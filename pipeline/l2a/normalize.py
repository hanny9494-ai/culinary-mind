#!/usr/bin/env python3
"""
l2a_normalize.py — L2a Stage 1
Normalize raw ingredient strings to canonical atoms using LLM.

Reads:  output/l2a/ingredient_seeds.json
Writes: output/l2a/canonical_map.json
        output/l2a/normalize_errors.json

API: qwen3.5-flash via DashScope (DASHSCOPE_API_KEY).
     Fallback: lingyaai proxy (L0_API_ENDPOINT / L0_API_KEY).
Concurrency: ThreadPoolExecutor with 4 workers.
"""

# MUST be first: kill proxy env vars before any network library loads
import os as _os
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY"):
    _os.environ.pop(_k, None)

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import requests
from tqdm import tqdm

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
L2A_DIR = ROOT / "output" / "l2a"
DEFAULT_INPUT = L2A_DIR / "ingredient_seeds.json"
DEFAULT_OUTPUT = L2A_DIR / "canonical_map.json"
ERRORS_OUTPUT = L2A_DIR / "normalize_errors.json"
PARTIAL_OUTPUT = L2A_DIR / "canonical_map_partial.jsonl"

# ── API config ────────────────────────────────────────────────────────────────
MODEL = "qwen3.5-flash"
MAX_CONCURRENCY = 4
MAX_RETRIES = 3
RETRY_DELAY = 2.0


def get_api_config() -> tuple[str, str]:
    """Return (base_url, api_key). qwen → DashScope, others → lingyaai."""
    # Kill proxy env to prevent requests from routing through local proxy
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        os.environ.pop(k, None)
    os.environ["no_proxy"] = "*"

    if MODEL.startswith("qwen"):
        key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if key:
            return "https://dashscope.aliyuncs.com/compatible-mode/v1", key
        print("WARNING: DASHSCOPE_API_KEY not set", file=sys.stderr)

    base = os.environ.get("L0_API_ENDPOINT", "").strip()
    key = os.environ.get("L0_API_KEY", "").strip()
    if base:
        if not base.endswith("/v1"):
            base += "/v1"
        return base, key
    return "https://dashscope.aliyuncs.com/compatible-mode/v1", os.environ.get("DASHSCOPE_API_KEY", "")


SYSTEM_PROMPT = (
    "You are a culinary ingredient normalization expert. "
    "Return only valid JSON, no markdown fences, no explanation."
)

USER_PROMPT_TEMPLATE = """\
Normalize these ingredient strings into canonical atoms.
Rules:
- Merge synonyms (e.g. scallion / green onion / spring onion → scallions)
- Merge singular/plural (tomato/tomatoes → tomato)
- Strip quantity modifiers and prep notes from the canonical name
- Preserve ALL ingredients, even low-frequency rare ones
  (truffle salt, squid ink, black garlic = separate canonicals)
- For items whose category is "other", reclassify to the correct category
- canonical_id: lowercase, underscores, ASCII only
- canonical_name_zh: provide best Chinese culinary translation
- confidence: "high" if obvious, "medium" if plausible, "low" if uncertain

Return JSON:
{{
  "canonicals": [
    {{"canonical_id": "garlic", "canonical_name_en": "garlic", "canonical_name_zh": "蒜", "category": "vegetable", "confidence": "high", "raw_variants": ["garlic", "garlic cloves"]}}
  ],
  "mapping": {{"garlic": "garlic", "garlic cloves": "garlic"}}
}}

Ingredients (raw_string | frequency):
{items_block}
"""


def call_llm(base_url: str, api_key: str, prompt_user: str) -> dict | None:
    """Synchronous LLM call with retries."""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": 0.1,
        "max_tokens": 8192,
        "enable_thinking": False,  # DashScope: skip reasoning tokens, 10x faster
    }

    # Use a session with explicit no-proxy to bypass any inherited env
    session = requests.Session()
    session.trust_env = False

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(url, headers=headers, json=payload, timeout=120)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])
            return json.loads(content)
        except Exception as exc:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
            else:
                return {"_error": str(exc)}
    return None


def merge_batch_result(result: dict, batch: list[dict], all_canonicals: dict, raw_to_canonical: dict) -> list[dict]:
    unmapped = []
    mapping = result.get("mapping", {})
    for c in result.get("canonicals", []):
        cid = c.get("canonical_id", "").strip()
        if not cid:
            continue
        if cid not in all_canonicals:
            all_canonicals[cid] = {
                "canonical_id": cid,
                "canonical_name_en": c.get("canonical_name_en", cid),
                "canonical_name_zh": c.get("canonical_name_zh", ""),
                "category": c.get("category", "other"),
                "confidence": c.get("confidence", "medium"),
                "raw_variants": list(c.get("raw_variants", [])),
                "external_ids": {},
            }
        else:
            existing = set(all_canonicals[cid]["raw_variants"])
            for rv in c.get("raw_variants", []):
                existing.add(rv)
            all_canonicals[cid]["raw_variants"] = sorted(existing)

    for entry in batch:
        raw = entry["item"]
        cid = mapping.get(raw)
        if cid:
            raw_to_canonical[raw] = cid
            if cid in all_canonicals and raw not in all_canonicals[cid]["raw_variants"]:
                all_canonicals[cid]["raw_variants"].append(raw)
        else:
            unmapped.append(entry)
    return unmapped


def chunk_list(lst, size):
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def build_batches(ingredients, batch_size, done_batch_keys):
    """Build batches with unique keys for resume support."""
    groups = defaultdict(list)
    for ing in ingredients:
        cat = ing.get("category_guess", "other")
        groups[cat].append(ing)
    batches = []
    for cat, items in sorted(groups.items()):
        for i, chunk in enumerate(chunk_list(items, batch_size)):
            batch_key = f"{cat}_{i}"
            if batch_key in done_batch_keys:
                continue
            batches.append((batch_key, cat, chunk))
    return batches


def load_resume_state(partial_path):
    """Load partial JSONL for resume. Each line is a batch result."""
    all_c = {}
    r2c = {}
    done_batch_keys = set()
    if not partial_path.exists():
        return all_c, r2c, done_batch_keys
    try:
        for line in partial_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            done_batch_keys.add(rec["batch_key"])
            for c in rec.get("canonicals", []):
                cid = c.get("canonical_id", "").strip()
                if not cid:
                    continue
                if cid not in all_c:
                    all_c[cid] = c
                else:
                    existing = set(all_c[cid].get("raw_variants", []))
                    for rv in c.get("raw_variants", []):
                        existing.add(rv)
                    all_c[cid]["raw_variants"] = sorted(existing)
            for raw, cid in rec.get("mapping", {}).items():
                r2c[raw] = cid
        print(f"Resumed {len(done_batch_keys)} batches, {len(all_c)} canonicals, {len(r2c)} mappings")
    except Exception as e:
        print(f"WARNING: resume load failed: {e}", file=sys.stderr)
    return all_c, r2c, done_batch_keys


def append_partial(partial_path, batch_key, result):
    """Append one batch result to partial JSONL — immediate persistence."""
    rec = {
        "batch_key": batch_key,
        "canonicals": result.get("canonicals", []),
        "mapping": result.get("mapping", {}),
    }
    with open(partial_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Normalize ingredient seeds to canonical L2a atoms.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading seeds from {args.input} ...")
    seeds_data = json.loads(args.input.read_text(encoding="utf-8"))
    items_key = "items" if "items" in seeds_data else "ingredients"
    ingredients = seeds_data[items_key]
    total_raw = len(ingredients)
    print(f"Total raw ingredients: {total_raw}")

    base_url, api_key = get_api_config()
    print(f"API: {base_url}, model: {MODEL}")

    all_canonicals: dict[str, Any] = {}
    raw_to_canonical: dict[str, str] = {}
    done_batch_keys: set[str] = set()

    # Always try resume from partial file
    all_canonicals, raw_to_canonical, done_batch_keys = load_resume_state(PARTIAL_OUTPUT)

    batches = build_batches(ingredients, args.batch_size, done_batch_keys)
    print(f"Batches to do: {len(batches)} (already done: {len(done_batch_keys)})")

    if args.dry_run:
        print("[DRY RUN] First batch only ...")
        batches = batches[:1]

    errors = []
    t0 = time.time()

    def process_batch(keyed_batch):
        batch_key, cat, batch = keyed_batch
        items_block = "\n".join(f"{e['item']} | {e.get('frequency', 0)}" for e in batch)
        prompt = USER_PROMPT_TEMPLATE.format(items_block=items_block)
        result = call_llm(base_url, api_key, prompt)
        return batch_key, cat, batch, result

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        futures = {pool.submit(process_batch, b): b for b in batches}
        pbar = tqdm(total=len(futures), desc="Normalizing", unit="batch")
        for future in as_completed(futures):
            batch_key, cat, batch, result = future.result()
            pbar.update(1)
            if result is None or "_error" in result:
                err = (result or {}).get("_error", "null")
                errors.append({"category": cat, "batch_size": len(batch), "error": err})
                tqdm.write(f"  [FAIL] {cat} ({len(batch)}): {err[:80]}")
            else:
                unmapped = merge_batch_result(result, batch, all_canonicals, raw_to_canonical)
                # Persist immediately
                append_partial(PARTIAL_OUTPUT, batch_key, result)
                if unmapped:
                    tqdm.write(f"  [WARN] {cat}: {len(unmapped)} unmapped")
        pbar.close()

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  Canonical atoms: {len(all_canonicals)}")
    print(f"  Mapped: {len(raw_to_canonical)} / {total_raw}")
    print(f"  Failed: {len(errors)}")

    if args.dry_run:
        print("\nPreview:")
        print(json.dumps({"canonicals": list(all_canonicals.values())[:3],
                          "mapping_sample": dict(list(raw_to_canonical.items())[:10])},
                         ensure_ascii=False, indent=2))
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "metadata": {
            "total_raw": total_raw, "total_canonical": len(all_canonicals),
            "model": MODEL, "created": str(date.today()),
            "unmapped": total_raw - len(raw_to_canonical), "failed_batches": len(errors),
        },
        "canonicals": sorted(all_canonicals.values(), key=lambda c: c["canonical_id"]),
        "raw_to_canonical": dict(sorted(raw_to_canonical.items())),
    }
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {args.output}")

    if errors:
        ERRORS_OUTPUT.write_text(json.dumps({"errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Errors: {ERRORS_OUTPUT}")


if __name__ == "__main__":
    main()
