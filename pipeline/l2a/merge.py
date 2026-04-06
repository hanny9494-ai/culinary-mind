#!/usr/bin/env python3
"""
l2a_merge_canonicals.py — L2a Stage 2
Global merge of canonical atoms using Opus 1M context.

Round 2: Send all ~13K canonicals to Opus in one call → identify merge groups.
Round 3: Re-map unmapped raw strings using Flash + merged canonical list.

Reads:  output/l2a/canonical_map.json (from round 1)
Writes: output/l2a/canonical_map_merged.json (final)
        output/l2a/merge_groups.json (audit: what got merged)
"""

# Kill proxy before any imports
import os as _os
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY"):
    _os.environ.pop(_k, None)

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
L2A_DIR = ROOT / "output" / "l2a"
INPUT_FILE = L2A_DIR / "canonical_map.json"
OUTPUT_FILE = L2A_DIR / "canonical_map_merged.json"
MERGE_GROUPS_FILE = L2A_DIR / "merge_groups.json"

# Opus via lingyaai
OPUS_BASE = os.environ.get("L0_API_ENDPOINT", "https://api.lingyaai.cn").rstrip("/")
OPUS_KEY = os.environ.get("L0_API_KEY", "")
OPUS_MODEL = "claude-opus-4-6"

# Flash via DashScope
FLASH_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
FLASH_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
FLASH_MODEL = "qwen3.5-flash"


def call_api(base_url, api_key, model, messages, max_tokens=16384, temperature=0.1, thinking=False):
    """Generic API call. Returns content string or raises."""
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    url += "/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if not thinking:
        payload["enable_thinking"] = False

    session = requests.Session()
    session.trust_env = False

    for attempt in range(3):
        try:
            resp = session.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=600,  # Opus with 150K+ input may take a while
            )
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            return content
        except Exception as e:
            if attempt < 2:
                print(f"  Retry {attempt+1}: {e}")
                time.sleep(5 * (attempt + 1))
            else:
                raise


def extract_json(content):
    """Extract JSON from potentially markdown-fenced response."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1])
    return json.loads(content)


# ── Round 2: Opus global merge ────────────────────────────────────────────────

OPUS_SYSTEM = """You are a culinary ingredient ontology expert. Your task is to identify canonical ingredient atoms that should be merged because they refer to the same ingredient.

Rules:
- Merge cross-language duplicates: "garlic" and "蒜" and "大蒜" are the same
- Merge singular/plural leftovers: "walnut" and "walnuts"
- Merge obvious synonyms: "scallion" and "green_onion" and "spring_onion"
- Merge different granularity ONLY if clearly the same thing: "soy_sauce" and "soy" should NOT merge
- Do NOT merge related-but-different items: "garlic" ≠ "garlic_powder", "chicken" ≠ "chicken_stock"
- For each merge group, pick the most standard English canonical_id as primary
- Return ONLY valid JSON array, no explanation"""

OPUS_USER_TEMPLATE = """Here are {count} canonical ingredient atoms. Find all groups that should be merged.

Return JSON array of merge groups:
[
  {{"primary": "garlic", "aliases": ["蒜", "大蒜", "garlic_clove"]}},
  {{"primary": "scallion", "aliases": ["green_onion", "spring_onion", "葱"]}}
]

Only include groups where merging is needed (2+ items). Skip singletons.

Canonical atoms (id | english | chinese | category):
{tsv}"""


def round2_opus_merge(canonicals):
    """Send all canonicals to Opus, get merge groups back."""
    tsv_lines = [
        f"{c['canonical_id']}|{c['canonical_name_en']}|{c.get('canonical_name_zh','')}|{c['category']}"
        for c in canonicals
    ]
    tsv = "\n".join(tsv_lines)
    count = len(canonicals)

    print(f"\n=== Round 2: Opus global merge ===")
    print(f"Sending {count} canonicals ({len(tsv)} chars) to {OPUS_MODEL}...")

    messages = [
        {"role": "system", "content": OPUS_SYSTEM},
        {"role": "user", "content": OPUS_USER_TEMPLATE.format(count=count, tsv=tsv)},
    ]

    t0 = time.time()
    content = call_api(OPUS_BASE, OPUS_KEY, OPUS_MODEL, messages, max_tokens=32768, temperature=0.0)
    elapsed = time.time() - t0
    print(f"Opus responded in {elapsed:.0f}s, {len(content)} chars")

    merge_groups = extract_json(content)
    print(f"Merge groups found: {len(merge_groups)}")
    return merge_groups


def apply_merges(canonicals_map, raw_to_canonical, merge_groups):
    """Apply merge groups: redirect aliases to primary."""
    merged_count = 0
    for group in merge_groups:
        primary_id = group.get("primary", "").strip()
        aliases = group.get("aliases", [])
        if not primary_id or not aliases:
            continue

        # Ensure primary exists
        if primary_id not in canonicals_map:
            # Try to find it
            for a in aliases:
                if a in canonicals_map:
                    primary_id = a
                    aliases = [x for x in aliases if x != a] + [group["primary"]]
                    break

        if primary_id not in canonicals_map:
            continue

        primary = canonicals_map[primary_id]

        for alias_id in aliases:
            alias_id = alias_id.strip()
            if alias_id not in canonicals_map or alias_id == primary_id:
                continue

            alias = canonicals_map[alias_id]

            # Merge raw_variants
            existing = set(primary.get("raw_variants", []))
            for rv in alias.get("raw_variants", []):
                existing.add(rv)
            primary["raw_variants"] = sorted(existing)

            # Merge zh name if primary is missing it
            if not primary.get("canonical_name_zh") and alias.get("canonical_name_zh"):
                primary["canonical_name_zh"] = alias["canonical_name_zh"]

            # Redirect raw_to_canonical mappings
            for raw, cid in list(raw_to_canonical.items()):
                if cid == alias_id:
                    raw_to_canonical[raw] = primary_id

            # Remove alias from canonicals
            del canonicals_map[alias_id]
            merged_count += 1

    return merged_count


# ── Round 3: Flash re-map unmapped ────────────────────────────────────────────

FLASH_SYSTEM = "You are a culinary ingredient matching expert. Return only valid JSON, no markdown fences."

FLASH_USER_TEMPLATE = """Match each unmapped ingredient string to the closest canonical atom from the list below.
If no good match exists, set canonical_id to "NEW" and suggest a new canonical.

Return JSON:
{{
  "mappings": [
    {{"raw": "fresh garlic cloves", "canonical_id": "garlic", "confidence": "high"}},
    {{"raw": "xyz rare thing", "canonical_id": "NEW", "new_canonical": "xyz_rare_thing", "new_name_zh": "稀有物", "confidence": "low"}}
  ]
}}

Canonical atoms (first 200 shown for context, {total} total):
{canonical_sample}

Unmapped items to match:
{unmapped_block}"""


def round3_flash_remap(canonicals_map, raw_to_canonical, all_ingredients):
    """Re-map unmapped raw strings using Flash."""
    items_key = "items" if isinstance(all_ingredients, dict) and "items" in all_ingredients else "ingredients"
    if isinstance(all_ingredients, dict):
        ingredients = all_ingredients[items_key]
    else:
        ingredients = all_ingredients

    # Find unmapped
    unmapped = [ing for ing in ingredients if ing["item"] not in raw_to_canonical]
    if not unmapped:
        print("No unmapped items!")
        return 0

    print(f"\n=== Round 3: Flash re-map {len(unmapped)} unmapped items ===")

    # Build canonical sample (top 500 by variant count)
    sorted_canonicals = sorted(canonicals_map.values(), key=lambda c: len(c.get("raw_variants", [])), reverse=True)
    canonical_sample = "\n".join(
        f"{c['canonical_id']}|{c['canonical_name_en']}|{c.get('canonical_name_zh','')}"
        for c in sorted_canonicals[:500]
    )
    total = len(canonicals_map)

    # Process in batches of 100
    batch_size = 100
    new_mapped = 0
    new_canonicals_added = 0

    batches = [unmapped[i:i+batch_size] for i in range(0, len(unmapped), batch_size)]
    pbar = tqdm(total=len(batches), desc="Re-mapping", unit="batch")

    for batch in batches:
        unmapped_block = "\n".join(f"{e['item']} | {e.get('frequency', 0)}" for e in batch)
        messages = [
            {"role": "system", "content": FLASH_SYSTEM},
            {"role": "user", "content": FLASH_USER_TEMPLATE.format(
                total=total, canonical_sample=canonical_sample, unmapped_block=unmapped_block
            )},
        ]

        try:
            content = call_api(FLASH_BASE, FLASH_KEY, FLASH_MODEL, messages, max_tokens=8192)
            result = extract_json(content)

            for m in result.get("mappings", []):
                raw = m.get("raw", "")
                cid = m.get("canonical_id", "")
                if not raw or not cid:
                    continue

                if cid == "NEW":
                    new_id = m.get("new_canonical", "").strip()
                    if new_id and new_id not in canonicals_map:
                        canonicals_map[new_id] = {
                            "canonical_id": new_id,
                            "canonical_name_en": new_id.replace("_", " "),
                            "canonical_name_zh": m.get("new_name_zh", ""),
                            "category": "other",
                            "confidence": m.get("confidence", "low"),
                            "raw_variants": [raw],
                            "external_ids": {},
                        }
                        raw_to_canonical[raw] = new_id
                        new_canonicals_added += 1
                        new_mapped += 1
                elif cid in canonicals_map:
                    raw_to_canonical[raw] = cid
                    if raw not in canonicals_map[cid].get("raw_variants", []):
                        canonicals_map[cid]["raw_variants"].append(raw)
                    new_mapped += 1

        except Exception as e:
            tqdm.write(f"  [FAIL] batch: {e}")

        pbar.update(1)

    pbar.close()
    print(f"  Re-mapped: {new_mapped}, New canonicals: {new_canonicals_added}")
    return new_mapped


def main():
    parser = argparse.ArgumentParser(description="L2a Round 2+3: global merge + re-map")
    parser.add_argument("--input", type=Path, default=INPUT_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    parser.add_argument("--skip-opus", action="store_true", help="Skip Opus merge, only do Flash re-map")
    parser.add_argument("--skip-flash", action="store_true", help="Skip Flash re-map, only do Opus merge")
    parser.add_argument("--dry-run", action="store_true", help="Show stats only, don't call APIs")
    args = parser.parse_args()

    print(f"Loading {args.input} ...")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    canonicals_list = data["canonicals"]
    raw_to_canonical = data["raw_to_canonical"]

    # Also load original seeds for unmapped items
    seeds_path = L2A_DIR / "ingredient_seeds.json"
    seeds_data = json.loads(seeds_path.read_text(encoding="utf-8"))

    # Build canonicals map
    canonicals_map = {c["canonical_id"]: c for c in canonicals_list}

    print(f"Canonicals: {len(canonicals_map)}")
    print(f"Mapped: {len(raw_to_canonical)}")
    print(f"Unmapped: {data['metadata']['total_raw'] - len(raw_to_canonical)}")

    if args.dry_run:
        print("\n[DRY RUN] Would call Opus with ~153K tokens, then Flash for unmapped.")
        return

    merge_groups = []

    # Round 2: Opus
    if not args.skip_opus:
        merge_groups = round2_opus_merge(canonicals_list)

        # Save merge groups for audit
        MERGE_GROUPS_FILE.write_text(
            json.dumps(merge_groups, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Saved merge groups to {MERGE_GROUPS_FILE}")

        # Apply merges
        merged = apply_merges(canonicals_map, raw_to_canonical, merge_groups)
        print(f"Applied {merged} merges → {len(canonicals_map)} canonicals remaining")

    # Round 3: Flash re-map
    if not args.skip_flash:
        round3_flash_remap(canonicals_map, raw_to_canonical, seeds_data)

    # Write final output
    total_raw = data["metadata"]["total_raw"]
    final = {
        "metadata": {
            "total_raw": total_raw,
            "total_canonical": len(canonicals_map),
            "mapped": len(raw_to_canonical),
            "unmapped": total_raw - len(raw_to_canonical),
            "merge_groups_applied": len(merge_groups),
            "model_merge": OPUS_MODEL,
            "model_remap": FLASH_MODEL,
            "created": str(date.today()),
        },
        "canonicals": sorted(canonicals_map.values(), key=lambda c: c["canonical_id"]),
        "raw_to_canonical": dict(sorted(raw_to_canonical.items())),
    }

    args.output.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFinal: {len(canonicals_map)} canonicals, {len(raw_to_canonical)}/{total_raw} mapped")
    print(f"Wrote: {args.output}")


if __name__ == "__main__":
    main()
