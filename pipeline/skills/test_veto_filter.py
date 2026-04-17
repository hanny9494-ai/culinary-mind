#!/usr/bin/env python3
"""
pipeline/skills/test_veto_filter.py
Validate Veto filter rules against known Skill A results for belitz and heldman.

For each book:
  - "data pages"  = pages in done_pages whose results.jsonl has ≥1 real record
                    (with mother_formula field → genuine extraction)
  - "empty pages" = pages in done_pages whose results.jsonl has 0 real records
                    (only _filtered or empty result rows)
  - Runs new filter on both sets and reports:
      * New veto filtering: how many empty pages would now be filtered
      * False negatives: how many data pages would be vetoed (must be 0)

Usage:
    python test_veto_filter.py
    python test_veto_filter.py --verbose          # show every FN page
    python test_veto_filter.py --book-id belitz_food_chemistry
"""

import argparse
import json
import sys
from pathlib import Path

# Add skills dir to path for relative import
sys.path.insert(0, str(Path(__file__).parent))
from secondary_filter import filter_skill_a, explain_filter

REPO_ROOT   = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "output"

BOOKS_TO_TEST = [
    "belitz_food_chemistry",
    "heldman_handbook_food_engineering",
]


def load_book_data(book_id: str) -> dict:
    """Load pages, signals, progress, and results for a book."""
    base = OUTPUT_ROOT / book_id
    skill_dir = base / "skill_a"

    pages_path    = base / "pages.json"
    signals_path  = base / "signals.json"
    progress_path = skill_dir / "_progress.json"
    results_path  = skill_dir / "results.jsonl"

    missing = [p for p in [pages_path, signals_path, progress_path, results_path]
               if not p.exists()]
    if missing:
        return {"error": f"Missing files: {[str(p) for p in missing]}"}

    pages_map   = {p["page"]: p.get("text", "")
                   for p in json.loads(pages_path.read_text())}
    signals_map = {s["page"]: s
                   for s in json.loads(signals_path.read_text())}
    progress    = json.loads(progress_path.read_text())
    done_pages  = set(progress.get("done_pages", []))

    # Parse results.jsonl — classify each done page
    has_data: set[int] = set()    # pages with ≥1 real mother_formula record
    is_empty: set[int] = set()    # pages processed but yielded no real records

    page_records: dict[int, list] = {}
    for line in results_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            pg  = rec.get("_page")
            if pg is None:
                continue
            page_records.setdefault(int(pg), []).append(rec)
        except Exception:
            pass

    for pg in done_pages:
        recs = page_records.get(pg, [])
        real_recs = [r for r in recs
                     if "mother_formula" in r and not r.get("_filtered") and not r.get("_error")]
        if real_recs:
            has_data.add(pg)
        else:
            is_empty.add(pg)

    return {
        "book_id":    book_id,
        "pages_map":  pages_map,
        "signals_map": signals_map,
        "done_pages": done_pages,
        "has_data":   has_data,
        "is_empty":   is_empty,
    }


def analyze_veto(book_data: dict, verbose: bool = False) -> dict:
    """
    Run current filter (with Veto rules) on both data and empty page sets.
    Returns result dict.
    """
    book_id     = book_data["book_id"]
    pages_map   = book_data["pages_map"]
    signals_map = book_data["signals_map"]
    has_data    = book_data["has_data"]
    is_empty    = book_data["is_empty"]

    # --- Check data pages (must NOT be vetoed) ---
    fn_pages: list[dict] = []          # false negatives: data pages vetoed
    for pg in sorted(has_data):
        sig  = signals_map.get(pg, {})
        text = pages_map.get(pg, "")
        keep, reason = filter_skill_a(text, sig)
        if not keep and reason.startswith("veto"):
            detail = explain_filter(text, sig)
            fn_pages.append({
                "page":   pg,
                "reason": reason,
                "text_snippet": text[:120].replace("\n", " "),
                "detail": detail,
            })

    # --- Check empty pages (want to filter MORE of these) ---
    newly_vetoed: list[dict] = []      # empty pages now caught by new Veto rules
    still_passing: list[dict] = []     # empty pages still let through

    veto_reason_counts: dict[str, int] = {}
    for pg in sorted(is_empty):
        sig  = signals_map.get(pg, {})
        text = pages_map.get(pg, "")
        keep, reason = filter_skill_a(text, sig)
        if not keep and reason.startswith("veto"):
            veto_reason_counts[reason] = veto_reason_counts.get(reason, 0) + 1
            entry = {"page": pg, "reason": reason, "text_snippet": text[:80].replace("\n", " ")}
            newly_vetoed.append(entry)
        elif not keep:
            pass   # filtered by existing rules — not new
        else:
            still_passing.append({"page": pg, "reason": reason})

    result = {
        "book_id":            book_id,
        "data_pages":         len(has_data),
        "empty_pages":        len(is_empty),
        "fn_count":           len(fn_pages),            # false negatives — must be 0
        "newly_vetoed_count": len(newly_vetoed),        # new empty pages filtered
        "veto_reason_counts": veto_reason_counts,
        "fn_pages":           fn_pages,
        "newly_vetoed":       newly_vetoed if verbose else newly_vetoed[:10],
    }
    return result


def print_report(result: dict, verbose: bool = False) -> None:
    book_id = result["book_id"]
    fn      = result["fn_count"]
    vetoed  = result["newly_vetoed_count"]

    pass_icon = "✅" if fn == 0 else "❌"
    print(f"\n{'='*60}")
    print(f"Book: {book_id}")
    print(f"{'='*60}")
    print(f"  Data pages (≥1 extraction):  {result['data_pages']}")
    print(f"  Empty pages (0 extractions): {result['empty_pages']}")
    print(f"  Newly vetoed empty pages:    {vetoed}  ← new filtering by Veto rules")
    print(f"  False negatives (data→veto): {fn}  {pass_icon}")

    if result["veto_reason_counts"]:
        print(f"\n  Veto breakdown (empty pages caught):")
        for reason, count in sorted(result["veto_reason_counts"].items(), key=lambda x: -x[1]):
            print(f"    {reason:<30} {count:>5}")

    if fn > 0:
        print(f"\n  ⚠️  FALSE NEGATIVES — data pages that would be wrongly vetoed:")
        for fn_pg in result["fn_pages"]:
            print(f"    p{fn_pg['page']:04d} [{fn_pg['reason']}]: {fn_pg['text_snippet']!r}")

    if verbose and result["newly_vetoed"]:
        print(f"\n  Newly vetoed pages (sample):")
        for entry in result["newly_vetoed"][:20]:
            print(f"    p{entry['page']:04d} [{entry['reason']}]: {entry['text_snippet']!r}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate Veto filter against known Skill A results")
    p.add_argument("--book-id", default=None,
                   help="Test one book only (default: both belitz + heldman)")
    p.add_argument("--verbose", action="store_true",
                   help="Show sample vetoed pages and all FN details")
    return p.parse_args()


def main() -> None:
    args     = parse_args()
    books    = [args.book_id] if args.book_id else BOOKS_TO_TEST
    any_fail = False

    for book_id in books:
        print(f"\nLoading {book_id}...", end=" ", flush=True)
        data = load_book_data(book_id)
        if "error" in data:
            print(f"ERROR: {data['error']}")
            any_fail = True
            continue
        print("OK")

        result = analyze_veto(data, verbose=args.verbose)
        print_report(result, verbose=args.verbose)

        if result["fn_count"] > 0:
            any_fail = True

    print(f"\n{'='*60}")
    if any_fail:
        print("RESULT: ❌ Some Veto rules caused false negatives or errors — review above")
        sys.exit(1)
    else:
        print("RESULT: ✅ All Veto rules passed — zero false negatives")


if __name__ == "__main__":
    main()
