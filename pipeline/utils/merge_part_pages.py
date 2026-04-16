#!/usr/bin/env python3
"""
pipeline/utils/merge_part_pages.py
Merge multiple part-level pages.json files into one, with sequential page numbering.

Used by scripts/ocr_mc_volumes.sh after per-part OCR completes.

Each part's pages are renumbered so they continue from where the previous part ended:
  part1: pages 1..N1
  part2: pages N1+1..N1+N2
  part3: etc.

Usage:
    python pipeline/utils/merge_part_pages.py \
        --parts-dir output/mc_vol2/parts \
        --out output/mc_vol2/pages.json \
        --book-id mc_vol2

    python pipeline/utils/merge_part_pages.py \
        --parts part1/pages.json part2/pages.json \
        --out merged.json
"""

import argparse
import json
import sys
from pathlib import Path


def find_part_dirs(parts_dir: Path) -> list[Path]:
    """Return sorted list of part subdirectories that contain pages.json."""
    dirs = sorted(
        [d for d in parts_dir.iterdir() if d.is_dir() and (d / "pages.json").exists()],
        key=lambda d: _part_sort_key(d.name),
    )
    return dirs


def _part_sort_key(name: str) -> tuple:
    """Sort part1, part2, ..., part10 correctly (numeric, not lexicographic)."""
    import re
    m = re.search(r"(\d+)", name)
    return (int(m.group(1)),) if m else (0,)


def merge_pages(
    part_json_paths: list[Path],
    book_id: str = "",
    start_page: int = 1,
) -> list[dict]:
    """
    Load and merge multiple pages.json files into one list.
    Page numbers are renumbered sequentially: part1 keeps its numbers,
    part2 is offset by max(part1.page), etc.
    """
    merged: list[dict] = []
    current_page = start_page - 1  # will be incremented before each page

    for idx, path in enumerate(part_json_paths, start=1):
        try:
            pages = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  WARNING: could not read {path}: {e}", file=sys.stderr)
            continue

        if not pages:
            print(f"  WARNING: {path} is empty, skipping", file=sys.stderr)
            continue

        # Detect original page count for logging
        orig_min = min(p["page"] for p in pages)
        orig_max = max(p["page"] for p in pages)
        n = len(pages)

        # Sort pages within this part by original page number
        pages_sorted = sorted(pages, key=lambda p: p["page"])

        # Assign new sequential page numbers
        for page in pages_sorted:
            current_page += 1
            new_page = {
                **page,
                "page": current_page,
                "part": idx,
                "part_page": page["page"],  # original page number within this part
            }
            if book_id:
                new_page["book_id"] = book_id
            merged.append(new_page)

        print(
            f"  part{idx}: {path} → {n} pages "
            f"(orig {orig_min}-{orig_max} → merged {current_page - n + 1}-{current_page})"
        )

    return merged


def main() -> None:
    p = argparse.ArgumentParser(description="Merge part-level pages.json files with sequential page numbering")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--parts-dir",
        help="Directory containing part1/, part2/, ... subdirs with pages.json",
    )
    grp.add_argument(
        "--parts",
        nargs="+",
        help="Explicit list of pages.json file paths (in order)",
    )
    p.add_argument("--out", required=True, help="Output merged pages.json path")
    p.add_argument("--book-id", default="", help="Book ID to tag each page (optional)")
    p.add_argument("--start-page", type=int, default=1, help="Starting page number (default: 1)")
    p.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    args = p.parse_args()

    out_path = Path(args.out)

    # Resolve input files
    if args.parts_dir:
        parts_dir = Path(args.parts_dir)
        if not parts_dir.exists():
            print(f"ERROR: --parts-dir {parts_dir} does not exist", file=sys.stderr)
            sys.exit(1)
        part_dirs = find_part_dirs(parts_dir)
        if not part_dirs:
            print(f"ERROR: No part directories with pages.json found in {parts_dir}", file=sys.stderr)
            sys.exit(1)
        part_json_paths = [d / "pages.json" for d in part_dirs]
        print(f"Found {len(part_json_paths)} parts in {parts_dir}:")
        for i, pp in enumerate(part_json_paths, 1):
            n = len(json.loads(pp.read_text()))
            print(f"  part{i}: {pp} ({n} pages)")
    else:
        part_json_paths = [Path(f) for f in args.parts]
        for pp in part_json_paths:
            if not pp.exists():
                print(f"ERROR: {pp} does not exist", file=sys.stderr)
                sys.exit(1)

    if args.dry_run:
        print(f"\n[dry-run] Would merge {len(part_json_paths)} parts → {out_path}")
        return

    # Merge
    print(f"\nMerging {len(part_json_paths)} parts → {out_path} ...")
    merged = merge_pages(part_json_paths, book_id=args.book_id, start_page=args.start_page)

    if not merged:
        print("ERROR: Merge produced 0 pages — aborting", file=sys.stderr)
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    total = len(merged)
    print(f"\nDone: {total} pages merged → {out_path}")
    print(f"  Page range: {merged[0]['page']} – {merged[-1]['page']}")


if __name__ == "__main__":
    main()
