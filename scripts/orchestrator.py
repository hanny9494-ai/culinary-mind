#!/usr/bin/env python3
"""
scripts/orchestrator.py
Deterministic pipeline scheduler — replaces LLM-driven dispatch.

Reads books.yaml as single source of truth, drives each book through the
Skill lifecycle state machine, runs quality gates at each stage, and
writes the outcome back to books.yaml.

Usage:
    python orchestrator.py --track A --dry-run            # preview plan
    python orchestrator.py --track A                       # full auto
    python orchestrator.py --track A --book-id mc_vol1     # single book
    python orchestrator.py --track B --concurrency 3       # parallel
    python orchestrator.py --track A --skip-gates          # skip G2/G3

Responsibilities:
  - Decide which books need the target skill run
  - Check OCR/Signal prerequisites (but not run them — that's ocr-claw / signal_router)
  - Run G2 signal_qc / G3 pilot / G4 final_qc via pipeline.skills.gates
  - Invoke run_skill.py via subprocess (capture returncode)
  - Update books.yaml skill_X_status
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
# Run child processes with the same interpreter that launched us — avoids
# drift between orchestrator's env and run_skill.py's. The launcher chooses
# the interpreter (miniforge3 is still the right pick for this repo because
# homebrew python 3.14 has the SSL bug).
PYTHON_BIN = sys.executable
BOOKS_YAML = REPO_ROOT / "config" / "books.yaml"
OUTPUT_ROOT = REPO_ROOT / "output"
RUN_SKILL_PY = REPO_ROOT / "pipeline" / "skills" / "run_skill.py"
TOC_ROUTER_PY = REPO_ROOT / "pipeline" / "skills" / "toc_router.py"

# Make pipeline.skills importable so we can call gates/lifecycle in-process.
sys.path.insert(0, str(REPO_ROOT / "pipeline" / "skills"))
import gates as _gates                  # noqa: E402
import lifecycle as _lifecycle          # noqa: E402

# Proxy bypass (run_skill does this too; safety for our direct gate calls)
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(_k, None)
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")


# ── Structured logging ────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [orch] %(message)s",
)
log = logging.getLogger("orchestrator")


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _load_books_yaml() -> list[dict]:
    with open(BOOKS_YAML) as f:
        data = yaml.safe_load(f) or []
    if not isinstance(data, list):
        raise RuntimeError(f"{BOOKS_YAML}: expected top-level list")
    return data


def _dump_books_yaml(books: list[dict]) -> None:
    """Atomic rewrite of books.yaml preserving key order best-effort."""
    tmp = BOOKS_YAML.with_suffix(".yaml.tmp")
    with open(tmp, "w") as f:
        yaml.safe_dump(
            books,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    tmp.replace(BOOKS_YAML)


def _update_book_status(book_id: str, field: str, value: str) -> None:
    """Rewrite books.yaml with book_id[field] = value. Thread-safe via lock."""
    with _yaml_lock:
        books = _load_books_yaml()
        for b in books:
            if b.get("id") == book_id:
                b[field] = value
                break
        _dump_books_yaml(books)


import threading
_yaml_lock = threading.Lock()
_log_lock = threading.Lock()


def _write_orchestrator_log(book_id: str, entry: dict) -> None:
    """Append one entry to orchestrator_log.jsonl (line-delimited JSON).

    JSONL is chosen over a re-serialised JSON array because it is
    append-only and safe under concurrent workers — each write is one
    atomic write() syscall; no read-modify-write race. The per-process
    _log_lock is kept as an extra safety belt for shared file handles.
    """
    out_dir = OUTPUT_ROOT / book_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "orchestrator_log.jsonl"
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _log_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)


# ── Per-book driver ───────────────────────────────────────────────────────────

class Outcome:
    SKIPPED = "skipped"
    DONE = "done"
    FAILED = "failed"
    GATE_BLOCKED = "gate_blocked"
    NEEDS_REVIEW = "needs_review"


def _plan_for_book(book: dict, skill: str, skip_gates: bool) -> dict:
    """
    Pure function: what would we do for this book?
    Returns {'action': one of ['skip','run'], 'reason': str, 'steps': [...]}.
    """
    book_id = book.get("id", "?")
    skills = [s.upper() for s in (book.get("skills") or [])]
    target = skill.upper()

    if target not in skills:
        return {"action": "skip", "reason": f"skills field does not include {target}"}

    cur_status = book.get(f"skill_{skill.lower()}_status", "pending")
    if cur_status in ("done", "skip"):
        return {"action": "skip", "reason": f"skill_{skill}_status={cur_status}"}

    ocr_status = book.get("ocr_status", "pending")
    if ocr_status != "done":
        return {"action": "skip", "reason": f"needs OCR (ocr_status={ocr_status})"}

    signal_status = book.get("signal_status", "pending")
    needs_toc_routing = signal_status != "done"

    phase = _lifecycle.compute_lifecycle(_lifecycle.enrich_book_with_gates(book))
    if phase == "qc_passed":
        return {"action": "skip", "reason": "lifecycle=qc_passed"}

    steps: list[str] = []
    if needs_toc_routing:
        # Orchestrator drives signal routing itself via toc_router.py.
        steps.append("toc_routing")
    if not skip_gates:
        steps += ["G2_signal_qc", "G3_pilot"]
    steps += ["run_skill", "G4_final_qc", "update_books_yaml"]
    reason = f"phase={phase}, status={cur_status}"
    if needs_toc_routing:
        reason += f", signal_status={signal_status} → toc_routing"
    return {
        "action": "run",
        "reason": reason,
        "steps": steps,
    }


def _run_subprocess_skill(book_id: str, skill: str, pages: int | None,
                          log_handle) -> tuple[int, float]:
    """Invoke run_skill.py. Returns (returncode, duration_seconds)."""
    cmd = [
        PYTHON_BIN, str(RUN_SKILL_PY),
        "--skill", skill,
        "--book-id", book_id,
        "--resume",
    ]
    if pages:
        cmd += ["--pages", str(pages)]
    t0 = time.time()
    log_handle.info(f"[{book_id}] subprocess: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    dur = time.time() - t0
    if result.returncode != 0:
        log_handle.error(f"[{book_id}] run_skill exited {result.returncode}")
        log_handle.error(f"[{book_id}] stderr tail: {result.stderr[-500:]}")
    return result.returncode, dur


def _run_subprocess_toc_router(book_id: str, log_handle) -> tuple[int, float, str]:
    """Invoke toc_router.py --book-id. Returns (returncode, duration_seconds, stderr_tail)."""
    cmd = [PYTHON_BIN, str(TOC_ROUTER_PY), "--book-id", book_id]
    t0 = time.time()
    log_handle.info(f"[{book_id}] subprocess: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    dur = time.time() - t0
    stderr_tail = (result.stderr or "")[-500:]
    if result.returncode != 0:
        log_handle.error(f"[{book_id}] toc_router exited {result.returncode}")
        log_handle.error(f"[{book_id}] stderr tail: {stderr_tail}")
    return result.returncode, dur, stderr_tail


def _process_book(book: dict, skill: str, *,
                  skip_gates: bool,
                  pages: int | None,
                  pilot_sample: int,
                  dry_run: bool) -> dict:
    """
    Drive a single book through the pipeline. Returns a result dict.
    Never raises — failures are captured in the result.
    """
    book_id = book["id"]
    started = time.time()
    entry: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "book_id": book_id,
        "skill": skill,
        "dry_run": dry_run,
        "steps": [],
    }

    plan = _plan_for_book(book, skill, skip_gates)
    entry["plan"] = plan

    if plan["action"] == "skip":
        entry["outcome"] = Outcome.SKIPPED
        entry["duration_s"] = round(time.time() - started, 2)
        if not dry_run:
            _write_orchestrator_log(book_id, entry)
        log.info(f"[{book_id}] SKIP — {plan['reason']}")
        return entry

    log.info(f"[{book_id}] RUN skill={skill} — {plan['reason']}")

    if dry_run:
        entry["outcome"] = "dry_run_would_execute"
        entry["duration_s"] = round(time.time() - started, 2)
        return entry

    try:
        # ── TOC routing (runs when signal_status != done) ──
        if "toc_routing" in plan.get("steps", []):
            rc, dur, stderr_tail = _run_subprocess_toc_router(book_id, log)
            entry["steps"].append({
                "step": "toc_routing",
                "returncode": rc,
                "duration_s": round(dur, 1),
            })
            if rc != 0:
                _update_book_status(book_id, "signal_status", "failed")
                entry["outcome"] = Outcome.FAILED
                entry["error"] = f"toc_router failed: {stderr_tail}"
                entry["duration_s"] = round(time.time() - started, 2)
                _write_orchestrator_log(book_id, entry)
                log.error(f"[{book_id}] toc_router failed — signal_status=failed; continuing to next book")
                return entry
            _update_book_status(book_id, "signal_status", "done")
            log.info(f"[{book_id}] toc_router done → signal_status=done")

        # ── G2 signal_qc ──
        if not skip_gates:
            g2 = _gates.gate_signal_qc(book_id)
            _gates._save_gate(book_id, "signal_qc", g2)
            entry["steps"].append({"step": "G2_signal_qc", "passed": g2.get("passed"),
                                   "anomalies": g2.get("anomalies", [])})
            if g2.get("passed") is False:
                entry["outcome"] = Outcome.GATE_BLOCKED
                entry["blocked_at"] = "G2"
                entry["duration_s"] = round(time.time() - started, 2)
                _write_orchestrator_log(book_id, entry)
                log.warning(f"[{book_id}] G2 blocked: {g2.get('anomalies')}")
                return entry

            # ── G3 pilot ──
            g3 = _gates.gate_pilot(book_id, skill, sample_size=pilot_sample)
            _gates._save_gate(book_id, f"pilot_{skill.lower()}", g3)
            entry["steps"].append({"step": "G3_pilot",
                                   "yield_pct": g3.get("yield_pct"),
                                   "passed": g3.get("passed"),
                                   "recommendation": g3.get("recommendation")})
            passed = g3.get("passed")
            if passed is False:
                # auto-skip → mark book skill as skip and stop
                _update_book_status(book_id, f"skill_{skill.lower()}_status", "skip")
                entry["outcome"] = Outcome.GATE_BLOCKED
                entry["blocked_at"] = "G3"
                entry["final_status"] = "skip"
                entry["duration_s"] = round(time.time() - started, 2)
                _write_orchestrator_log(book_id, entry)
                log.info(f"[{book_id}] G3 pilot recommends skip — books.yaml updated")
                return entry
            if passed is None:
                # needs human review — leave status untouched
                entry["outcome"] = Outcome.NEEDS_REVIEW
                entry["blocked_at"] = "G3"
                entry["duration_s"] = round(time.time() - started, 2)
                _write_orchestrator_log(book_id, entry)
                log.info(f"[{book_id}] G3 pilot needs human review")
                return entry

        # ── Full extraction ──
        _update_book_status(book_id, f"skill_{skill.lower()}_status", "running")
        rc, dur = _run_subprocess_skill(book_id, skill, pages, log)
        entry["steps"].append({"step": "run_skill", "returncode": rc, "duration_s": round(dur, 1)})
        if rc != 0:
            _update_book_status(book_id, f"skill_{skill.lower()}_status", "failed")
            entry["outcome"] = Outcome.FAILED
            entry["duration_s"] = round(time.time() - started, 2)
            _write_orchestrator_log(book_id, entry)
            return entry

        # ── G4 final_qc ──
        g4 = _gates.gate_final_qc(book_id, skill)
        _gates._save_gate(book_id, f"final_qc_{skill.lower()}", g4)
        entry["steps"].append({"step": "G4_final_qc", "passed": g4.get("passed"),
                               "stats": g4.get("stats")})

        # ── Update books.yaml ──
        final_field_value = "done" if g4.get("passed") else "partial"
        _update_book_status(book_id, f"skill_{skill.lower()}_status", final_field_value)
        entry["final_status"] = final_field_value
        entry["outcome"] = Outcome.DONE if g4.get("passed") else Outcome.NEEDS_REVIEW
        entry["duration_s"] = round(time.time() - started, 2)
        _write_orchestrator_log(book_id, entry)
        log.info(f"[{book_id}] DONE — skill_{skill.lower()}_status={final_field_value}")
        return entry

    except Exception as e:
        entry["outcome"] = Outcome.FAILED
        entry["error"] = str(e)
        entry["duration_s"] = round(time.time() - started, 2)
        try:
            _write_orchestrator_log(book_id, entry)
        except Exception:
            pass
        log.exception(f"[{book_id}] unhandled error: {e}")
        return entry


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic pipeline scheduler")
    p.add_argument("--track", required=True, choices=["A", "B", "C", "D"],
                   help="Which skill track to drive")
    p.add_argument("--book-id", help="Restrict to one book")
    p.add_argument("--dry-run", action="store_true", help="Print plan without executing")
    p.add_argument("--skip-gates", action="store_true",
                   help="Skip G2/G3 (use only for known-safe resumes)")
    p.add_argument("--concurrency", type=int, default=1,
                   help="Parallel book workers (default 1; API limits apply)")
    p.add_argument("--pages", type=int, default=None,
                   help="Pass through to run_skill.py --pages (max pages per book)")
    p.add_argument("--pilot-sample", type=int, default=5,
                   help="G3 pilot sample size (default 5)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    skill = args.track.lower()

    books = _load_books_yaml()
    if args.book_id:
        books = [b for b in books if b.get("id") == args.book_id]
        if not books:
            log.error(f"book_id '{args.book_id}' not found")
            return 1

    # Decide targets
    targets = []
    for b in books:
        plan = _plan_for_book(b, skill, args.skip_gates)
        targets.append((b, plan))

    runnable = [(b, p) for b, p in targets if p["action"] == "run"]
    skipped  = [(b, p) for b, p in targets if p["action"] == "skip"]

    log.info(f"track={args.track} total={len(targets)} runnable={len(runnable)} skipped={len(skipped)}")
    if args.dry_run:
        print(f"\n── Plan (track={args.track}, dry-run) ──")
        for b, p in targets:
            print(f"  {b.get('id', '?'):<30} {p['action']:<5} — {p['reason']}")
            if p["action"] == "run":
                print(f"    steps: {p.get('steps', [])}")
        return 0

    if not runnable:
        log.info("Nothing to run.")
        return 0

    results = []
    if args.concurrency > 1:
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futs = {
                ex.submit(_process_book, b, skill,
                          skip_gates=args.skip_gates,
                          pages=args.pages,
                          pilot_sample=args.pilot_sample,
                          dry_run=False): b.get("id")
                for b, _ in runnable
            }
            for fut in as_completed(futs):
                results.append(fut.result())
    else:
        for b, _ in runnable:
            results.append(_process_book(
                b, skill,
                skip_gates=args.skip_gates,
                pages=args.pages,
                pilot_sample=args.pilot_sample,
                dry_run=False,
            ))

    # Summary
    from collections import Counter
    outcomes = Counter(r.get("outcome", "?") for r in results)
    print(f"\n── Orchestrator Summary (track={args.track}) ──")
    for k, v in outcomes.most_common():
        print(f"  {k:<20} {v}")
    print(f"  processed:           {len(results)}")

    # Return non-zero if any hard failures
    return 1 if outcomes.get(Outcome.FAILED, 0) > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
