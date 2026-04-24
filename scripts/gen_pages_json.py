#!/usr/bin/env python3
"""
scripts/gen_pages_json.py
Convert chunks_smart.json → pages.json for signal_router.py

pages.json format: [{"page": int, "text": str, "source": str}]
"""

import json, sys, argparse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

def find_chunks(book_id: str) -> Path | None:
    """Try multiple locations for chunks_smart.json"""
    candidates = [
        REPO / "output" / book_id / "prep" / "prep" / "chunks_smart.json",
        REPO / "output" / book_id / "prep" / "chunks_smart.json",
        REPO / "output" / book_id / "stage1" / "stage1" / "chunks_smart.json",
        REPO / "output" / book_id / "stage1" / "chunks_smart.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def convert(book_id: str, force: bool = False) -> int:
    out_path = REPO / "output" / book_id / "pages.json"
    if out_path.exists() and not force:
        print(f"[skip] {book_id}: pages.json already exists")
        return 0

    chunks_path = find_chunks(book_id)
    if not chunks_path:
        print(f"[ERROR] {book_id}: no chunks_smart.json found")
        return -1

    chunks = json.loads(chunks_path.read_text())
    pages = []
    for c in chunks:
        idx = c.get("chunk_idx", c.get("id", len(pages)))
        text = c.get("full_text", c.get("text", ""))
        pages.append({"page": idx, "text": text, "source": "chunks_smart"})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(pages, ensure_ascii=False, indent=2))
    print(f"[ok] {book_id}: {len(pages)} pages → {out_path}")
    return len(pages)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-ids", nargs="+", help="List of book IDs, or 'all'")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not args.book_ids:
        print("Usage: gen_pages_json.py --book-ids book1 book2 ...")
        sys.exit(1)

    total = 0
    for bid in args.book_ids:
        n = convert(bid, force=args.force)
        if n > 0:
            total += n

    print(f"\nDone. Total pages generated: {total}")


if __name__ == "__main__":
    main()
