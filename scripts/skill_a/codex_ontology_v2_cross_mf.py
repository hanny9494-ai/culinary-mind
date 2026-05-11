#!/usr/bin/env python3
"""P1-21c-D v2: 跨 MF 重映射. 把 21,298 no_match items 重新送 Codex，问"属于 28 MF 任一字段吗"."""
import argparse
import asyncio
import json
import os
import re
import time
import yaml
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/jeff/culinary-mind")
MAP_FILE = ROOT / "output/skill_a/param_ontology_map.json"
BOUNDS_FILE = ROOT / "config/solver_bounds.yaml"
OUT_DIR = ROOT / "output/skill_a/codex_raw_v2"
PROGRESS = Path("/tmp/codex_ontology_v2_progress.json")

CODEX_CMD = [
    "codex", "exec",
    "--ephemeral",
    "--ignore-user-config",
    "--dangerously-bypass-approvals-and-sandbox",
    "-s", "read-only",
]

def load_28_mf_fields():
    bounds = yaml.safe_load(open(BOUNDS_FILE))
    return {mf_id: {
        "canonical": mf["canonical_name"],
        "fields": list(dict.fromkeys(i["name"] for i in mf.get("inputs", []))),
        "output": mf.get("output", {}).get("symbol", "?"),
    } for mf_id, mf in bounds["solvers"].items()}

def load_no_match_items():
    m = json.load(open(MAP_FILE))
    items = []
    for mf_id, params in m["mappings"].items():
        for pn, meta in params.items():
            if meta["canonical_field"] == "no_match" and meta["confidence"] >= 0.85:
                items.append({
                    "original_mf": mf_id,
                    "parameter_name": pn,
                    "occurrence_count": meta["occurrence_count"],
                    "sample_value": meta.get("sample_value"),
                    "sample_unit": meta.get("sample_unit"),
                    "unit_hint": meta.get("unit_hint"),
                })
    return items

def build_system_prompt(mf_fields):
    lines = ["You are a chemical/food engineering ontology mapper for the 28 MF solver framework.",
             "",
             "TASK: For each parameter name, search ACROSS ALL 28 MF solvers and find the best matching canonical_field.",
             "If the parameter clearly belongs to a DIFFERENT MF than the one originally assigned, return that other MF.",
             "If the parameter doesn't belong to ANY of 28 MF, return no_match (and suggest if it's a NEW MF candidate).",
             "",
             "# All 28 MF Standard Fields:",
             ]
    for mf_id, info in sorted(mf_fields.items()):
        lines.append(f"  {mf_id} ({info['canonical']}): {info['fields']} → {info['output']}")
    lines += [
        "",
        "# Rules:",
        "1. best_mf: must be one of MF-T01..MF-R07..MF-K01..MF-M01..MF-C01..MF-M06 (any of 28), OR 'no_match'",
        "2. canonical_field: must be in best_mf's standard list above, OR 'no_match' (in which case best_mf must also be no_match)",
        "3. confidence ∈ [0,1]: ≥0.85 if clear semantic + unit match",
        "4. original_mf_was_wrong: true if best_mf differs from input's original_mf",
        "5. new_mf_candidate: short description if param is meaningful physical quantity but outside 28 MF (e.g. 'pKa acid-base equilibrium', 'dielectric constant', 'heat transfer coefficient'), else null",
        "6. unit_hint: implied unit string from name or null",
        "",
        "Examples:",
        "  Input: original_mf=MF-R05, name='Activation energy for browning' → best_mf=MF-T03, canonical_field=Ea, original_mf_was_wrong=true",
        "  Input: original_mf=MF-K01, name='Reynolds number for jet' → best_mf=MF-T04, canonical_field=Re, original_mf_was_wrong=true",
        "  Input: original_mf=MF-M03, name='octanol-water partition coefficient logP' → best_mf=no_match, new_mf_candidate='Solubility/Partition coefficient'",
        "  Input: original_mf=MF-K01, name='毒素化合物 X 浓度' → best_mf=no_match, new_mf_candidate=null (true noise)",
        "",
        "Output strict JSON only:",
        '{"mappings":[{"row":1,"best_mf":"MF-T03","canonical_field":"Ea","confidence":0.93,"original_mf_was_wrong":true,"new_mf_candidate":null,"unit_hint":"kJ/mol","reason":"..."}, ...]}',
    ]
    return "\n".join(lines)

def build_user_prompt(batch):
    lines = [f"Map these {len(batch)} parameter names. Search ACROSS ALL 28 MF. Return JSON with exactly {len(batch)} mappings."]
    lines.append("")
    for i, p in enumerate(batch, 1):
        val = p.get("sample_value")
        unit = p.get("sample_unit") or ""
        sample_str = f" (sample: {val} {unit})" if val is not None else ""
        lines.append(f"{i}. original_mf={p['original_mf']} | name='{p['parameter_name']}'{sample_str}")
    return "\n".join(lines)

async def run_codex(system_prompt, user_prompt, timeout=300):
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
        return {"error": "timeout", "stdout": "", "stderr": "", "returncode": -1}
    return {"stdout": stdout.decode("utf-8","replace"), "stderr": stderr.decode("utf-8","replace"), "returncode": proc.returncode}

def parse_codex_output(stdout):
    if not stdout: return None
    idx = stdout.find("\ncodex\n")
    start = stdout.find("{", idx) if idx >= 0 else stdout.find("{")
    if start < 0: return None
    dec = json.JSONDecoder()
    try:
        obj, _ = dec.raw_decode(stdout[start:])
        if isinstance(obj, dict) and "mappings" in obj: return obj
    except json.JSONDecodeError:
        pass
    # balanced brace fallback
    depth = 0; in_str = False; esc = False
    for i, ch in enumerate(stdout[start:], start):
        if esc: esc = False; continue
        if ch == "\\": esc = True; continue
        if ch == '"' and not esc: in_str = not in_str; continue
        if in_str: continue
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try: return json.loads(stdout[start:i+1])
                except: return None
    return None

async def run_batch(batch_id, system_prompt, batch_items, semaphore, progress):
    out_file = OUT_DIR / f"{batch_id}.json"
    if out_file.exists():
        progress["completed"].add(batch_id)
        return {"batch_id": batch_id, "status": "skip_existing"}
    async with semaphore:
        usr = build_user_prompt(batch_items)
        t0 = time.time()
        r = await run_codex(system_prompt, usr)
        elapsed = time.time() - t0
        stdout = r.get("stdout",""); stderr = r.get("stderr",""); rc = r.get("returncode")
        if rc != 0:
            head = stderr[:1000].lower()
            if any(k in head for k in ("rate limit","rate_limit","rate-limit","429","too many requests","quota")):
                return {"batch_id": batch_id, "status":"rate_limited", "elapsed": elapsed, "stderr_tail": stderr[:1000]}
        parsed = parse_codex_output(stdout)
        if not parsed or "mappings" not in parsed:
            err = OUT_DIR / f"{batch_id}.error.json"
            err.write_text(json.dumps({
                "batch_id": batch_id, "elapsed": elapsed,
                "stdout_tail": stdout[-2000:], "stderr_tail": stderr[:1000],
                "input_items": batch_items,
            }, ensure_ascii=False, indent=2))
            return {"batch_id": batch_id, "status":"parse_failed", "elapsed": elapsed}
        payload = {
            "batch_id": batch_id,
            "elapsed_sec": round(elapsed, 2),
            "input_items": batch_items,
            "raw_output": parsed,
            "n_input": len(batch_items),
            "n_output": len(parsed.get("mappings", [])),
        }
        tmp = out_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        tmp.rename(out_file)
        progress["completed"].add(batch_id)
        save_progress(progress)
        return {"batch_id": batch_id, "status":"ok", "elapsed": elapsed, "n_output": payload["n_output"]}

def load_progress():
    if PROGRESS.exists():
        d = json.loads(PROGRESS.read_text())
        d["completed"] = set(d.get("completed", []))
        return d
    return {"completed": set(), "started_at": time.time()}

def save_progress(p):
    out = {"completed": sorted(p["completed"]), "started_at": p.get("started_at"), "updated_at": time.time()}
    tmp = PROGRESS.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    tmp.rename(PROGRESS)

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--canary", action="store_true")
    ap.add_argument("--batch-size", type=int, default=30)
    ap.add_argument("--parallel", type=int, default=10)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mf_fields = load_28_mf_fields()
    items = load_no_match_items()
    progress = load_progress()
    system_prompt = build_system_prompt(mf_fields)

    print(f"System prompt size: {len(system_prompt)} chars (~{len(system_prompt)//4} tokens)")
    print(f"Total no_match items: {len(items):,}")
    
    # Sort by occurrence_count desc to prioritize high-value items
    items.sort(key=lambda x: -x["occurrence_count"])

    # Build batches
    batches = []
    for i in range(0, len(items), args.batch_size):
        chunk = items[i:i+args.batch_size]
        batches.append((f"v2_b{i//args.batch_size:04d}", chunk))
    if args.canary:
        batches = batches[:1]

    pending = [b for b in batches if b[0] not in progress["completed"]]
    print(f"Total batches: {len(batches)} | already done: {len(batches)-len(pending)} | pending: {len(pending)}")
    print(f"Estimated wall: {len(pending) * 60 / args.parallel / 60:.1f} min")
    print()

    sem = asyncio.Semaphore(args.parallel)
    t0 = time.time()
    tasks = [run_batch(bid, system_prompt, b, sem, progress) for bid, b in pending]
    done = 0
    for coro in asyncio.as_completed(tasks):
        r = await coro
        done += 1
        elapsed = time.time() - t0
        print(f"[{done}/{len(pending)}] {r['batch_id']} → {r['status']} ({r.get('elapsed',0):.1f}s) | total {elapsed/60:.1f}min")
        if r["status"] == "rate_limited":
            print("⛔ RATE LIMIT — exit 2"); save_progress(progress); return 2
    save_progress(progress)
    print(f"\n✅ Done. completed: {len(progress['completed'])} batches")
    return 0

if __name__ == "__main__":
    rc = asyncio.run(main())
    raise SystemExit(rc or 0)
