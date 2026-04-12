#!/usr/bin/env python3
"""
L0 公式提取 MVP Pipeline — Steps 1, 2, 3
========================================
Step 1: Regex candidate filtering (no LLM, zero cost)
Step 2: 9b binary classification via Ollama (local, zero cost)
Step 3: Opus formula extraction via Lingya API (3 concurrent)

Usage:
    python3 scripts/l0_formula_extract.py [--step 1|2|3|all] [--limit N] [--dry-run]

Long-running note: for Step 2/3, run with:
    caffeinate -s nohup python3 scripts/l0_formula_extract.py --step 2 &
"""

# ── Clear proxy env vars first (local proxy 127.0.0.1:7890 must be bypassed) ──
import os
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_k, None)

import re
import sys
import json
import time
import asyncio
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Iterator

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "output" / "l0_computable"
CANDIDATES_FILE = OUTPUT_DIR / "mvp_candidates.jsonl"
CLASSIFIED_FILE = OUTPUT_DIR / "mvp_classified.jsonl"
FORMULAS_FILE = OUTPUT_DIR / "mvp_formulas.jsonl"
STEP2_PROGRESS = OUTPUT_DIR / "step2_progress.json"
STEP3_PROGRESS = OUTPUT_DIR / "step3_progress.json"

# ── Target domains for煎牛排 + 炸鸡煳 ──────────────────────────────────────────
TARGET_DOMAINS = {
    "thermal_dynamics",
    "protein_science",
    "texture_rheology",
    "lipid_science",
    "carbohydrate",
    "maillard_caramelization",
    "water_activity",
}

# ── Step 1 filter keywords (case-insensitive) ─────────────────────────────────
CONTENT_KEYWORDS = re.compile(
    r"°[CF]|%|ratio|rate|equation|kinetics|activation|constant|threshold|onset|"
    r"denaturation|gelatinization|\bTg\b|\bAw\b|denature|maillard|browning|viscosity|"
    r"diffusion|conductivity|enthalpy|latent|evaporation|absorption|gelatin|collagen|"
    r"myosin|actin|\bstarch\b|gluten|crisp|crust|Q10|Arrhenius",
    re.IGNORECASE,
)

QUOTE_FORMULA_MARKERS = re.compile(
    r"=|formula|law|coefficient|\bk\s*=|\brate\s*=|Q10|Arrhenius|Fick|Fourier|Henry",
    re.IGNORECASE,
)

DIGIT_RE = re.compile(r"\d")

# ── Opus system prompt (verbatim from Gemini Round 2 + Round 3 patches) ────────
OPUS_SYSTEM_PROMPT = """You are an expert Scientific Knowledge Extractor. Your task is to analyze scientific statements and citation quotes, and extract underlying mathematical formulas or physical laws into a strict JSON format.

## Extraction Rules & SymPy Syntax
1. **Chain of Thought (CoT)**: Always write your reasoning in the `reasoning` field BEFORE extracting the formula. Analyze if a formula exists, identify its components, and determine if it's complete or partial.
2. **Formula Types**:
   - "scientific_law": Pure physical/chemical relationships.
   - "empirical_rule": Culinary rules of thumb and operational heuristics.
   - "threshold_constant": Critical temperature points, pH levels, or state-change thresholds. Use Eq() for these. Example: "Ovotransferrin denatures at 61°C" → sympy_expression: "Eq(T_denature_ovotransferrin, 61)"
   - If no mathematical relationship is stated or strongly implied, set has_formula: false.
3. **SymPy strict syntax**:
   - Use ** for exponentiation, NEVER use ^ (e.g., x**2, not x^2).
   - Use exp() for exponential functions, NEVER use e**x or e^x (e.g., A * exp(-Ea / (R * T))).
   - For conditional formulas, use Piecewise: Piecewise((expr1, cond1), (expr2, cond2)).
   - For thresholds/constants, use Eq(): Eq(symbol, value).
4. **Symbol Classification**:
   - variables: State variables that change over time/space (e.g., Temperature T, Time t, Concentration C).
   - parameters: Condition-specific inputs or boundary conditions (e.g., target temperature 130°C, initial mass).
   - constants: Universal or material-specific fixed values (e.g., Ideal Gas Constant R, activation energy Ea).
5. **Units**: NEVER convert units. Keep the exact units mentioned in the text.
6. **Partial formulas**: If the text implies a known relationship but omits specific constants, use readable placeholders (e.g., k_placeholder, Ea_placeholder). Use formula_type "scientific_law" or "empirical_rule" as appropriate; note partial nature in reasoning.
7. **ANTI-HALLUCINATION**: Do NOT fill in constants from your pre-training knowledge. Only use values explicitly stated in the text. Missing values MUST use _placeholder suffix.

## Output Format
CRITICAL: You must output ONLY valid, raw JSON. Do NOT wrap the JSON in markdown code blocks (NO ```json). Your response must begin strictly with the { character and end with }.

Output schema:
{
  "has_formula": boolean,
  "reasoning": "Step-by-step analysis of the text...",
  "formula_type": "scientific_law" | "empirical_rule" | "threshold_constant" | null,
  "formula_name": string | null,
  "sympy_expression": string | null,
  "symbols": {
    "variables": [{"symbol": "string", "description": "string", "unit": "string or null"}],
    "parameters": [{"symbol": "string", "description": "string", "unit": "string or null"}],
    "constants": [{"symbol": "string", "description": "string", "unit": "string or null"}]
  }
}"""


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: Candidate filtering
# ══════════════════════════════════════════════════════════════════════════════

def iter_stage4_entries() -> Iterator[dict]:
    """Yield all entries from all stage4_*/stage4_deduped.jsonl files."""
    stage4_dirs = sorted(REPO_ROOT.glob("output/stage4_*/"))
    # Also check output/stage4/ (the merged file)
    merged = REPO_ROOT / "output" / "stage4" / "stage4_deduped.jsonl"

    files = []
    for d in stage4_dirs:
        jsonl = d / "stage4_deduped.jsonl"
        if jsonl.exists():
            files.append((d.name, jsonl))
    if merged.exists():
        files.append(("stage4_merged", merged))

    for book_name, fpath in files:
        with open(fpath, encoding="utf-8") as f:
            for line_idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Assign id if missing
                if "id" not in entry:
                    # Remove "stage4_" prefix for cleaner id
                    clean_name = book_name.replace("stage4_", "")
                    entry["id"] = f"{clean_name}_{line_idx:06d}"
                entry["source_book"] = book_name
                yield entry


def matches_step1_filter(entry: dict) -> bool:
    """Return True if entry is a candidate for formula extraction."""
    domain = entry.get("domain", "")
    if domain not in TARGET_DOMAINS:
        return False

    stmt = entry.get("scientific_statement", "") or ""
    quote = entry.get("citation_quote", "") or ""
    combined = stmt + " " + quote

    # Must contain digits somewhere
    has_digits = bool(DIGIT_RE.search(combined))

    # Primary: digits + domain keyword in content
    if has_digits and CONTENT_KEYWORDS.search(combined):
        return True

    # Secondary: formula marker in citation quote
    if QUOTE_FORMULA_MARKERS.search(quote):
        return True

    return False


def run_step1(limit: int = 0, dry_run: bool = False) -> int:
    """Step 1: Regex filter. Returns count of candidates."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("STEP 1: Candidate filtering")
    print("=" * 60)

    candidates = []
    total_scanned = 0

    for entry in iter_stage4_entries():
        total_scanned += 1
        if matches_step1_filter(entry):
            candidates.append(entry)
        if limit and total_scanned >= limit:
            break
        if total_scanned % 5000 == 0:
            print(f"  Scanned {total_scanned:,} entries, found {len(candidates):,} candidates...")

    print(f"\nScanned {total_scanned:,} total entries")
    print(f"Found {len(candidates):,} candidates in target domains")

    if dry_run:
        print("[dry-run] Skipping write")
        if candidates:
            print(f"\nSample candidate:")
            print(json.dumps(candidates[0], ensure_ascii=False, indent=2)[:500])
        return len(candidates)

    with open(CANDIDATES_FILE, "w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"Saved → {CANDIDATES_FILE}")
    return len(candidates)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: 9b binary classification via Ollama
# ══════════════════════════════════════════════════════════════════════════════

def call_ollama_9b(stmt: str, quote: str) -> bool:
    """Call Ollama qwen3.5:9b. Returns True if has computable relation."""
    prompt = (
        "Does this scientific statement contain a computable mathematical relationship "
        "where one variable depends on another (like a formula, equation, rate law, or "
        "threshold constant)? Answer only YES or NO.\n\n"
        f"Statement: {stmt}\n"
        f"Context: {quote}"
    )

    payload = json.dumps({
        "model": "qwen3.5:9b",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 10},
    }).encode()

    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            response_text = result.get("response", "").strip().upper()
            return response_text.startswith("YES")
    except Exception as e:
        print(f"  [Ollama error] {e}", file=sys.stderr)
        return False


def run_step2(limit: int = 0, dry_run: bool = False) -> tuple[int, int]:
    """Step 2: 9b classification. Returns (total, classified_true)."""
    if not CANDIDATES_FILE.exists():
        print("ERROR: mvp_candidates.jsonl not found. Run Step 1 first.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("STEP 2: 9b binary classification (Ollama qwen3.5:9b)")
    print("=" * 60)

    # Load resume state
    processed_ids: set[str] = set()
    if STEP2_PROGRESS.exists():
        try:
            prog = json.loads(STEP2_PROGRESS.read_text())
            processed_ids = set(prog.get("processed_ids", []))
            print(f"  Resuming: {len(processed_ids)} already processed")
        except Exception:
            pass

    # Load all candidates
    candidates = []
    with open(CANDIDATES_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    candidates.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    print(f"  Loaded {len(candidates):,} candidates")

    if limit:
        candidates = candidates[:limit]

    # Load already-classified results for dedup
    existing: dict[str, dict] = {}
    if CLASSIFIED_FILE.exists():
        with open(CLASSIFIED_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        e = json.loads(line)
                        existing[e["id"]] = e
                    except Exception:
                        continue

    count_true = sum(1 for e in existing.values() if e.get("has_computable_relation"))

    with open(CLASSIFIED_FILE, "a", encoding="utf-8") as outf:
        for idx, entry in enumerate(candidates):
            eid = entry["id"]
            if eid in processed_ids:
                continue

            if dry_run:
                print(f"  [dry-run] Would classify: {eid}")
                if idx >= 5:
                    print(f"  [dry-run] ... and {len(candidates) - 6} more")
                    break
                continue

            stmt = entry.get("scientific_statement", "") or ""
            quote = entry.get("citation_quote", "") or ""

            result = call_ollama_9b(stmt, quote)
            entry["has_computable_relation"] = result

            if result:
                count_true += 1

            outf.write(json.dumps(entry, ensure_ascii=False) + "\n")
            processed_ids.add(eid)

            # Save progress every 50 entries
            if len(processed_ids) % 50 == 0:
                STEP2_PROGRESS.write_text(json.dumps({"processed_ids": list(processed_ids)}))
                print(f"  [{idx+1}/{len(candidates)}] classified {len(processed_ids)} — {count_true} true")

        if not dry_run:
            STEP2_PROGRESS.write_text(json.dumps({"processed_ids": list(processed_ids)}))

    total = len(processed_ids)
    count_false = total - count_true
    print(f"\nClassification complete:")
    print(f"  Total classified: {total:,}")
    print(f"  has_computable_relation=true:  {count_true:,}")
    print(f"  has_computable_relation=false: {count_false:,}")
    return total, count_true


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Opus formula extraction via Lingya API
# ══════════════════════════════════════════════════════════════════════════════

def build_opus_user_message(entry: dict) -> str:
    stmt = entry.get("scientific_statement", "")
    conditions = entry.get("boundary_conditions", [])
    quote = entry.get("citation_quote", "")
    return (
        f"Please extract the formula from the following input:\n"
        f"- scientific_statement: {stmt}\n"
        f"- boundary_conditions: {conditions}\n"
        f"- citation_quote: {quote}"
    )


def parse_opus_response(raw: str) -> dict | None:
    """Strip markdown fences and parse JSON from Opus response."""
    raw = raw.strip()
    # Strip markdown code fences
    if raw.startswith("```"):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
    # Also try to find JSON object if response has prefix text
    if not raw.startswith("{"):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def call_opus_async(session, endpoint: str, api_key: str, entry: dict) -> dict | None:
    """Call Opus via Lingya API asynchronously. Returns parsed formula dict or None."""
    try:
        import aiohttp as _aiohttp
    except ImportError:
        return call_opus_sync(endpoint, api_key, entry)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "claude-opus-4-5",
        "max_tokens": 2000,
        "temperature": 0,
        "system": OPUS_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": build_opus_user_message(entry)}],
    }

    try:
        async with session.post(
            f"{endpoint}/messages",
            headers=headers,
            json=payload,
            timeout=_aiohttp.ClientTimeout(total=120),
        ) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                print(f"  [Opus API error {resp.status}] {err_text[:200]}", file=sys.stderr)
                return None
            data = await resp.json()
            raw = data["content"][0]["text"]
            return parse_opus_response(raw)
    except Exception as e:
        print(f"  [Opus async error] {e}", file=sys.stderr)
        return None


def call_opus_sync(endpoint: str, api_key: str, entry: dict) -> dict | None:
    """Sync fallback for Opus API call using urllib."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    payload = json.dumps({
        "model": "claude-opus-4-5",
        "max_tokens": 2000,
        "temperature": 0,
        "system": OPUS_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": build_opus_user_message(entry)}],
    }).encode()

    req = urllib.request.Request(
        f"{endpoint}/messages",
        data=payload,
        headers=headers,
    )

    # Disable proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    try:
        with opener.open(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
            raw = data["content"][0]["text"]
            return parse_opus_response(raw)
    except Exception as e:
        print(f"  [Opus sync error] {e}", file=sys.stderr)
        return None


async def run_step3_async(
    entries_to_process: list[dict],
    endpoint: str,
    api_key: str,
    outf,
    processed_ids: set[str],
    count_formulas: list,
) -> None:
    """Process entries 3 at a time with asyncio."""
    try:
        import aiohttp
        connector = aiohttp.TCPConnector(ssl=False)
        trust_env = False
        async with aiohttp.ClientSession(connector=connector, trust_env=trust_env) as session:
            semaphore = asyncio.Semaphore(3)

            async def process_one(entry: dict):
                async with semaphore:
                    eid = entry["id"]
                    formula = await call_opus_async(session, endpoint, api_key, entry)

                    if formula is None:
                        print(f"  [skip] {eid} — API error or null response")
                        processed_ids.add(eid)
                        return

                    entry_out = {k: v for k, v in entry.items()}
                    entry_out["formula"] = formula

                    if formula.get("has_formula"):
                        count_formulas.append(1)
                        outf.write(json.dumps(entry_out, ensure_ascii=False) + "\n")
                        outf.flush()
                        print(f"  ✓ {eid} [{formula.get('formula_type')}] {formula.get('formula_name', '')[:50]}")
                    else:
                        print(f"  ✗ {eid} — has_formula=false")

                    processed_ids.add(eid)
                    # Save progress periodically
                    if len(processed_ids) % 10 == 0:
                        STEP3_PROGRESS.write_text(
                            json.dumps({"processed_ids": list(processed_ids)})
                        )

            tasks = [process_one(e) for e in entries_to_process]
            await asyncio.gather(*tasks)

    except ImportError:
        # Sync fallback
        print("  [aiohttp not available, using sync mode]")
        for entry in entries_to_process:
            eid = entry["id"]
            formula = call_opus_sync(endpoint, api_key, entry)
            if formula and formula.get("has_formula"):
                count_formulas.append(1)
                entry_out = {k: v for k, v in entry.items()}
                entry_out["formula"] = formula
                outf.write(json.dumps(entry_out, ensure_ascii=False) + "\n")
                outf.flush()
                print(f"  ✓ {eid} [{formula.get('formula_type')}] {formula.get('formula_name', '')[:50]}")
            processed_ids.add(eid)
            time.sleep(0.2)  # rate limit


def run_step3(limit: int = 0, dry_run: bool = False) -> int:
    """Step 3: Opus extraction. Returns count of extracted formulas."""
    if not CLASSIFIED_FILE.exists():
        print("ERROR: mvp_classified.jsonl not found. Run Step 2 first.")
        sys.exit(1)

    endpoint = os.environ.get("L0_API_ENDPOINT", "").rstrip("/")
    api_key = os.environ.get("L0_API_KEY", "")

    if not endpoint or not api_key:
        print("ERROR: L0_API_ENDPOINT and L0_API_KEY environment variables required.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("STEP 3: Opus formula extraction (Lingya API, 3 concurrent)")
    print("=" * 60)

    # Load resume state
    processed_ids: set[str] = set()
    if STEP3_PROGRESS.exists():
        try:
            prog = json.loads(STEP3_PROGRESS.read_text())
            processed_ids = set(prog.get("processed_ids", []))
            print(f"  Resuming: {len(processed_ids)} already processed")
        except Exception:
            pass

    # Load classified entries with has_computable_relation=true
    to_process = []
    with open(CLASSIFIED_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("has_computable_relation") and e["id"] not in processed_ids:
                to_process.append(e)

    print(f"  Found {len(to_process):,} entries to extract")

    if limit:
        to_process = to_process[:limit]
        print(f"  Limited to {limit} entries")

    if dry_run:
        print(f"[dry-run] Would call Opus on {len(to_process)} entries")
        for e in to_process[:5]:
            print(f"  - {e['id']}: {e.get('scientific_statement', '')[:80]}")
        return 0

    if not to_process:
        # Count existing formulas
        count = sum(1 for _ in open(FORMULAS_FILE, encoding="utf-8")) if FORMULAS_FILE.exists() else 0
        print(f"  Nothing new to process. Existing formulas: {count}")
        return count

    count_formulas: list = []

    with open(FORMULAS_FILE, "a", encoding="utf-8") as outf:
        asyncio.run(run_step3_async(to_process, endpoint, api_key, outf, processed_ids, count_formulas))

    STEP3_PROGRESS.write_text(json.dumps({"processed_ids": list(processed_ids)}))

    # Count total
    total_formulas = 0
    if FORMULAS_FILE.exists():
        with open(FORMULAS_FILE, encoding="utf-8") as f:
            total_formulas = sum(1 for line in f if line.strip())

    print(f"\nExtraction complete:")
    print(f"  New formulas extracted this run: {len(count_formulas)}")
    print(f"  Total formulas in file: {total_formulas}")
    print(f"  Saved → {FORMULAS_FILE}")

    return total_formulas


# ══════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="L0 公式提取 MVP Pipeline (Steps 1-3)"
    )
    parser.add_argument(
        "--step",
        choices=["1", "2", "3", "all"],
        default="all",
        help="Which step to run (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max entries to process (0 = unlimited)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without calling APIs",
    )
    args = parser.parse_args()

    step = args.step
    limit = args.limit
    dry_run = args.dry_run

    if dry_run:
        print("[DRY RUN MODE — no APIs will be called, no files written]\n")

    if step in ("1", "all"):
        n = run_step1(limit=limit, dry_run=dry_run)
        if n == 0 and not dry_run:
            print("WARNING: No candidates found. Check domain filters and file paths.")

    if step in ("2", "all"):
        run_step2(limit=limit, dry_run=dry_run)

    if step in ("3", "all"):
        run_step3(limit=limit, dry_run=dry_run)

    print("\nDone.")


if __name__ == "__main__":
    main()
