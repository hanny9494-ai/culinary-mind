#!/usr/bin/env python3
"""
pipeline/skills/lifecycle.py
Lifecycle state machine — pure functions for computing book status.

compute_lifecycle(book) → str   total lifecycle phase
compute_next_action(book) → str | None   what to do next

These functions are read-only: they never write to books.yaml.
Gate results live in output/{book_id}/gates/*.json.

Usage:
    python lifecycle.py --books-yaml config/books.yaml
    python lifecycle.py --books-yaml config/books.yaml --book-id mc_vol1
    python lifecycle.py --books-yaml config/books.yaml --json
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "output"

# ── Lifecycle phases (ordered) ────────────────────────────────────────────────
LIFECYCLE_PHASES = [
    "registered",      # just added to books.yaml, no OCR yet
    "ocr_running",     # OCR in progress
    "ocr_ready",       # OCR done, awaiting Signal QC
    "signaled",        # signals.json done, awaiting Pilot
    "piloted",         # all skill pilots passed / skipped
    "extracting",      # full extraction in progress
    "extracted",       # all skills done or skipped
    "qc_passed",       # Final QC passed — ready for graph ingest
    # Error states
    "ocr_failed",
    "extraction_failed",
    "signal_failed",
]

# Status values that mean "finished successfully"
_DONE = {"done", "skip"}
_ACTIVE = {"running", "piloting"}
_FAILED = {"failed", "error"}


# ── Pure state-machine functions ──────────────────────────────────────────────

def compute_lifecycle(book: dict) -> str:
    """
    Pure function: derive total lifecycle state from a book's status fields.

    Reads: ocr_status, signal_status, skill_{a,b,c,d}_status, gates, skills.
    Does NOT write anything.

    Returns one of the LIFECYCLE_PHASES strings.
    """
    ocr_status = book.get("ocr_status", "pending")
    signal_status = book.get("signal_status", "pending")
    skills = [s.upper() for s in book.get("skills", [])]
    gates = book.get("gates") or {}

    # OCR phase
    if ocr_status in _FAILED:
        return "ocr_failed"
    if ocr_status in ("pending", "needs_reocr"):
        return "registered"
    if ocr_status in _ACTIVE:
        return "ocr_running"
    # ocr_status == "done" from here

    # Signal phase
    if signal_status in _FAILED:
        return "signal_failed"
    if signal_status != "done":
        return "ocr_ready"

    # Check skill statuses
    skill_statuses = {}
    for s in skills:
        key = f"skill_{s.lower()}_status"
        skill_statuses[s] = book.get(key, "pending")

    any_failed = any(v in _FAILED for v in skill_statuses.values())
    if any_failed:
        return "extraction_failed"

    any_active = any(v in _ACTIVE for v in skill_statuses.values())
    all_done = all(v in _DONE for v in skill_statuses.values())
    any_pending = any(v == "pending" for v in skill_statuses.values())

    if all_done:
        final_qc = gates.get("final_qc") or {}
        if final_qc.get("passed") is True:
            return "qc_passed"
        return "extracted"

    if any_active:
        return "extracting"

    # Some skills pending — check if all pilots passed
    all_pilots_done = True
    for s in skills:
        sk = s.lower()
        status = skill_statuses.get(s, "pending")
        if status == "skip":
            continue
        if status == "pending":
            pilot_result = gates.get(f"pilot_{sk}") or {}
            if pilot_result.get("passed") is None and not pilot_result:
                all_pilots_done = False

    if all_pilots_done and any_pending:
        return "piloted"

    return "signaled"


def compute_next_action(book: dict) -> str | None:
    """
    Pure function: return the single next action for this book, or None.

    Return values:
      "ocr"                    — run OCR (ocr_claw)
      "gate_ocr_qc"           — run G1 OCR quality check
      "signal"                 — run signal router
      "gate_signal_qc"        — run G2 Signal quality check
      "pilot_{a|b|c|d}"       — run Pilot gate for skill X
      "await_pilot_{a|b|c|d}" — pilot running, wait
      "skill_{a|b|c|d}"       — run full skill extraction
      "gate_final_qc"         — run G4 Final QC
      None                     — nothing to do (done or blocked on human)

    Reads: same fields as compute_lifecycle.
    Does NOT write anything.
    """
    ocr_status = book.get("ocr_status", "pending")
    signal_status = book.get("signal_status", "pending")
    skills = [s.upper() for s in book.get("skills", [])]
    gates = book.get("gates") or {}

    # ── OCR ───────────────────────────────────────────────────────────────────
    if ocr_status in ("pending", "needs_reocr"):
        return "ocr"
    if ocr_status in _ACTIVE:
        return None  # wait
    if ocr_status in _FAILED:
        return None  # human intervention needed

    # OCR done — check OCR QC gate
    ocr_qc = gates.get("ocr_qc") or {}
    if not ocr_qc:
        return "gate_ocr_qc"
    if ocr_qc.get("passed") is False:
        return None  # failed gate — human review
    if ocr_qc.get("needs_review"):
        return None  # borderline — human review

    # ── Signal ────────────────────────────────────────────────────────────────
    if signal_status in ("pending",):
        return "signal"
    if signal_status in _ACTIVE:
        return None  # wait
    if signal_status in _FAILED:
        return None

    # Signal done — check Signal QC gate
    signal_qc = gates.get("signal_qc") or {}
    if not signal_qc:
        return "gate_signal_qc"
    if signal_qc.get("passed") is False:
        return None  # anomalies detected — human review

    # ── Skills (pilot → full extraction) ─────────────────────────────────────
    for s in skills:
        sk = s.lower()
        status = book.get(f"skill_{sk}_status", "pending")

        if status == "skip":
            continue
        if status in _DONE:
            continue
        if status in _FAILED:
            return None  # human intervention

        if status == "piloting":
            return f"await_pilot_{sk}"

        if status == "pending":
            pilot_result = gates.get(f"pilot_{sk}") or {}
            if not pilot_result:
                return f"pilot_{sk}"
            # Pilot ran — check result
            passed = pilot_result.get("passed")
            if passed is True:
                return f"skill_{sk}"
            if passed is False:
                # Auto-skip: pilot said no value
                return None  # caller should update skill status to skip
            if passed is None:
                return None  # needs human review

        if status == "running":
            return None  # wait

    # ── All skills done or skipped ────────────────────────────────────────────
    skill_statuses = [book.get(f"skill_{s.lower()}_status", "pending") for s in skills]
    if all(v in _DONE for v in skill_statuses):
        final_qc = gates.get("final_qc") or {}
        if not final_qc:
            return "gate_final_qc"
        if final_qc.get("passed") is True:
            return None  # all done!
        if final_qc.get("passed") is False:
            return None  # human review

    return None


# ── Gate result loader (reads output/{book_id}/gates/*.json) ──────────────────

def load_gate_results(book_id: str) -> dict[str, Any]:
    """Load all gate JSON files from output/{book_id}/gates/ into a dict."""
    gates_dir = OUTPUT_ROOT / book_id / "gates"
    gates: dict[str, Any] = {}
    if not gates_dir.exists():
        return gates
    for f in gates_dir.glob("*.json"):
        key = f.stem  # e.g. "ocr_qc", "pilot_a"
        try:
            gates[key] = json.loads(f.read_text())
        except Exception:
            pass
    return gates


def enrich_book_with_gates(book: dict) -> dict:
    """
    Return a copy of book with gates field populated from disk.
    books.yaml may not have gates (they live in output/), so we merge.
    """
    book_copy = dict(book)
    disk_gates = load_gate_results(book["id"])
    yaml_gates = book.get("gates") or {}
    # Disk gates take precedence (they are more up-to-date)
    merged = {**yaml_gates, **disk_gates}
    book_copy["gates"] = merged
    return book_copy

# ── YAML loader ───────────────────────────────────────────────────────────────

def load_books(books_yaml_path: Path) -> list[dict]:
    """Load books.yaml and return list of book dicts."""
    try:
        import yaml
        with open(books_yaml_path) as f:
            data = yaml.safe_load(f)
        if isinstance(data, list):
            return data
        return data.get("books", [])
    except ImportError:
        # Fallback: minimal YAML parser for simple lists
        import re
        books = []
        current: dict | None = None
        with open(books_yaml_path) as f:
            for line in f:
                if line.startswith("- id:"):
                    if current:
                        books.append(current)
                    current = {"id": line.split(":", 1)[1].strip()}
                elif current and ":" in line and not line.startswith("#"):
                    k, _, v = line.strip().partition(":")
                    current[k.strip()] = v.strip()
        if current:
            books.append(current)
        return books

# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lifecycle state machine — compute book status and next action")
    p.add_argument("--books-yaml", default=str(REPO_ROOT / "config" / "books.yaml"),
                   help="Path to books.yaml")
    p.add_argument("--book-id", help="Show detail for one book")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.add_argument("--action-filter", help="Only show books with this next_action")
    p.add_argument("--lifecycle-filter", help="Only show books with this lifecycle phase")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    books_yaml = Path(args.books_yaml)
    if not books_yaml.exists():
        print(f"ERROR: {books_yaml} not found", file=sys.stderr)
        sys.exit(1)

    books = load_books(books_yaml)
    if not books:
        print("No books found in books.yaml")
        return

    # Enrich with gate results from disk
    books = [enrich_book_with_gates(b) for b in books]

    if args.book_id:
        # Single book detail
        book = next((b for b in books if b.get("id") == args.book_id), None)
        if not book:
            print(f"ERROR: book_id '{args.book_id}' not found", file=sys.stderr)
            sys.exit(1)

        lifecycle = compute_lifecycle(book)
        next_action = compute_next_action(book)

        if args.json:
            print(json.dumps({
                "id": book["id"],
                "lifecycle": lifecycle,
                "next_action": next_action,
                "ocr_status": book.get("ocr_status", "pending"),
                "signal_status": book.get("signal_status", "pending"),
                "skills": book.get("skills", []),
                "skill_statuses": {
                    s: book.get(f"skill_{s.lower()}_status", "pending")
                    for s in book.get("skills", [])
                },
                "gates": book.get("gates", {}),
            }, ensure_ascii=False, indent=2))
        else:
            print(f"\n{'='*60}")
            print(f"  Book: {book['id']}")
            print(f"  Title: {book.get('title', 'N/A')}")
            print(f"{'='*60}")
            print(f"  lifecycle:     {lifecycle}")
            print(f"  next_action:   {next_action}")
            print(f"  ocr_status:    {book.get('ocr_status', 'pending')}")
            print(f"  signal_status: {book.get('signal_status', 'pending')}")
            print(f"  skills:        {book.get('skills', [])}")
            for s in book.get("skills", []):
                sk = s.lower()
                status = book.get(f"skill_{sk}_status", "pending")
                pilot = (book.get("gates") or {}).get(f"pilot_{sk}", {})
                pilot_str = ""
                if pilot:
                    pilot_str = f" | pilot: yield={pilot.get('yield_pct', '?'):.0f}% passed={pilot.get('passed')}"
                print(f"  skill_{sk}:     {status}{pilot_str}")
            gates = book.get("gates", {})
            if gates:
                print(f"\n  Gates:")
                for gk, gv in gates.items():
                    passed = gv.get("passed") if gv else "N/A"
                    print(f"    {gk}: passed={passed}")
        return

    # All books table
    results = []
    for book in books:
        lifecycle = compute_lifecycle(book)
        next_action = compute_next_action(book)
        results.append({
            "id": book.get("id", ""),
            "title_short": book.get("title", "")[:40],
            "lifecycle": lifecycle,
            "next_action": next_action or "—",
            "ocr": book.get("ocr_status", "pending"),
            "signal": book.get("signal_status", "pending"),
            "skills": ",".join(book.get("skills", [])),
        })

    # Apply filters
    if args.action_filter:
        results = [r for r in results if r["next_action"] == args.action_filter]
    if args.lifecycle_filter:
        results = [r for r in results if r["lifecycle"] == args.lifecycle_filter]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    # Pretty table
    print(f"\n{'='*100}")
    print(f"  Book Lifecycle Status  ({len(results)} books)")
    print(f"{'='*100}")
    hdr = f"  {'ID':<30} {'Lifecycle':<18} {'Next Action':<25} {'OCR':<15} {'Signal':<12} {'Skills'}"
    print(hdr)
    print("  " + "-" * 96)
    for r in results:
        print(
            f"  {r['id']:<30} {r['lifecycle']:<18} {r['next_action']:<25} "
            f"{r['ocr']:<15} {r['signal']:<12} {r['skills']}"
        )
    print()

    # Summary counts by next_action
    from collections import Counter
    action_counts = Counter(r["next_action"] for r in results)
    print("  Next Actions Summary:")
    for action, count in sorted(action_counts.items(), key=lambda x: -x[1]):
        print(f"    {action:<30} {count}")
    print()


if __name__ == "__main__":
    main()
