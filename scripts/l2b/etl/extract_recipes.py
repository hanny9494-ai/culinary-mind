#!/usr/bin/env python3
"""P2-Lb1 Step 1: Extract 54K recipes from Stage5 → flat CSVs for Neo4j LOAD.

Schema (temp namespace CKG_L2B_TMP_*):
- CKG_L2B_TMP_Recipe: recipe_id / name / book_id / yield_text / recipe_type
- CKG_L2B_TMP_Step: step_id / recipe_id / order / text / action / duration_min / temp_c
- CKG_L2B_TMP_Ingredient: ingredient_id (=lowercase item slug) / item / qty / unit / note

Edges:
- HAS_STEP: Recipe → Step (kind=ordered)
- USES_INGREDIENT: Recipe → Ingredient
- HAS_EQUIPMENT: Recipe → Equipment (later via P2-Ic6)

Output: output/l2b/etl/{recipes,steps,ingredients}.csv + has_step_edges.csv + uses_ingredient_edges.csv + cypher

Idempotent: each recipe gets stable recipe_id (book + chunk_idx + recipe_index).
"""
import csv
import json
import re
from pathlib import Path
from collections import defaultdict

ROOT = Path("/Users/jeff/culinary-mind")
OUT_DIR = ROOT / "output/l2b/etl"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def slugify(s, max_len=80):
    if not s: return ""
    s = re.sub(r'[^\w\s-]', '', s.lower(), flags=re.UNICODE)
    s = re.sub(r'\s+', '_', s.strip())
    return s[:max_len]

def main():
    recipe_rows = []
    step_rows = []
    ingredient_rows = []   # unique per (recipe_id, ingredient_slug)
    has_step_edges = []
    uses_ingredient_edges = []

    unique_ingredient_slugs = set()  # global ingredient pool (dedup)
    ingredient_node_rows = {}        # slug → first occurrence row

    total_recipes = 0
    total_steps = 0
    total_uses = 0
    books_seen = set()

    for stage5_path in sorted(ROOT.glob("output/*/stage5/stage5_results.jsonl")) + \
                      sorted(ROOT.glob("output/*/l2b/stage5_results.jsonl")):
        # Book name: parent of parent (output/{book}/stage5/...)
        book_id = stage5_path.parents[1].name
        books_seen.add(book_id)
        with open(stage5_path, encoding="utf-8") as f:
            for line in f:
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not chunk.get("recipes"):
                    continue
                chunk_idx = chunk.get("chunk_idx", 0)
                for rec_idx, rec in enumerate(chunk["recipes"]):
                    # recipe_id: stable across runs
                    name_slug = slugify(rec.get("name", ""), 60)
                    raw_key = f"{book_id}|{chunk_idx}|{rec_idx}|{name_slug}"
                    import hashlib
                    short_hash = hashlib.md5(raw_key.encode()).hexdigest()[:6]
                    recipe_id = f"{book_id}__c{chunk_idx}_r{rec_idx}_{short_hash}"
                    total_recipes += 1
                    recipe_rows.append({
                        "recipe_id": recipe_id,
                        "name": rec.get("name", ""),
                        "book_id": book_id,
                        "yield_text": rec.get("yield_text", "") or "",
                        "recipe_type": rec.get("recipe_type", "") or "",
                        "n_steps": len(rec.get("steps", [])),
                        "n_ingredients": len(rec.get("ingredients", [])),
                    })

                    # Steps
                    for step_idx, step in enumerate(rec.get("steps", [])):
                        order = step.get("order", 0)
                        step_id = f"{recipe_id}__s{step_idx}"
                        total_steps += 1
                        step_rows.append({
                            "step_id": step_id,
                            "recipe_id": recipe_id,
                            "order": order,
                            "text": (step.get("text") or "")[:500],
                            "action": (step.get("action") or "")[:50],
                            "duration_min": step.get("duration_min") or "",
                            "temp_c": step.get("temp_c") or "",
                        })
                        has_step_edges.append({"recipe_id": recipe_id, "step_id": step_id, "order": order})

                    # Ingredients
                    for ing in rec.get("ingredients", []):
                        item = (ing.get("item") or "").strip()
                        if not item:
                            continue
                        ing_slug = slugify(item, 80)
                        if not ing_slug:
                            continue
                        # Track unique ingredient nodes
                        if ing_slug not in unique_ingredient_slugs:
                            unique_ingredient_slugs.add(ing_slug)
                            ingredient_node_rows[ing_slug] = {
                                "ingredient_slug": ing_slug,
                                "item_raw": item,
                            }
                        # Edge: recipe → ingredient
                        total_uses += 1
                        uses_ingredient_edges.append({
                            "recipe_id": recipe_id,
                            "ingredient_slug": ing_slug,
                            "qty": ing.get("qty") or "",
                            "unit": ing.get("unit") or "",
                            "note": (ing.get("note") or "")[:200],
                        })

    # Write CSVs (atomic)
    def write_csv(name, rows, fields):
        if not rows: 
            print(f"  ! {name}: empty"); return
        p = OUT_DIR / name
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows: w.writerow(r)
        tmp.rename(p)
        print(f"  ✅ {name}: {len(rows):,} rows")

    write_csv("recipes.csv", recipe_rows, ["recipe_id", "name", "book_id", "yield_text", "recipe_type", "n_steps", "n_ingredients"])
    write_csv("steps.csv", step_rows, ["step_id", "recipe_id", "order", "text", "action", "duration_min", "temp_c"])
    write_csv("ingredients.csv", list(ingredient_node_rows.values()), ["ingredient_slug", "item_raw"])
    write_csv("has_step_edges.csv", has_step_edges, ["recipe_id", "step_id", "order"])
    write_csv("uses_ingredient_edges.csv", uses_ingredient_edges, ["recipe_id", "ingredient_slug", "qty", "unit", "note"])

    print(f"\n=== Summary ===")
    print(f"Books: {len(books_seen)}")
    print(f"Recipes: {total_recipes:,}")
    print(f"Steps: {total_steps:,}")
    print(f"Unique ingredient slugs: {len(unique_ingredient_slugs):,}")
    print(f"USES_INGREDIENT edges: {total_uses:,}")

if __name__ == "__main__":
    main()
