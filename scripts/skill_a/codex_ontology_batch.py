#!/usr/bin/env python3
"""P1-21c-D Step 2: Codex CLI batch ontology mapper.

Reads unique_pairs.jsonl, groups by formula_id, calls Codex CLI in parallel batches.
Output: output/skill_a/codex_raw/{batch_id}.json
Progress: /tmp/codex_ontology_progress.json
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import yaml
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/jeff/culinary-mind")
PAIRS_FILE = ROOT / "output/skill_a/unique_pairs.jsonl"
BOUNDS_FILE = ROOT / "config/solver_bounds.yaml"
OUT_DIR = ROOT / "output/skill_a/codex_raw"
PROGRESS = Path("/tmp/codex_ontology_progress.json")

CODEX_CMD = [
    "codex", "exec",
    "--ephemeral",
    "--ignore-user-config",
    "--dangerously-bypass-approvals-and-sandbox",
    "-s", "read-only",
]

# ---------- Load standard fields ----------
def load_mf_fields():
    bounds = yaml.safe_load(open(BOUNDS_FILE))
    fields_by_mf = {}
    for mf_id, mf in bounds["solvers"].items():
        canonical = mf.get("canonical_name", "?")
        inputs = list(dict.fromkeys(i["name"] for i in mf.get("inputs", [])))  # dedupe preserving order
        output_sym = mf.get("output", {}).get("symbol", "?")
        fields_by_mf[mf_id] = {
            "canonical_name": canonical,
            "input_fields": inputs,
            "output_symbol": output_sym,
        }
    return fields_by_mf

# ---------- Group pairs by formula_id ----------
def load_pairs():
    by_mf = defaultdict(list)
    with open(PAIRS_FILE, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by_mf[r["formula_id"]].append(r)
    return by_mf

# ---------- Prompt builder ----------
def build_system_prompt(mf_id, mf_meta):
    fields = mf_meta["input_fields"]
    return f"""You are a chemical/food engineering ontology mapper.

Target solver: {mf_id} ({mf_meta["canonical_name"]})
Standard input fields (canonical_field MUST be one of these, OR exactly "no_match"):
{json.dumps(fields, ensure_ascii=False)}
Output symbol: {mf_meta["output_symbol"]}

For each LLM-written parameter_name, output ONE mapping object:
- canonical_field: must be in the list above OR "no_match"
- confidence: float [0,1]. ≥0.85 if clear semantic match. <0.85 if ambiguous/speculative.
- alternatives: list of other plausible standard fields (or [])
- reason: ONE short sentence
- unit_hint: implied unit string from the name (e.g. "K", "°C", "Pa·s") or null

Rules:
- If parameter name is clearly outside this MF's physical scope, canonical_field="no_match"
- Use semantic matching: "稠度系数 K" → K; "thermal conductivity" → k; "activation energy" → Ea
- Strict JSON only. No prose, no markdown.

Output format (exactly):
{{"mappings":[{{"row":1,"canonical_field":"...","confidence":0.92,"alternatives":[],"reason":"...","unit_hint":null}}, ...]}}"""

def build_user_prompt(batch):
    lines = [f"Map these {len(batch)} parameter names. Return JSON with exactly {len(batch)} mappings."]
    lines.append("")
    for i, p in enumerate(batch, 1):
        val = p.get("sample_value")
        unit = p.get("sample_unit") or ""
        sample_str = f' (sample: {val} {unit})' if val is not None else ""
        lines.append(f"{i}. {p['parameter_name']}{sample_str}")
    return "\n".join(lines)

# ---------- Codex call ----------
JSON_RE = re.compile(r'\{[\s\S]*"mappings"[\s\S]*\}')

async def run_codex(system_prompt, user_prompt, timeout=300):
    """Run codex exec with system+user prompts via stdin."""
    # codex exec accepts prompt as last arg or stdin. We'll use --system + positional user.
    combined = f"<system>\n{system_prompt}\n</system>\n\n<user>\n{user_prompt}\n</user>"
    cmd = CODEX_CMD + ["-m", "gpt-5.4", "-c", "model_reasoning_effort=low", combined]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "NO_PROXY": "*"},
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"error": "timeout", "stdout": "", "stderr": ""}
    return {
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "returncode": proc.returncode,
    }

def parse_codex_output(stdout):
    """Extract the JSON {mappings:[...]} from codex stdout. Robust to LLM trailing garbage."""
    if not stdout:
        return None
    # Strategy 1: locate first '{' after "codex" marker (Codex CLI prints "codex\n" before LLM output)
    idx = stdout.find('\ncodex\n')
    if idx >= 0:
        start = stdout.find('{', idx)
    else:
        start = stdout.find('{')
    if start < 0:
        return None
    # Strategy 2: raw_decode from start to find first valid JSON object
    dec = json.JSONDecoder()
    try:
        obj, _end = dec.raw_decode(stdout[start:])
        if isinstance(obj, dict) and "mappings" in obj:
            return obj
    except json.JSONDecodeError:
        pass
    # Strategy 3: find balanced braces ignoring strings
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(stdout[start:], start):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"' and not esc:
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stdout[start:i+1])
                except Exception:
                    return None
    return None

# ---------- Batch runner ----------
async def run_batch(batch_id, mf_id, mf_meta, batch_pairs, semaphore, progress):
    out_file = OUT_DIR / f"{batch_id}.json"
    if out_file.exists():
        progress["completed"].add(batch_id)
        return {"batch_id": batch_id, "status": "skip_existing"}

    async with semaphore:
        sys_p = build_system_prompt(mf_id, mf_meta)
        usr_p = build_user_prompt(batch_pairs)
        t0 = time.time()
        result = await run_codex(sys_p, usr_p)
        elapsed = time.time() - t0

        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")

        # Detect rate limit — only when codex itself errors (not LLM content containing the words)
        rc = result.get("returncode")
        if rc != 0:
            stderr_head = stderr[:1000].lower()
            if ("rate limit" in stderr_head or "rate_limit" in stderr_head or
                "rate-limit" in stderr_head or "429" in stderr_head or
                "too many requests" in stderr_head or "quota" in stderr_head):
                return {"batch_id": batch_id, "status": "rate_limited", "elapsed": elapsed, "stderr_tail": stderr[:1000]}

        parsed = parse_codex_output(stdout)
        if not parsed or "mappings" not in parsed:
            err_payload = {"batch_id": batch_id, "mf_id": mf_id, "elapsed": elapsed, "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-500:], "input_pairs": batch_pairs}
            err_file = OUT_DIR / f"{batch_id}.error.json"
            err_file.write_text(json.dumps(err_payload, ensure_ascii=False, indent=2))
            return {"batch_id": batch_id, "status": "parse_failed", "elapsed": elapsed}

        # Sanity: count match
        n_input = len(batch_pairs)
        n_output = len(parsed.get("mappings", []))
        if n_output != n_input:
            print(f"⚠️ {batch_id}: input {n_input} vs output {n_output} mismatch", file=sys.stderr)

        payload = {
            "batch_id": batch_id,
            "mf_id": mf_id,
            "elapsed_sec": round(elapsed, 2),
            "input_pairs": batch_pairs,
            "raw_output": parsed,
            "n_input": n_input,
            "n_output": n_output,
        }
        # atomic write
        tmp = out_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        tmp.rename(out_file)
        progress["completed"].add(batch_id)
        save_progress(progress)
        return {"batch_id": batch_id, "status": "ok", "elapsed": elapsed, "n_output": n_output}

# ---------- Progress checkpoint ----------
def load_progress():
    if PROGRESS.exists():
        d = json.loads(PROGRESS.read_text())
        d["completed"] = set(d.get("completed", []))
        d["failed"] = set(d.get("failed", []))
        return d
    return {"completed": set(), "failed": set(), "started_at": time.time()}

def save_progress(p):
    out = {
        "completed": sorted(p["completed"]),
        "failed": sorted(p["failed"]),
        "started_at": p.get("started_at", time.time()),
        "updated_at": time.time(),
    }
    tmp = PROGRESS.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    tmp.rename(PROGRESS)

# ---------- Main ----------
async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--canary", action="store_true", help="Run only 1 batch from MF-K01 for testing")
    ap.add_argument("--mf", type=str, default=None, help="Only this MF (e.g. MF-K01)")
    ap.add_argument("--batch-size", type=int, default=30)
    ap.add_argument("--parallel", type=int, default=10)
    ap.add_argument("--limit-batches", type=int, default=None)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mf_fields = load_mf_fields()
    pairs_by_mf = load_pairs()
    progress = load_progress()

    # Build all batches
    all_batches = []
    for mf_id in sorted(pairs_by_mf):
        if args.mf and mf_id != args.mf:
            continue
        pairs = pairs_by_mf[mf_id]
        for i in range(0, len(pairs), args.batch_size):
            chunk = pairs[i:i+args.batch_size]
            batch_id = f"{mf_id}_b{i//args.batch_size:04d}"
            all_batches.append((batch_id, mf_id, mf_fields[mf_id], chunk))

    if args.canary:
        all_batches = all_batches[:1]
    elif args.limit_batches:
        all_batches = all_batches[:args.limit_batches]

    pending = [b for b in all_batches if b[0] not in progress["completed"]]
    print(f"Total batches: {len(all_batches)} | already done: {len(all_batches) - len(pending)} | pending: {len(pending)}")
    print(f"Estimated wall time @ {args.parallel} parallel × 60s/batch: {len(pending) * 60 / args.parallel / 60:.1f} min")
    print()

    sem = asyncio.Semaphore(args.parallel)
    t0 = time.time()
    tasks = [run_batch(*b, sem, progress) for b in pending]
    rate_limit_hit = False
    done_count = 0
    for coro in asyncio.as_completed(tasks):
        r = await coro
        done_count += 1
        elapsed_total = time.time() - t0
        status = r.get("status", "?")
        bid = r.get("batch_id", "?")
        print(f"[{done_count}/{len(pending)}] {bid} → {status} ({r.get('elapsed', 0):.1f}s) | total {elapsed_total/60:.1f}min")
        if status == "rate_limited":
            rate_limit_hit = True
            print(f"⛔ RATE LIMIT HIT on {bid}. stderr: {r.get('stderr_tail','')[:300]}", file=sys.stderr)
            break

    save_progress(progress)
    if rate_limit_hit:
        sys.exit(2)
    print(f"\n✅ All done. completed: {len(progress['completed'])} batches")

if __name__ == "__main__":
    asyncio.run(main())
