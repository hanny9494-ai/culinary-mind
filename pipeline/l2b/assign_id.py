#!/usr/bin/env python3
"""
assign_recipe_id.py — Stage 5.6
Assign unique recipe_id to every recipe in stage5_batch output files.

ID format: {book_id}_r{seq:04d}, e.g. ofc_r0001
- book_id = filename stem with '_recipes' removed
- seq starts at 0001 per book, independent numbering
- In-place update; skips recipes that already have a recipe_id
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGE5_DIR = ROOT / "output" / "stage5_batch"


def main() -> None:
    # Each book is a directory containing stage5_results.jsonl
    # Each line in the JSONL is a chunk: {book_id, chunk_idx, chunk_type, topics, recipes[]}
    # Recipes are nested inside chunks.
    jsonl_files = sorted(STAGE5_DIR.glob("*/stage5_results.jsonl"))
    if not jsonl_files:
        print(f"No stage5_results.jsonl files found in {STAGE5_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(jsonl_files)} book(s)")

    total_assigned = 0
    total_skipped = 0
    books_processed = 0

    for jf in jsonl_files:
        book_id = jf.parent.name

        try:
            lines = jf.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            print(f"  [ERROR] {book_id}: {exc}")
            continue

        seq = 1
        assigned = 0
        skipped = 0
        modified = False
        new_lines = []

        for line in lines:
            line = line.strip()
            if not line:
                new_lines.append(line)
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                new_lines.append(line)
                continue

            for recipe in chunk.get("recipes") or []:
                if not isinstance(recipe, dict):
                    continue
                existing = recipe.get("recipe_id")
                if existing and isinstance(existing, str) and existing.strip():
                    skipped += 1
                    seq += 1
                    continue
                recipe["recipe_id"] = f"{book_id}_r{seq:04d}"
                seq += 1
                assigned += 1
                modified = True

            new_lines.append(json.dumps(chunk, ensure_ascii=False))

        if modified:
            jf.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        total_assigned += assigned
        total_skipped += skipped
        books_processed += 1
        print(f"  {book_id}: assigned={assigned}, skipped={skipped}")

    print(
        f"\nDone. books={books_processed}, "
        f"recipes_assigned={total_assigned}, "
        f"recipes_skipped(already had id)={total_skipped}"
    )


if __name__ == "__main__":
    main()
