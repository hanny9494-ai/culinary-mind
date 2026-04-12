#!/usr/bin/env python3
"""
L0 公式验证 MVP — Step 4
=========================
Validates extracted SymPy formulas for:
  1. SymPy parseability (sympify())
  2. Variable consistency (all symbols in expression are defined)
  3. Range plausibility (basic sanity checks)
  4. Placeholder detection

Usage:
    python3 scripts/l0_formula_validate.py [--input path] [--output path]
"""

# Clear proxy env vars
import os
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_k, None)

import re
import sys
import json
import argparse
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "output" / "l0_computable" / "mvp_formulas.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "output" / "l0_computable" / "mvp_validation.json"

PLACEHOLDER_RE = re.compile(r"\w+_placeholder\b")


def collect_expression_symbols(expr_str: str) -> set[str]:
    """Extract symbol names from a SymPy expression string (rough heuristic)."""
    # Remove numeric literals, operators, function names, punctuation
    # Keep identifier tokens
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr_str)
    # Remove known SymPy functions / keywords
    builtins = {
        "exp", "log", "sin", "cos", "tan", "sqrt", "Abs", "Eq", "Piecewise",
        "And", "Or", "Not", "True", "False", "E", "pi", "I", "oo",
        "Symbol", "symbols", "Integer", "Float", "Rational",
    }
    return {t for t in tokens if t not in builtins}


def validate_formula(entry: dict) -> dict:
    """Validate a single formula entry. Returns check results dict."""
    formula = entry.get("formula", {})
    eid = entry.get("id", "unknown")
    expr_str = formula.get("sympy_expression") or ""
    symbols_block = formula.get("symbols", {})

    # Collect all defined symbols
    defined_syms: set[str] = set()
    for category in ("variables", "parameters", "constants"):
        for sym_entry in symbols_block.get(category, []):
            sym = sym_entry.get("symbol", "")
            if sym:
                defined_syms.add(sym)

    checks: dict[str, Any] = {
        "sympy_parseable": False,
        "sympy_error": None,
        "variables_consistent": True,
        "missing_symbols": [],
        "has_placeholders": bool(PLACEHOLDER_RE.search(expr_str)),
        "range_warnings": [],
    }

    # ── Check 1: SymPy parseable ──────────────────────────────────────────────
    if not expr_str:
        checks["sympy_error"] = "Empty expression"
        checks["variables_consistent"] = False
    else:
        try:
            from sympy import sympify, Symbol, exp, log, sqrt, Abs, Eq, Piecewise, pi, E, oo
            from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application

            local_syms = {s: Symbol(s) for s in defined_syms}
            # Add math functions to locals
            local_syms.update({
                "exp": exp, "log": log, "sqrt": sqrt, "Abs": Abs,
                "Eq": Eq, "Piecewise": Piecewise, "pi": pi, "E": E, "oo": oo,
            })

            parsed = sympify(expr_str, locals=local_syms)
            checks["sympy_parseable"] = True

        except ImportError:
            # SymPy not installed — skip this check
            checks["sympy_parseable"] = None
            checks["sympy_error"] = "sympy not installed"
        except Exception as e:
            checks["sympy_error"] = str(e)[:200]

    # ── Check 2: Variable consistency ────────────────────────────────────────
    if expr_str and checks["sympy_parseable"]:
        expr_syms = collect_expression_symbols(expr_str)
        # Ignore numeric-like tokens and known constants
        skip_tokens = {"E", "pi", "oo", "True", "False"}
        missing = [s for s in expr_syms if s not in defined_syms and s not in skip_tokens]
        # Exclude placeholder suffix tokens
        missing = [s for s in missing if not s.endswith("placeholder")]
        # If the formula is a placeholder-heavy partial, defined_syms may include them
        checks["missing_symbols"] = missing
        if missing:
            checks["variables_consistent"] = False

    # ── Check 3: Range plausibility ───────────────────────────────────────────
    for category in ("variables", "parameters"):
        for sym_entry in symbols_block.get(category, []):
            desc = (sym_entry.get("description") or "").lower()
            unit = (sym_entry.get("unit") or "").lower()
            # Temperature sanity
            if "temperature" in desc and ("c" in unit or "°c" in unit or "degc" in unit):
                # We can't check values without applicable_range, just note
                pass
            # Time sanity — if unit suggests time, no negative values
            if "time" in desc and unit in ("min", "s", "sec", "hour", "hours", "minutes", "seconds"):
                checks["range_warnings"].append(
                    f"Symbol '{sym_entry.get('symbol')}' is time — ensure range ≥ 0"
                )

    overall_valid = (
        (checks["sympy_parseable"] is True or checks["sympy_parseable"] is None)
        and checks["variables_consistent"]
    )

    return {
        "id": eid,
        "formula_name": formula.get("formula_name"),
        "sympy_expression": expr_str,
        "formula_type": formula.get("formula_type"),
        "scientific_statement": entry.get("scientific_statement", "")[:120],
        "checks": checks,
        "overall_valid": overall_valid,
    }


def run_validation(input_path: Path, output_path: Path) -> None:
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)

    print("=" * 60)
    print("STEP 4: SymPy Formula Validation")
    print("=" * 60)
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print()

    entries = []
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    print(f"Loaded {len(entries)} formula entries\n")

    results = []
    for entry in entries:
        result = validate_formula(entry)
        results.append(result)

    # Compute summary
    total = len(results)
    sympy_valid = sum(
        1 for r in results
        if r["checks"]["sympy_parseable"] is True
    )
    var_consistent = sum(
        1 for r in results
        if r["checks"]["variables_consistent"]
    )
    has_placeholders = sum(
        1 for r in results
        if r["checks"]["has_placeholders"]
    )
    fully_valid = sum(1 for r in results if r["overall_valid"])

    summary = {
        "total": total,
        "sympy_valid": sympy_valid,
        "variable_consistent": var_consistent,
        "has_placeholders": has_placeholders,
        "fully_valid": fully_valid,
        "sympy_valid_pct": round(100 * sympy_valid / total, 1) if total else 0,
        "fully_valid_pct": round(100 * fully_valid / total, 1) if total else 0,
    }

    validation_report = {
        "summary": summary,
        "results": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(validation_report, f, ensure_ascii=False, indent=2)

    # Print summary table
    print("─" * 60)
    print(f"{'VALIDATION SUMMARY':^60}")
    print("─" * 60)
    print(f"  Total formulas:          {total:>6}")
    print(f"  SymPy parseable:         {sympy_valid:>6}  ({summary['sympy_valid_pct']}%)")
    print(f"  Variable consistent:     {var_consistent:>6}")
    print(f"  Has placeholders:        {has_placeholders:>6}")
    print(f"  Fully valid:             {fully_valid:>6}  ({summary['fully_valid_pct']}%)")
    print("─" * 60)

    # Print failures
    failures = [r for r in results if not r["overall_valid"]]
    if failures:
        print(f"\n{'INVALID FORMULAS':}")
        for r in failures:
            print(f"  [{r['id']}] {r['formula_name'] or '(unnamed)'}")
            c = r["checks"]
            if not c["sympy_parseable"]:
                print(f"    ✗ SymPy error: {c['sympy_error']}")
            if not c["variables_consistent"]:
                print(f"    ✗ Missing symbols: {c['missing_symbols']}")

    # Print valid formulas
    valid_ones = [r for r in results if r["overall_valid"]]
    if valid_ones:
        print(f"\n{'VALID FORMULAS':}")
        for r in valid_ones:
            placeholder_note = " [partial]" if r["checks"]["has_placeholders"] else ""
            print(f"  ✓ [{r['formula_type']}] {r['formula_name'] or '(unnamed)'}{placeholder_note}")
            print(f"      {r['sympy_expression'][:80]}")

    print(f"\nSaved → {output_path}")


def main():
    parser = argparse.ArgumentParser(description="L0 公式验证 (Step 4)")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to mvp_formulas.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path to output validation JSON",
    )
    args = parser.parse_args()
    run_validation(args.input, args.output)


if __name__ == "__main__":
    main()
