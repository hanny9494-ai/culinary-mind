#!/usr/bin/env python3
"""
scripts/batch_gates.py
Batch gate executor — reads books.yaml, runs specified gate for all matching books.

Usage:
    # Run gate_ocr_qc for all books whose next_action == gate_ocr_qc
    python scripts/batch_gates.py --gate ocr_qc

    # Run gate_signal_qc for all matching books
    python scripts/batch_gates.py --gate signal_qc

    # Run for a single book
    python scripts/batch_gates.py --gate ocr_qc --book-id mc_vol1

    # Dry-run: show which books would be gated, don't run
    python scripts/batch_gates.py --gate ocr_qc --dry-run

    # Pilot gate for all matching books (requires --skill)
    python scripts/batch_gates.py --gate pilot --skill a

    # Final QC gate
    python scripts/batch_gates.py --gate final_qc --skill b
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# ── Proxy bypass ──────────────────────────────────────────────────────────────
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(_k, None)
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "pipeline" / "skills"))

import yaml  # type: ignore

# ── Gate name → next_action mapping ──────────────────────────────────────────
# Which lifecycle next_action triggers each gate
GATE_NEXT_ACTION_MAP: dict[str, list[str]] = {
    "preflight":  ["ocr"],
    "ocr_qc":     ["gate_ocr_qc"],
    "signal_qc":  ["gate_signal_qc"],
    "pilot":      [],  # populated dynamically based on --skill
    "final_qc":   [],  # populated dynamically based on --skill
}


def get_gate_actions(gate: str, skill: str | None) -> list[str]:
    """Return the next_action values that trigger this gate."""
    if gate == "pilot" and skill:
        return [f"pilot_{skill}"]
    if gate == "final_qc" and skill:
        return [f"gate_final_qc_{skill}"]
    return GATE_NEXT_ACTION_MAP.get(gate, [])


def load_books(books_yaml: Path) -> list[dict]:
    with open(books_yaml) as f:
        books = yaml.safe_load(f)
    return books if isinstance(books, list) else []


def run_gate(gate: str, book_id: str, skill: str | None, books_yaml: Path,
             sample_pages: int = 5, sample_final: int = 10,
             save: bool = True) -> dict[str, Any]:
    """Run the specified gate for a book. Returns the result dict."""
    from gates import (
        gate_preflight, gate_ocr_qc, gate_signal_qc,
        gate_pilot, gate_final_qc, _save_gate,
    )

    if gate == "preflight":
        result = gate_preflight(book_id, books_yaml_path=books_yaml)
        gate_name = "preflight"
    elif gate == "ocr_qc":
        result = gate_ocr_qc(book_id)
        gate_name = "ocr_qc"
    elif gate == "signal_qc":
        result = gate_signal_qc(book_id)
        gate_name = "signal_qc"
    elif gate == "pilot":
        if not skill:
            return {"passed": False, "error": "pilot gate requires --skill"}
        result = gate_pilot(book_id, skill, sample_size=sample_pages)
        gate_name = f"pilot_{skill}"
    elif gate == "final_qc":
        if not skill:
            return {"passed": False, "error": "final_qc gate requires --skill"}
        result = gate_final_qc(book_id, skill, sample_size=sample_final)
        gate_name = f"final_qc_{skill}"
    else:
        return {"passed": False, "error": f"unknown gate: {gate}"}

    if save:
        _save_gate(book_id, gate_name, result)

    return result


def _status_icon(result: dict) -> str:
    p = result.get("passed")
    if p is True:
        return "✅"
    if p is None:
        return "⚠️ "
    return "❌"


def _key_metrics(gate: str, result: dict) -> str:
    """Extract key metrics as a short string for the summary table."""
    if "error" in result:
        return f"ERROR: {result['error'][:60]}"
    if gate == "ocr_qc":
        s = result.get("stats", {})
        return f"blank={s.get('blank_pct','?')}% avg_chars={s.get('avg_chars_per_page','?')}"
    if gate == "signal_qc":
        s = result.get("stats", {})
        return (f"A={s.get('a_pct','?')}% B={s.get('b_pct','?')}% "
                f"skip={s.get('skip_pct','?')}%")
    if gate == "pilot":
        return (f"yield={result.get('yield_pct','?')}% "
                f"({result.get('non_empty_pages','?')}/{result.get('sample_size','?')}) "
                f"rec={result.get('recommendation','?')}")
    if gate == "final_qc":
        s = result.get("stats", {})
        return (f"records={s.get('total_records','?')} "
                f"errors={s.get('error_pct','?')}% "
                f"schema_errs={s.get('schema_error_count','?')}")
    if gate == "preflight":
        c = result.get("checks", {})
        return (f"pdf={c.get('source_pdf_exists','?')} "
                f"disk={c.get('free_disk_gb','?')}GB")
    return ""


def main() -> None:
    p = argparse.ArgumentParser(
        description="Batch gate executor — runs quality gates for multiple books",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--gate", required=True,
                   choices=["preflight", "ocr_qc", "signal_qc", "pilot", "final_qc"],
                   help="Which gate to run")
    p.add_argument("--book-id", default=None,
                   help="Run for a single book only")
    p.add_argument("--skill", choices=["a", "b", "c", "d"], default=None,
                   help="Skill (required for pilot and final_qc)")
    p.add_argument("--books-yaml", default=str(REPO_ROOT / "config" / "books.yaml"),
                   help="Path to books.yaml")
    p.add_argument("--dry-run", action="store_true",
                   help="Show which books would be gated, don't run")
    p.add_argument("--pages", type=int, default=5,
                   help="Sample size for pilot gate (default: 5)")
    p.add_argument("--sample", type=int, default=10,
                   help="Sample size for final_qc (default: 10)")
    p.add_argument("--force", action="store_true",
                   help="Run gate even if next_action doesn't match (use with --book-id)")
    p.add_argument("--no-save", action="store_true",
                   help="Don't write gate results to disk")
    args = p.parse_args()

    books_yaml = Path(args.books_yaml)
    if not books_yaml.exists():
        print(f"ERROR: books.yaml not found: {books_yaml}", file=sys.stderr)
        sys.exit(1)

    # ── Import lifecycle functions ──
    from lifecycle import compute_next_action, enrich_book_with_gates

    books = load_books(books_yaml)

    # ── Determine target books ──
    if args.book_id:
        # Single book mode
        book_list = [b for b in books if b.get("id") == args.book_id]
        if not book_list:
            print(f"ERROR: book_id '{args.book_id}' not found in books.yaml", file=sys.stderr)
            sys.exit(1)
        if not args.force:
            # Still filter by next_action unless --force
            target_actions = get_gate_actions(args.gate, args.skill)
            filtered = []
            for b in book_list:
                enriched = enrich_book_with_gates(b)
                na = compute_next_action(enriched)
                if na in target_actions or not target_actions:
                    filtered.append(b)
                else:
                    print(f"⚠  {b['id']}: next_action={na!r} doesn't match gate "
                          f"{args.gate!r} (expected {target_actions}). Use --force to override.")
            book_list = filtered
    else:
        # Batch mode: filter by next_action
        target_actions = get_gate_actions(args.gate, args.skill)
        if not target_actions and args.gate in ("pilot", "final_qc") and not args.skill:
            print(f"ERROR: --skill required for {args.gate} gate in batch mode", file=sys.stderr)
            sys.exit(1)

        book_list = []
        for b in books:
            enriched = enrich_book_with_gates(b)
            na = compute_next_action(enriched)
            if na in target_actions:
                book_list.append(b)

    if not book_list:
        print(f"No books with next_action matching gate '{args.gate}'"
              + (f" (skill {args.skill})" if args.skill else ""))
        sys.exit(0)

    print(f"\n── Batch Gate: {args.gate.upper()}"
          + (f" skill={args.skill}" if args.skill else "")
          + f" — {len(book_list)} books ──")
    if args.dry_run:
        print("(DRY RUN — no gates will be executed)\n")
    print(f"  {'Book ID':<35} {'Status':<6} {'Key Metrics'}")
    print(f"  {'-'*35} {'-'*6} {'-'*50}")

    # ── Run gates ──
    results_map: dict[str, dict] = {}
    passed_count = 0
    failed_count = 0
    review_count = 0
    error_count = 0

    for book in book_list:
        book_id = book["id"]
        if args.dry_run:
            enriched = enrich_book_with_gates(book)
            na = compute_next_action(enriched)
            print(f"  {book_id:<35} {'DRY':<6} next_action={na}")
            continue

        t0 = time.time()
        try:
            result = run_gate(
                gate=args.gate,
                book_id=book_id,
                skill=args.skill,
                books_yaml=books_yaml,
                sample_pages=args.pages,
                sample_final=args.sample,
                save=not args.no_save,
            )
        except Exception as e:
            result = {"passed": False, "error": str(e)}

        elapsed = time.time() - t0
        results_map[book_id] = result

        icon = _status_icon(result)
        metrics = _key_metrics(args.gate, result)
        p_val = result.get("passed")
        if p_val is True:
            passed_count += 1
        elif p_val is None:
            review_count += 1
        elif "error" in result and result.get("passed") is False and "error" in result.get("error",""):
            error_count += 1
        else:
            failed_count += 1

        print(f"  {book_id:<35} {icon:<6} {metrics}  [{elapsed:.1f}s]")

    if args.dry_run:
        print(f"\n  Total: {len(book_list)} books would be gated")
        return

    print(f"\n── Summary ──")
    print(f"  Total:       {len(book_list)}")
    print(f"  ✅ Passed:   {passed_count}")
    print(f"  ⚠️  Review:   {review_count}")
    print(f"  ❌ Failed:   {failed_count}")
    if error_count:
        print(f"  💥 Errors:   {error_count}")

    if not args.no_save:
        # Write batch summary
        from pipeline.skills.gates import _ts  # noqa
        summary_path = REPO_ROOT / "output" / f"_batch_gates_{args.gate}.json"
        summary = {
            "gate": args.gate,
            "skill": args.skill,
            "total": len(book_list),
            "passed": passed_count,
            "needs_review": review_count,
            "failed": failed_count,
            "errors": error_count,
            "results": {bid: {"passed": r.get("passed"), "metrics": _key_metrics(args.gate, r)}
                        for bid, r in results_map.items()},
            "_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"\n  Batch summary → {summary_path}")


if __name__ == "__main__":
    main()
