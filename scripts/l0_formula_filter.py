#!/usr/bin/env python3
"""
L0 Formula Filter — Task 2
===========================
Filter mvp_formulas.jsonl (2099 entries) into:
  - empirical_rules_l2b.jsonl  (550 empirical_rule entries → L2b ParameterSet format)
  - scientific_laws_review.jsonl (29 scientific_law entries → human review list)
  - threshold_constants_discard.jsonl (1520 entries — for audit only, not used)

Usage:
    python3 scripts/l0_formula_filter.py [--dry-run] [--input PATH]

Output:
    output/l0_computable/empirical_rules_l2b.jsonl
    output/l0_computable/scientific_laws_review.jsonl
"""

# ── Clear proxy env vars (local proxy 127.0.0.1:7890 must be bypassed) ──
import os
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_k, None)

import json
import argparse
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "output" / "l0_computable"
DEFAULT_INPUT = OUTPUT_DIR / "mvp_formulas.jsonl"
EMPIRICAL_OUTPUT = OUTPUT_DIR / "empirical_rules_l2b.jsonl"
SCIENTIFIC_OUTPUT = OUTPUT_DIR / "scientific_laws_review.jsonl"
DISCARD_OUTPUT = OUTPUT_DIR / "threshold_constants_discard.jsonl"


# ── Domain inference helpers ─────────────────────────────────────────────────
DOMAIN_KEYWORDS = {
    "protein_science":      ["protein", "myosin", "actin", "collagen", "denaturation", "gelatin"],
    "carbohydrate":         ["starch", "gelatinization", "gluten", "retrogradation", "sugar", "caramel"],
    "lipid_science":        ["fat", "oil", "lipid", "frying", "smoke", "oxidation", "saturated"],
    "fermentation":         ["ferment", "yeast", "bacteria", "lactic", "acetic", "pH"],
    "food_safety":          ["bacteria", "pathogen", "salmonella", "D-value", "z-value", "F0"],
    "water_activity":       ["water activity", "aw", "moisture", "hygroscopic", "sorption"],
    "enzyme":               ["enzyme", "michaelis", "Km", "Vmax", "protease", "amylase"],
    "color_pigment":        ["chlorophyll", "anthocyanin", "carotenoid", "browning", "pigment"],
    "maillard_caramelization": ["maillard", "browning", "caramelization", "reducing sugar", "amino"],
    "thermal_dynamics":     ["heat", "temperature", "thermal", "conduction", "conductivity", "Fourier"],
    "mass_transfer":        ["diffusion", "Fick", "concentration", "moisture migration"],
    "texture_rheology":     ["viscosity", "gel", "texture", "rheology", "elasticity", "firmness"],
    "taste_perception":     ["taste", "umami", "saltiness", "sweetness", "bitterness"],
    "aroma_volatiles":      ["aroma", "volatile", "flavor", "odor", "Henry"],
    "salt_acid_chemistry":  ["pH", "acid", "base", "buffer", "salt", "brine"],
    "oxidation_reduction":  ["oxidation", "antioxidant", "rancidity", "browning", "peroxide"],
}


def infer_domain(entry: dict) -> str:
    """Infer domain from entry's existing domain field or from text."""
    domain = entry.get("domain") or ""
    if domain and domain != "unknown":
        return domain
    # Fallback: scan text
    text = (entry.get("scientific_statement", "") + " " + entry.get("citation_quote", "")).lower()
    for dom, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text:
                return dom
    return "unknown"


def infer_category(entry: dict, domain: str) -> str:
    """Infer culinary category from text."""
    text = (entry.get("scientific_statement", "") + " " + entry.get("citation_quote", "")).lower()

    CATEGORY_MAP = {
        "bread": ["bread", "flour", "gluten", "dough", "yeast", "baking"],
        "meat": ["beef", "pork", "chicken", "myosin", "collagen", "denaturation"],
        "frying": ["fry", "oil", "crispy", "crust", "smoke point"],
        "sauce": ["sauce", "thicken", "roux", "viscosity", "starch"],
        "fermentation": ["ferment", "pickle", "kimchi", "sauerkraut"],
        "dairy": ["milk", "cheese", "cream", "casein", "whey"],
        "egg": ["egg", "albumen", "yolk", "emulsify", "lecithin"],
        "sugar": ["sugar", "caramel", "candy", "syrup", "crystallization"],
        "fish": ["fish", "seafood", "salmon", "tuna", "shrimp"],
        "vegetable": ["vegetable", "starch", "cellulose", "pectin", "chlorophyll"],
        "spice": ["spice", "pepper", "capsaicin", "aroma", "volatile"],
        "general": [],
    }

    for cat, keywords in CATEGORY_MAP.items():
        if cat == "general":
            continue
        for kw in keywords:
            if kw in text:
                return cat
    return "general"


def extract_parameters(formula: dict) -> dict:
    """Extract parameter dict from formula JSON."""
    params = {}
    symbols = formula.get("symbols", {})

    # Collect all constants with values
    for const in symbols.get("constants", []):
        sym = const.get("symbol", "")
        val = const.get("value")
        if sym and val is not None:
            params[sym] = val

    # Collect parameters with units (no values typically)
    for param in symbols.get("parameters", []):
        sym = param.get("symbol", "")
        unit = param.get("unit", "")
        if sym:
            params[sym] = f"<{unit}>" if unit else "<required>"

    return params


def infer_related_formula(formula: dict) -> Optional[str]:
    """Try to infer the related MotherFormula from formula_name or text."""
    name = (formula.get("formula_name") or "").lower()
    sympy = (formula.get("sympy_expression") or "").lower()

    FORMULA_HINTS = {
        "MF_001": ["fourier", "heat conduction", "∂t/∂t", "alpha"],
        "MF_008": ["arrhenius", "activation energy", "exp(-ea"],
        "MF_009": ["d-value", "z-value", "f0", "decimal reduction"],
        "MF_010": ["michaelis", "km", "vmax", "enzyme kinetic"],
        "MF_014": ["fick", "diffusion", "d_eff"],
        "MF_015": ["gab", "isotherm", "water activity"],
        "MF_019": ["antoine", "vapor pressure"],
        "MF_020": ["power law", "ostwald", "consistency index"],
        "MF_008": ["q10", "temperature coefficient"],
    }

    combined = name + " " + sympy
    for mf_id, hints in FORMULA_HINTS.items():
        for hint in hints:
            if hint in combined:
                return mf_id
    return None


def convert_to_l2b_parameterset(entry: dict) -> dict:
    """Convert an empirical_rule entry to L2b ParameterSet format."""
    formula = entry.get("formula", {})
    domain = infer_domain(entry)
    category = infer_category(entry, domain)

    # Build rule string from formula_name + sympy_expression
    rule = formula.get("formula_name") or ""
    sympy = formula.get("sympy_expression") or ""
    if sympy and rule:
        rule = f"{rule}: {sympy}"
    elif sympy:
        rule = sympy
    elif not rule:
        rule = (entry.get("scientific_statement") or "")[:120]

    params = extract_parameters(formula)
    related_mf = infer_related_formula(formula)

    # Source information
    source_book = entry.get("source_book", "unknown")
    if source_book.startswith("stage4_"):
        source_book = source_book[7:]  # strip stage4_ prefix

    return {
        "type": "empirical_rule",
        "domain": domain,
        "category": category,
        "rule": rule,
        "parameters": params,
        "source": {
            "book": source_book,
            "scientific_statement": entry.get("scientific_statement", ""),
            "citation_quote": entry.get("citation_quote", ""),
            "source_chunk_id": entry.get("source_chunk_id", ""),
        },
        "related_formula": related_mf,
        "confidence": formula.get("confidence", 0.75),
        "original_id": entry.get("id", ""),
        "reasoning": formula.get("reasoning", ""),
    }


def convert_to_review_entry(entry: dict) -> dict:
    """Convert a scientific_law entry to review list format."""
    formula = entry.get("formula", {})
    domain = infer_domain(entry)

    source_book = entry.get("source_book", "unknown")
    if source_book.startswith("stage4_"):
        source_book = source_book[7:]

    related_mf = infer_related_formula(formula)

    return {
        "review_status": "pending",
        "recommended_action": "evaluate",  # to be filled by human: approve | reject | merge_to_mf
        "domain": domain,
        "formula_name": formula.get("formula_name"),
        "sympy_expression": formula.get("sympy_expression"),
        "related_mother_formula": related_mf,
        "symbols": formula.get("symbols", {}),
        "applicable_range": formula.get("applicable_range", {}),
        "source": {
            "book": source_book,
            "scientific_statement": entry.get("scientific_statement", ""),
            "citation_quote": entry.get("citation_quote", ""),
            "source_chunk_id": entry.get("source_chunk_id", ""),
        },
        "confidence": formula.get("confidence", 0.80),
        "reasoning": formula.get("reasoning", ""),
        "original_id": entry.get("id", ""),
        "reviewer_notes": "",  # human fills this
    }


def run_filter(input_path: Path, dry_run: bool = False) -> None:
    """Main filter routine."""
    print("=" * 60)
    print("L0 Formula Filter")
    print("=" * 60)
    print(f"Input:  {input_path}")
    print(f"Output: {OUTPUT_DIR}")
    print()

    counts = {"empirical_rule": 0, "scientific_law": 0, "threshold_constant": 0, "other": 0}
    empirical_entries = []
    scientific_entries = []
    discard_entries = []

    with open(input_path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  WARNING: JSON decode error at line {line_num}: {e}")
                continue

            formula = entry.get("formula", {})
            if not formula:
                counts["other"] += 1
                continue

            formula_type = formula.get("formula_type")

            if formula_type == "empirical_rule":
                counts["empirical_rule"] += 1
                empirical_entries.append(convert_to_l2b_parameterset(entry))
            elif formula_type == "scientific_law":
                counts["scientific_law"] += 1
                scientific_entries.append(convert_to_review_entry(entry))
            elif formula_type == "threshold_constant":
                counts["threshold_constant"] += 1
                discard_entries.append({
                    "id": entry.get("id", ""),
                    "formula_type": "threshold_constant",
                    "statement": entry.get("scientific_statement", "")[:150],
                    "domain": entry.get("domain", ""),
                    "action": "discarded — already in L0 51K",
                })
            else:
                counts["other"] += 1

    print(f"Scan results:")
    print(f"  empirical_rule:      {counts['empirical_rule']:4d} → L2b ParameterSet JSONL")
    print(f"  scientific_law:      {counts['scientific_law']:4d} → Human review JSONL")
    print(f"  threshold_constant:  {counts['threshold_constant']:4d} → Discarded (already in L0)")
    print(f"  other/unknown:       {counts['other']:4d} → Skipped")
    print()

    if dry_run:
        print("[DRY RUN] No files written.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Write empirical_rules_l2b.jsonl
    with open(EMPIRICAL_OUTPUT, "w", encoding="utf-8") as f:
        for entry in empirical_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"✅ Written: {EMPIRICAL_OUTPUT} ({counts['empirical_rule']} entries)")

    # Write scientific_laws_review.jsonl
    with open(SCIENTIFIC_OUTPUT, "w", encoding="utf-8") as f:
        for entry in scientific_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"✅ Written: {SCIENTIFIC_OUTPUT} ({counts['scientific_law']} entries)")

    # Write discard log (for audit)
    with open(DISCARD_OUTPUT, "w", encoding="utf-8") as f:
        for entry in discard_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"✅ Written: {DISCARD_OUTPUT} ({counts['threshold_constant']} entries, audit log)")

    print()
    print("Summary:")
    print(f"  → {EMPIRICAL_OUTPUT.name}: {counts['empirical_rule']} L2b ParameterSets")
    print(f"  → {SCIENTIFIC_OUTPUT.name}: {counts['scientific_law']} for human review")
    print(f"  → {DISCARD_OUTPUT.name}: {counts['threshold_constant']} discarded (audit)")


def main():
    parser = argparse.ArgumentParser(description="Filter mvp_formulas.jsonl into L2b + review lists")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help=f"Input JSONL path (default: {DEFAULT_INPUT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scan and count without writing output files")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: Input file not found: {args.input}")
        raise SystemExit(1)

    run_filter(args.input, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
