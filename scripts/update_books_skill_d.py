#!/usr/bin/env python3
"""
scripts/update_books_skill_d.py
Batch update books.yaml:
  1. Remove "D" from skills + set skill_d_status=skip for 31 English science books
  2. Upgrade ice_cream_flavor: add "A", skill_a_status=pending, parameter_density=high, priority=P1

Uses line-by-line string replacement to preserve YAML comments.
"""

import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BOOKS_YAML = REPO_ROOT / "config" / "books.yaml"
BOOKS_YAML_BAK = REPO_ROOT / "config" / "books.yaml.bak"

# 31 English science books to remove Skill D
REMOVE_D_BOOKS = {
    "mc_vol1", "mc_vol2", "mc_vol3", "mc_vol4",
    "food_lab", "science_good_cooking", "essentials_food_science",
    "professional_baking", "professional_chef", "professional_pastry_chef",
    "chocolates_confections", "science_of_chocolate", "molecular_gastronomy",
    "bread_hamelman", "koji_alchemy", "handbook_molecular_gastronomy",
    "bread_science_yoshino", "cooking_for_geeks", "modernist_pizza",
    "noma_fermentation", "ratio", "sous_vide_keller", "charcuterie",
    "art_of_fermentation", "french_patisserie", "vegetarian_flavor_bible",
    "ofc", "franklin_barbecue", "japanese_cooking_tsuji", "jacques_pepin",
}

ICE_CREAM_ID = "ice_cream_flavor"


def remove_skill_d_from_list(skills_str: str) -> str:
    """Remove 'D' from a YAML inline list string like '["A", "B", "C", "D"]'."""
    # Match and remove "D" with surrounding quotes and optional comma/space
    # Handle patterns: "D", "D" at end, "D" at start
    result = re.sub(r',\s*"D"', '', skills_str)      # , "D"
    result = re.sub(r'"D",\s*', '', result)           # "D",
    result = re.sub(r'"D"', '', result)               # bare "D"
    # Clean up empty brackets or trailing/leading commas
    result = re.sub(r'\[\s*,\s*', '[', result)
    result = re.sub(r',\s*\]', ']', result)
    result = re.sub(r'\[\s*\]', '[]', result)
    return result


def add_skill_a_to_list(skills_str: str) -> str:
    """Add 'A' to front of a YAML inline list string like '["B", "C", "D"]'."""
    # Find the opening bracket
    match = re.match(r'(\s*skills:\s*)\[', skills_str)
    if match:
        prefix = match.group(1)
        rest = skills_str[len(match.group(0)):]
        # Check if "A" already present
        if '"A"' in skills_str:
            return skills_str
        # Add "A" at front
        return f'{prefix}["A", {rest}'
    return skills_str


def process_books_yaml(content: str) -> tuple[str, dict]:
    """
    Process the YAML content line by line, tracking which book block we're in.
    Returns (new_content, stats).
    """
    lines = content.splitlines(keepends=True)
    out = []

    current_book_id = None
    stats = {
        "removed_d": [],
        "not_found": list(REMOVE_D_BOOKS),  # will remove as we find them
        "ice_cream_changes": [],
        "already_no_d": [],
    }

    for i, line in enumerate(lines):
        # Detect book entry start
        id_match = re.match(r'^- id:\s*(\S+)', line)
        if id_match:
            current_book_id = id_match.group(1)
            # Remove from not_found if we encounter it
            if current_book_id in stats["not_found"]:
                stats["not_found"].remove(current_book_id)
            out.append(line)
            continue

        # Detect end of current book block (new book starts)
        # We stay in the same block until another "- id:" line

        # ── Modifications for REMOVE_D_BOOKS ──
        if current_book_id in REMOVE_D_BOOKS:
            # Modify skills line
            if re.match(r'\s+skills:\s*\[', line):
                if '"D"' in line:
                    new_line = remove_skill_d_from_list(line)
                    out.append(new_line)
                    if current_book_id not in stats["removed_d"]:
                        stats["removed_d"].append(current_book_id)
                    continue
                else:
                    if current_book_id not in stats["already_no_d"]:
                        stats["already_no_d"].append(current_book_id)

            # Modify skill_d_status line
            if re.match(r'\s+skill_d_status:\s*pending', line):
                new_line = re.sub(r'(skill_d_status:\s*)pending', r'\1skip', line)
                out.append(new_line)
                continue

            # Modify pipeline: remove "skill_d" entry
            if re.match(r'\s+pipeline:\s*\[', line) and '"skill_d"' in line:
                result = re.sub(r',\s*"skill_d"', '', line)
                result = re.sub(r'"skill_d",\s*', '', result)
                result = re.sub(r'"skill_d"', '', result)
                result = re.sub(r'\[\s*,\s*', '[', result)
                result = re.sub(r',\s*\]', ']', result)
                out.append(result)
                continue

        # ── Modifications for ice_cream_flavor ──
        if current_book_id == ICE_CREAM_ID:
            # Add "A" to skills
            if re.match(r'\s+skills:\s*\[', line):
                if '"A"' not in line:
                    new_line = add_skill_a_to_list(line)
                    out.append(new_line)
                    stats["ice_cream_changes"].append("skills: added A")
                    continue

            # skill_a_status: skip → pending
            if re.match(r'\s+skill_a_status:\s*skip', line):
                new_line = re.sub(r'(skill_a_status:\s*)skip', r'\1pending', line)
                out.append(new_line)
                stats["ice_cream_changes"].append("skill_a_status: skip→pending")
                continue

            # parameter_density: medium → high
            if re.match(r'\s+parameter_density:\s*medium', line):
                new_line = re.sub(r'(parameter_density:\s*)medium', r'\1high', line)
                out.append(new_line)
                stats["ice_cream_changes"].append("parameter_density: medium→high")
                continue

            # priority: P2 → P1
            if re.match(r'\s+priority:\s*P2', line):
                new_line = re.sub(r'(priority:\s*)P2', r'\1P1', line)
                out.append(new_line)
                stats["ice_cream_changes"].append("priority: P2→P1")
                continue

            # pipeline: add "skill_a" if not present
            if re.match(r'\s+pipeline:\s*\[', line):
                if '"skill_a"' not in line:
                    new_line = re.sub(r'(\s+pipeline:\s*\[)', r'\1"skill_a", ', line)
                    out.append(new_line)
                    stats["ice_cream_changes"].append('pipeline: added "skill_a"')
                    continue

        out.append(line)

    return ''.join(out), stats


def main():
    if not BOOKS_YAML.exists():
        print(f"ERROR: {BOOKS_YAML} not found", file=sys.stderr)
        sys.exit(1)

    # Backup
    shutil.copy2(BOOKS_YAML, BOOKS_YAML_BAK)
    print(f"✅ Backed up to {BOOKS_YAML_BAK}")

    content = BOOKS_YAML.read_text(encoding="utf-8")
    new_content, stats = process_books_yaml(content)

    BOOKS_YAML.write_text(new_content, encoding="utf-8")
    print(f"✅ Written {BOOKS_YAML}")

    # Summary
    print(f"\n── Change Summary ──")
    print(f"  Books with D removed:   {len(stats['removed_d'])}")
    for b in sorted(stats['removed_d']):
        print(f"    ✓ {b}")

    if stats["already_no_d"]:
        print(f"\n  Books already without D: {len(stats['already_no_d'])}")
        for b in sorted(stats["already_no_d"]):
            print(f"    - {b}")

    if stats["not_found"]:
        print(f"\n  Book IDs not found (skipped): {len(stats['not_found'])}")
        for b in sorted(stats["not_found"]):
            print(f"    ? {b}")

    print(f"\n  ice_cream_flavor changes:")
    for c in stats["ice_cream_changes"]:
        print(f"    ✓ {c}")

    print()


if __name__ == "__main__":
    main()
