#!/usr/bin/env python3
"""Apply step_phn_rules.yaml to 80K steps → generate TRIGGERS_PHN edges."""
import csv
import yaml
import re
from pathlib import Path
from collections import Counter

ROOT = Path("/Users/jeff/culinary-mind")
RULES_FILE = ROOT / "config/step_phn_rules.yaml"
STEPS_FILE = ROOT / "output/l2b/etl/steps.csv"
USES_INGR = ROOT / "output/l2b/etl/uses_ingredient_edges.csv"
OUT_EDGES = ROOT / "output/l2b/etl/triggers_phn_edges.csv"

def step_matches_rule(step, rule, recipe_ingredients):
    cond = rule["conditions"]
    action = (step.get("action") or "").lower().strip()
    if "action_in" in cond:
        if action not in [a.lower() for a in cond["action_in"]]:
            return False
    # Temp
    try:
        temp = float(step.get("temp_c", "") or "nan")
    except: temp = None
    if "temp_c_gte" in cond:
        if temp is None or temp < cond["temp_c_gte"]:
            return False
    if "temp_c_lte" in cond:
        if temp is None or temp > cond["temp_c_lte"]:
            return False
    # Duration
    try:
        dur = float(step.get("duration_min", "") or "nan")
    except: dur = None
    if "duration_min_gte" in cond:
        if dur is None or dur < cond["duration_min_gte"]:
            return False
    # Ingredient (for starch_gel rule)
    if "ingredient_contains_any" in cond:
        keywords = [k.lower() for k in cond["ingredient_contains_any"]]
        # Look up ingredients of this recipe
        recipe_id = step.get("recipe_id")
        ings = recipe_ingredients.get(recipe_id, [])
        ing_text = " ".join(ings).lower()
        if not any(k in ing_text for k in keywords):
            return False
    return True

def main():
    rules = yaml.safe_load(open(RULES_FILE))["rules"]
    print(f"Loaded {len(rules)} rules")

    # Build recipe → ingredients lookup
    recipe_ingredients = {}
    with open(USES_INGR) as f:
        for row in csv.DictReader(f):
            recipe_ingredients.setdefault(row["recipe_id"], []).append(row["ingredient_slug"])

    edges = []
    matches_per_rule = Counter()
    matched_steps = 0
    total_steps = 0

    with open(STEPS_FILE) as f:
        for step in csv.DictReader(f):
            total_steps += 1
            for rule in rules:
                if step_matches_rule(step, rule, recipe_ingredients):
                    edges.append({
                        "step_id": step["step_id"],
                        "phn_id": rule["triggers_phn"],
                        "rule_id": rule["id"],
                        "confidence": rule["confidence"],
                        "governed_by_mfs": ",".join(rule.get("governed_by_mf", [])),
                    })
                    matches_per_rule[rule["id"]] += 1
                    matched_steps += 1
                    # break  # single PHN per step; allow multi for now

    # Write edges CSV
    OUT_EDGES.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_EDGES.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["step_id", "phn_id", "rule_id", "confidence", "governed_by_mfs"])
        w.writeheader()
        for r in edges: w.writerow(r)
    tmp.rename(OUT_EDGES)

    print(f"\n=== Results ===")
    print(f"Total steps: {total_steps:,}")
    print(f"Matched steps (≥1 PHN): ~{matched_steps:,}")
    print(f"TRIGGERS_PHN edges: {len(edges):,}")
    print(f"\nTop rule matches:")
    for rule_id, n in matches_per_rule.most_common(10):
        print(f"  {rule_id}: {n:,}")
    print(f"\n✅ Wrote: {OUT_EDGES}")

if __name__ == "__main__":
    main()
