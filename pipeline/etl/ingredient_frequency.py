#!/usr/bin/env python3
"""
pipeline/etl/ingredient_frequency.py
P1-12 — Count ingredient occurrences across every L2b recipe and emit
a frequency-ranked JSON table.

Sources scanned (all books under `output/`):
  • NEW pipeline:  output/{book_id}/skill_b/results.jsonl
                   (recipes at top level; ingredient field name = `name`)
  • OLD pipeline:  output/{book_id}/l2b/stage5_results.jsonl
                   (recipes wrapped in `recipes[]`; ingredient name = `item`)

Cleanup:
  • strip + collapse whitespace
  • lowercase (CJK unaffected)
  • opencc t2s 繁→简 normalisation
  • drop common quantity-only tokens (适量 / 少许 / to taste / as needed …)
  • drop trailing punctuation and parenthetical modifiers like "(diced)"

Output:  output/phase1/ingredient_frequency.json
{
  "total_recipes":           int,
  "total_unique_ingredients":int,
  "frequencies": [
    {"ingredient": "salt", "count": N, "pct": N.NN},
    ...
  ],
  "_meta": {...},
}

Run:
  /Users/jeff/miniforge3/bin/python3 pipeline/etl/ingredient_frequency.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

try:
    import opencc
    _T2S = opencc.OpenCC("t2s")
except Exception as e:   # noqa: BLE001
    print(f"ERROR: opencc-python-reimplemented not installed: {e}", file=sys.stderr)
    print("Install: /Users/jeff/miniforge3/bin/python3 -m pip install opencc-python-reimplemented",
          file=sys.stderr)
    sys.exit(1)


REPO_ROOT   = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "output"
OUT_JSON    = OUTPUT_ROOT / "phase1" / "ingredient_frequency.json"


# Filler / quantity-only words — these appear as ingredient entries in
# casual recipes but aren't real ingredients.
STOPWORDS: set[str] = {
    "适量", "少许", "少量", "若干", "酌量", "随意", "按需",
    "一些", "数粒", "数片", "数根",
    "to taste", "as needed", "as desired", "optional", "for garnish",
    "for serving", "for dusting", "for brushing", "for sprinkling",
}
_ALNUM_RE = re.compile(r"[\w\u4e00-\u9fff]")


# ── Cleanup ─────────────────────────────────────────────────────────────────

def _clean(raw: str) -> str:
    """Normalise a single ingredient name. Returns '' if it should be dropped."""
    if not raw:
        return ""
    s = str(raw).strip()
    # drop trailing parenthetical (e.g. " (diced)")
    s = re.sub(r"\s*[\(（][^)）]*[\)）]\s*$", "", s).strip()
    # trim trailing punctuation
    s = s.strip(",，.。;；:：")
    if not s or not _ALNUM_RE.search(s):
        return ""
    # 繁→简 first so traditional-form stopwords (e.g. 適量) get caught
    # by the canonical (simplified) STOPWORDS set below.
    s = _T2S.convert(s)
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    if s in STOPWORDS:
        return ""
    return s


# ── Scanners ────────────────────────────────────────────────────────────────

def scan_skill_b(counter: Counter[str]) -> tuple[int, int]:
    """Returns (files_scanned, recipes_counted)."""
    files = recipes = 0
    for path in sorted(OUTPUT_ROOT.glob("*/skill_b/results.jsonl")):
        files += 1
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("_error"):
                    continue
                ings = rec.get("ingredients") or []
                if not ings:
                    continue
                recipes += 1
                for ing in ings:
                    if not isinstance(ing, dict):
                        continue
                    name = _clean(ing.get("name", ""))
                    if name:
                        counter[name] += 1
    return files, recipes


def scan_stage5(counter: Counter[str]) -> tuple[int, int]:
    """Returns (files_scanned, recipes_counted)."""
    files = recipes = 0
    for path in sorted(OUTPUT_ROOT.glob("*/l2b/stage5_results.jsonl")):
        files += 1
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("_error"):
                    continue
                for r in rec.get("recipes") or []:
                    if not isinstance(r, dict):
                        continue
                    ings = r.get("ingredients") or []
                    if not ings:
                        continue
                    recipes += 1
                    for ing in ings:
                        if not isinstance(ing, dict):
                            continue
                        name = _clean(ing.get("item", ""))
                        if name:
                            counter[name] += 1
    return files, recipes


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    counter: Counter[str] = Counter()
    f_b, r_b = scan_skill_b(counter)
    f_5, r_5 = scan_stage5(counter)

    total_recipes = r_b + r_5
    if total_recipes == 0:
        print("ERROR: no recipes found in any source", file=sys.stderr)
        return 1

    # Each ingredient name occurrence counts as one — pct is share of
    # all (ingredient, recipe) appearances.
    total_appearances = sum(counter.values())
    frequencies: list[dict] = []
    for ing, n in counter.most_common():
        frequencies.append({
            "ingredient": ing,
            "count":      n,
            "pct":        round(100.0 * n / total_appearances, 2),
        })

    payload = {
        "_meta": {
            "task":                "P1-12",
            "date":                time.strftime("%Y-%m-%d", time.gmtime()),
            "files_scanned":       {"skill_b": f_b, "l2b_stage5": f_5},
            "total_appearances":   total_appearances,
            "normalisation":       "lowercase + CJK trad→simp + strip parentheticals + filter quantity stopwords",
        },
        "total_recipes":            total_recipes,
        "total_unique_ingredients": len(frequencies),
        "frequencies":              frequencies,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT_JSON)

    # Stdout summary
    print(f"\n── Ingredient Frequency (P1-12) ──")
    print(f"  files scanned:      skill_b={f_b}, l2b_stage5={f_5}")
    print(f"  total recipes:      {total_recipes}")
    print(f"  unique ingredients: {len(frequencies)}")
    print(f"  total appearances:  {total_appearances}")
    print(f"  output:             {OUT_JSON}")
    print(f"\n── Top 20 ──")
    for r in frequencies[:20]:
        print(f"  {r['count']:>5} ({r['pct']:>5.2f}%)  {r['ingredient']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
