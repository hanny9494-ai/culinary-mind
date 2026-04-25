#!/usr/bin/env python3
"""
L0 公式提取 — 灵雅 Gemini Flash 分类 + Gemini 3.1 Pro Thinking 提取
===================================================================
Step 2: Gemini Flash (分类 YES/NO)
Step 3: Gemini 3.1 Pro Thinking (SymPy 提取)
全部走灵雅 OpenAI 兼容接口，trust_env=False。

Usage:
    python3 scripts/l0_formula_gemini.py [--step 2|3|all] [--limit N] [--dry-run] [--concurrency 5]
    caffeinate -s nohup python3 -u scripts/l0_formula_gemini.py > output/l0_computable/gemini.log 2>&1 &
"""

import os
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_k, None)

import re, sys, json, asyncio, argparse, time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "output" / "l0_computable"
CANDIDATES_FILE = OUTPUT_DIR / "mvp_candidates.jsonl"
CLASSIFIED_FILE = OUTPUT_DIR / "mvp_classified.jsonl"
FORMULAS_FILE = OUTPUT_DIR / "mvp_formulas.jsonl"
STEP2_PROGRESS = OUTPUT_DIR / "gemini_step2_progress.json"
STEP3_PROGRESS = OUTPUT_DIR / "gemini_step3_progress.json"

API_ENDPOINT = os.environ.get("L0_API_ENDPOINT", "").rstrip("/")
API_KEY = os.environ.get("L0_API_KEY", "")

FLASH_MODEL = "gemini-2.5-flash"
PRO_MODEL = "gemini-3.1-pro-preview-thinking"

EXTRACTION_PROMPT = """You are an expert Scientific Knowledge Extractor. Analyze the scientific statement and extract any mathematical formula or physical law into strict JSON.

## Rules
1. Write reasoning in `reasoning` field FIRST.
2. `formula_type` must be one of: "scientific_law", "empirical_rule", "threshold_constant", or null if no formula.
3. SymPy syntax: use ** not ^, use exp() not e^x, use Eq() for thresholds, Piecewise for conditionals.
4. Symbol classification: variables (change over time/space), parameters (condition-specific), constants (fixed values).
5. Units: NEVER convert. Keep original units from text.
6. Missing constants: use _placeholder suffix. NEVER fill from pre-training knowledge.

## Output (raw JSON only, no markdown fences)
{
  "has_formula": boolean,
  "reasoning": "...",
  "formula_type": "scientific_law"|"empirical_rule"|"threshold_constant"|null,
  "formula_name": string|null,
  "sympy_expression": string|null,
  "symbols": {
    "variables": [{"symbol":"str","description":"str","unit":"str|null"}],
    "parameters": [{"symbol":"str","description":"str","unit":"str|null"}],
    "constants": [{"symbol":"str","description":"str","unit":"str|null"}]
  }
}"""


def parse_json_response(raw: str) -> dict | None:
    raw = raw.strip()
    if raw.startswith("```"):
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m: raw = m.group(0)
    if not raw.startswith("{"):
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m: raw = m.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def lingya_chat(session, model: str, messages: list, max_tokens: int, sem):
    """Call Lingya OpenAI-compatible chat endpoint."""
    url = f"{API_ENDPOINT}/v1/chat/completions"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}

    import aiohttp
    async with sem:
        for attempt in range(3):
            try:
                async with session.post(url, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    if resp.status == 429:
                        wait = 3 * (attempt + 1)
                        print(f"    [429 rate limit, wait {wait}s]", file=sys.stderr)
                        await asyncio.sleep(wait)
                        continue
                    if resp.status != 200:
                        err = await resp.text()
                        print(f"    [API {resp.status}] {err[:200]}", file=sys.stderr)
                        return None
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                print(f"    [error] {type(e).__name__}: {e}", file=sys.stderr)
                return None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: Gemini Flash 分类
# ══════════════════════════════════════════════════════════════════════════════

async def run_step2(candidates: list[dict], concurrency: int, dry_run: bool):
    processed_ids: set[str] = set()
    if STEP2_PROGRESS.exists():
        try:
            prog = json.loads(STEP2_PROGRESS.read_text())
            processed_ids = set(prog.get("processed_ids", []))
            print(f"  Resuming: {len(processed_ids)} already processed")
        except: pass

    to_process = [c for c in candidates if c.get("id","") not in processed_ids]
    print(f"  To classify: {len(to_process)} (skipping {len(processed_ids)} done)")

    if dry_run:
        print(f"  [dry-run] Would call {FLASH_MODEL} on {len(to_process)} entries")
        return
    if not to_process:
        print("  Nothing to process.")
        return

    import aiohttp
    sem = asyncio.Semaphore(concurrency)
    conn = aiohttp.TCPConnector(limit=concurrency*2, ssl=False)
    count_true = count_false = count_err = 0

    async with aiohttp.ClientSession(connector=conn, trust_env=False) as session:
        batch_size = concurrency * 3
        with open(CLASSIFIED_FILE, "a", encoding="utf-8") as outf:
            for bs in range(0, len(to_process), batch_size):
                batch = to_process[bs:bs+batch_size]

                async def classify(entry):
                    stmt = entry.get("scientific_statement","")
                    quote = entry.get("citation_quote","")
                    msg = [{"role":"user","content":
                        f"Does this scientific statement contain a computable mathematical relationship "
                        f"(formula, equation, rate law, threshold constant, or quantitative rule)? "
                        f"Answer ONLY 'YES' or 'NO'.\n\nStatement: {stmt}\nContext: {quote}"}]
                    text = await lingya_chat(session, FLASH_MODEL, msg, 300, sem)
                    if text is None: return entry, None
                    return entry, text.strip().upper().startswith("YES")

                results = await asyncio.gather(*[classify(e) for e in batch])

                for entry, has_formula in results:
                    eid = entry["id"]
                    processed_ids.add(eid)
                    if has_formula is None:
                        count_err += 1
                        continue
                    entry["has_computable_relation"] = has_formula
                    outf.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    outf.flush()
                    if has_formula: count_true += 1
                    else: count_false += 1

                STEP2_PROGRESS.write_text(json.dumps({"processed_ids": list(processed_ids)}))
                total = len(processed_ids)
                pct = 100*total/len(candidates) if candidates else 0
                print(f"  [{total}/{len(candidates)}] ({pct:.1f}%) true={count_true} false={count_false} err={count_err}")

    print(f"\n  Classification done: {count_true} true, {count_false} false, {count_err} errors")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Gemini 3.1 Pro Thinking 提取
# ══════════════════════════════════════════════════════════════════════════════

async def run_step3(concurrency: int, dry_run: bool):
    if not CLASSIFIED_FILE.exists():
        print("ERROR: mvp_classified.jsonl not found. Run step 2 first.")
        sys.exit(1)

    true_entries = []
    with open(CLASSIFIED_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                e = json.loads(line)
                if e.get("has_computable_relation"):
                    true_entries.append(e)
            except: continue

    print(f"  Entries with has_computable_relation=true: {len(true_entries)}")

    processed_ids: set[str] = set()
    if STEP3_PROGRESS.exists():
        try:
            prog = json.loads(STEP3_PROGRESS.read_text())
            processed_ids = set(prog.get("processed_ids", []))
            print(f"  Resuming: {len(processed_ids)} already processed")
        except: pass

    to_process = [e for e in true_entries if e.get("id","") not in processed_ids]
    print(f"  To extract: {len(to_process)}")

    if dry_run:
        for e in to_process[:5]:
            print(f"    - {e['id']}: {e.get('scientific_statement','')[:80]}")
        return
    if not to_process:
        print("  Nothing to process.")
        return

    import aiohttp
    sem = asyncio.Semaphore(concurrency)
    conn = aiohttp.TCPConnector(limit=concurrency*2, ssl=False)
    count_formula = count_no = count_err = 0

    async with aiohttp.ClientSession(connector=conn, trust_env=False) as session:
        batch_size = concurrency * 2
        with open(FORMULAS_FILE, "a", encoding="utf-8") as outf:
            for bs in range(0, len(to_process), batch_size):
                batch = to_process[bs:bs+batch_size]

                async def extract(entry):
                    stmt = entry.get("scientific_statement","")
                    conds = entry.get("boundary_conditions",[])
                    quote = entry.get("citation_quote","")
                    msgs = [
                        {"role":"system","content": EXTRACTION_PROMPT},
                        {"role":"user","content":
                            f"Extract the formula from:\n"
                            f"- scientific_statement: {stmt}\n"
                            f"- boundary_conditions: {conds}\n"
                            f"- citation_quote: {quote}"}
                    ]
                    text = await lingya_chat(session, PRO_MODEL, msgs, 2000, sem)
                    if text is None: return entry, None
                    return entry, parse_json_response(text)

                results = await asyncio.gather(*[extract(e) for e in batch])

                for entry, formula in results:
                    eid = entry["id"]
                    processed_ids.add(eid)
                    if formula is None:
                        count_err += 1
                        continue
                    if formula.get("has_formula"):
                        count_formula += 1
                        entry_out = {k:v for k,v in entry.items()}
                        entry_out["formula"] = formula
                        outf.write(json.dumps(entry_out, ensure_ascii=False)+"\n")
                        outf.flush()
                        ftype = formula.get("formula_type","?")
                        fname = (formula.get("formula_name") or "")[:50]
                        print(f"  ✓ [{count_formula}] {eid} [{ftype}] {fname}")
                    else:
                        count_no += 1

                STEP3_PROGRESS.write_text(json.dumps({"processed_ids": list(processed_ids)}))
                total = len(processed_ids)
                print(f"  --- {total}/{len(true_entries)} | formulas={count_formula} no={count_no} err={count_err}")

    print(f"\n{'='*60}")
    print(f"EXTRACTION COMPLETE ({PRO_MODEL})")
    print(f"{'='*60}")
    print(f"  Formulas: {count_formula} | No formula: {count_no} | Errors: {count_err}")
    if FORMULAS_FILE.exists():
        total = sum(1 for l in open(FORMULAS_FILE) if l.strip())
        print(f"  Total in file: {total}")


def main():
    parser = argparse.ArgumentParser(description="L0 公式提取 — 灵雅 Gemini")
    parser.add_argument("--step", choices=["2","3","all"], default="all")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()

    if not API_ENDPOINT or not API_KEY:
        print("ERROR: L0_API_ENDPOINT and L0_API_KEY must be set"); sys.exit(1)

    print("="*60)
    print("L0 Formula Extraction — Lingya API")
    print(f"  Step 2: {FLASH_MODEL} (classification)")
    print(f"  Step 3: {PRO_MODEL} (extraction)")
    print(f"  Concurrency: {args.concurrency}")
    print(f"  Endpoint: {API_ENDPOINT}")
    print("="*60)

    if args.step in ("2","all"):
        if not CANDIDATES_FILE.exists():
            print(f"ERROR: {CANDIDATES_FILE} not found. Run Step 1 first."); sys.exit(1)
        candidates = []
        with open(CANDIDATES_FILE, encoding="utf-8") as f:
            for line in f:
                l = line.strip()
                if l:
                    try: candidates.append(json.loads(l))
                    except: continue
        print(f"\n  Loaded {len(candidates)} candidates")
        if args.limit:
            candidates = candidates[:args.limit]
            print(f"  Limited to {args.limit}")
        print(f"\n--- STEP 2: {FLASH_MODEL} Classification ---")
        asyncio.run(run_step2(candidates, args.concurrency, args.dry_run))

    if args.step in ("3","all"):
        print(f"\n--- STEP 3: {PRO_MODEL} Extraction ---")
        asyncio.run(run_step3(args.concurrency, args.dry_run))

    print("\nDone.")

if __name__ == "__main__":
    main()
