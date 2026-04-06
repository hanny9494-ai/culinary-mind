#!/usr/bin/env python3
"""
整理 output 目录：每本书一个文件夹，内含 ocr/stage1/stage4/stage5。
安全策略：只移动文件，不删除；旧路径创建 symlink 保持兼容。

Usage:
    python3 scripts/reorganize_output.py --dry-run   # 先看计划
    python3 scripts/reorganize_output.py              # 执行
"""

import json
import shutil
import argparse
from pathlib import Path

L0_OUTPUT = Path(__file__).resolve().parent.parent / "output"
CE_OUTPUT = Path.home() / "culinary-engine" / "output"

# Archive these subdirectories (test/obsolete data)
ARCHIVE_PATTERNS = [
    "vlm_test_*", "vlm_annotated_test", "pages_150dpi",
    "mineru_parts", "raw_mineru.md", "raw_vision.md",
    "comparison", "toc_candidate.json",
]

# Don't touch these books (currently being processed by 2b/9b)
SKIP_BOOKS = set()  # Will be populated by checking for active processes


def find_active_books():
    """Find books with recently modified chunks files (likely being processed)."""
    import time
    active = set()
    now = time.time()
    threshold = 3600  # 1 hour

    for d in CE_OUTPUT.iterdir():
        if not d.is_dir():
            continue
        for f in d.rglob("chunks_raw.json"):
            if now - f.stat().st_mtime < threshold:
                active.add(d.name)
        for f in d.rglob("chunks_smart.json"):
            if now - f.stat().st_mtime < threshold:
                active.add(d.name)

    # Also check l0 output
    for d in L0_OUTPUT.iterdir():
        if not d.is_dir() or d.name.startswith("stage"):
            continue
        for f in d.rglob("chunks_smart.json"):
            if now - f.stat().st_mtime < threshold:
                active.add(d.name)

    return active


def plan_moves(dry_run=True):
    moves = []
    symlinks = []
    archives = []

    # --- 1. Consolidate stage4_{book} → {book}/stage4/ ---
    for d in sorted(L0_OUTPUT.glob("stage4_*")):
        if not d.is_dir():
            continue
        book = d.name.replace("stage4_", "")
        if not book:  # skip bare "stage4/"
            continue

        target = L0_OUTPUT / book / "stage4"
        if target.exists():
            continue  # Already reorganized

        moves.append(("stage4", d, target))
        # Create symlink for backward compat
        symlinks.append((target, d))

    # --- 2. Consolidate culinary-engine Stage1 files → l0/{book}/stage1/ ---
    for d in sorted(CE_OUTPUT.iterdir()):
        if not d.is_dir():
            continue
        book = d.name
        if book.startswith("stage5") or book.startswith("l2a") or book.startswith("_") or book.startswith("runtime"):
            continue
        if book in SKIP_BOOKS:
            continue

        target_dir = L0_OUTPUT / book / "stage1"

        # Move key Stage1 files
        for fname in ["raw_merged.md", "chunks_raw.json", "chunks_smart.json",
                       "annotation_failures.json"]:
            src = d / fname
            if src.exists():
                dst = target_dir / fname
                if not dst.exists():
                    moves.append(("stage1", src, dst))

            # Also check stage1 subdir
            src2 = d / "stage1" / fname
            if src2.exists():
                dst = target_dir / fname
                if not dst.exists():
                    moves.append(("stage1", src2, dst))

    # --- 3. Consolidate Stage5 → {book}/stage5/ ---
    stage5_batch = CE_OUTPUT / "stage5_batch"
    if stage5_batch.exists():
        for d in sorted(stage5_batch.iterdir()):
            if not d.is_dir():
                continue
            book = d.name
            target = L0_OUTPUT / book / "stage5"
            if target.exists():
                continue

            # Only move if there's actual data
            results = d / "stage5_results.jsonl"
            if results.exists() and results.stat().st_size > 200:
                moves.append(("stage5", d, target))

    # --- 4. Reorganize OCR files: vlm_full_flash/ → ocr/ ---
    for d in sorted(L0_OUTPUT.iterdir()):
        if not d.is_dir() or d.name.startswith("stage"):
            continue

        vlm = d / "vlm_full_flash"
        if vlm.exists() and not (d / "ocr").exists():
            moves.append(("ocr_rename", vlm, d / "ocr"))

        # Handle split OCR (french_patisserie has part1/part2)
        for part in d.glob("vlm_full_flash_part*"):
            if not (d / "ocr" / part.name.replace("vlm_full_flash_", "")).exists():
                moves.append(("ocr_part", part, d / "ocr" / part.name.replace("vlm_full_flash_", "")))

    # --- 5. Archive old test/obsolete files ---
    for d in sorted(L0_OUTPUT.iterdir()):
        if not d.is_dir() or d.name.startswith("stage"):
            continue

        archive_target = d / "_archive"

        for pattern in ARCHIVE_PATTERNS:
            for match in d.glob(pattern):
                if match.exists() and "_archive" not in str(match):
                    archives.append((match, archive_target / match.name))

    return moves, symlinks, archives


def execute(moves, symlinks, archives, dry_run=True):
    prefix = "[DRY-RUN] " if dry_run else ""

    print(f"\n{'='*60}")
    print(f"{'DRY RUN - No changes made' if dry_run else 'EXECUTING'}")
    print(f"{'='*60}")

    # Moves
    print(f"\n--- Moves ({len(moves)}) ---")
    for category, src, dst in moves:
        print(f"  {prefix}{category:12s} {src} → {dst}")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

    # Symlinks for backward compat (stage4 only)
    print(f"\n--- Symlinks ({len(symlinks)}) ---")
    for target, link_path in symlinks:
        if not dry_run and not link_path.is_symlink():
            # Remove original dir after copy, replace with symlink
            if link_path.exists() and target.exists():
                shutil.rmtree(link_path)
                link_path.symlink_to(target)
                print(f"  {prefix}symlink {link_path} → {target}")
        else:
            print(f"  {prefix}symlink {link_path} → {target}")

    # Archives
    print(f"\n--- Archives ({len(archives)}) ---")
    for src, dst in archives:
        print(f"  {prefix}{src} → {dst}")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    # Summary
    print(f"\n--- Summary ---")
    print(f"  Moves:    {len(moves)}")
    print(f"  Symlinks: {len(symlinks)}")
    print(f"  Archives: {len(archives)}")
    if dry_run:
        print(f"\n  Run without --dry-run to execute.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    global SKIP_BOOKS
    SKIP_BOOKS = find_active_books()
    if SKIP_BOOKS:
        print(f"⚠ Skipping active books: {', '.join(SKIP_BOOKS)}")

    moves, symlinks, archives = plan_moves(args.dry_run)
    execute(moves, symlinks, archives, args.dry_run)


if __name__ == "__main__":
    main()
