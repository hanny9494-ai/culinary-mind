#!/usr/bin/env python3
"""merge_r1_r2.py — Merge R1 atom fields into completed R2 atoms.

Strategy: R2 fields take priority; R1 fields fill any gaps.
  merged = {**r1_atom, **r2_atom}
  merged['canonical_id'] = r2_atom['canonical_id']  # never overwrite

Usage:
  python pipeline/l2a/merge_r1_r2.py            # dry-run (prints report)
  python pipeline/l2a/merge_r1_r2.py --inplace  # update atoms_r2/*.json in-place
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ATOMS_R1_DIR = REPO_ROOT / "output" / "l2a" / "atoms"
ATOMS_R2_DIR = REPO_ROOT / "output" / "l2a" / "atoms_r2"

# R2 adds exactly these fields to R1 atoms (all other fields come from R1)
R2_NEW_FIELDS = {'culinary_deep', 'substitutes', 'processing_effects',
                 'quality_indicators', 'l0_principles'}


def load_r1_map() -> dict[str, dict]:
    """Load all R1 atoms indexed by canonical_id."""
    r1_map: dict[str, dict] = {}
    for f in ATOMS_R1_DIR.glob("*.json"):
        try:
            atom = json.loads(f.read_text(encoding="utf-8"))
            cid = atom.get("canonical_id") or f.stem
            r1_map[cid] = atom
        except Exception as e:
            print(f"  [warn] skip unreadable R1 {f.name}: {e}", file=sys.stderr)
    return r1_map


def main(inplace: bool) -> None:
    print(f"Loading R1 atoms from {ATOMS_R1_DIR} ...")
    r1_map = load_r1_map()
    print(f"  {len(r1_map)} R1 atoms loaded")

    r2_files = [
        f for f in ATOMS_R2_DIR.glob("*.json")
        if not f.name.startswith("_")
    ]
    print(f"Loading {len(r2_files)} R2 atoms from {ATOMS_R2_DIR} ...")

    total_r2 = len(r2_files)
    merged_count = 0
    no_r1_count = 0
    error_count = 0

    for r2_path in sorted(r2_files):
        try:
            r2_atom = json.loads(r2_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [error] cannot read {r2_path.name}: {e}", file=sys.stderr)
            error_count += 1
            continue

        cid = r2_atom.get("canonical_id") or r2_path.stem

        r1_atom = r1_map.get(cid)
        if r1_atom is None:
            # No matching R1 — keep R2 as-is
            no_r1_count += 1
            continue

        # Merge: R1 as base, R2 fields override, canonical_id always from R2
        # R1 is authoritative base; only graft the 5 new R2 fields
        merged = {**r1_atom}
        for field in R2_NEW_FIELDS:
            if field in r2_atom:
                merged[field] = r2_atom[field]
        merged["canonical_id"] = cid

        if inplace:
            try:
                r2_path.write_text(
                    json.dumps(merged, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                print(f"  [error] write failed for {cid}: {e}", file=sys.stderr)
                error_count += 1
                continue

        merged_count += 1

    print()
    print("=== merge_r1_r2 report ===")
    print(f"  Total R2 atoms:      {total_r2}")
    print(f"  Merged with R1:      {merged_count}")
    print(f"  No matching R1:      {no_r1_count}")
    print(f"  Errors:              {error_count}")
    if inplace:
        print(f"  Mode:                in-place (atoms_r2/*.json updated)")
    else:
        print(f"  Mode:                dry-run  (no files written; add --inplace to apply)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Merge R1 fields into R2 atoms")
    p.add_argument("--inplace", action="store_true",
                   help="Update atoms_r2/*.json files in-place (default: dry-run)")
    args = p.parse_args()
    main(inplace=args.inplace)
