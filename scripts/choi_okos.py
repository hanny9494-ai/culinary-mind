#!/usr/bin/env python3
"""
Choi-Okos 食品热物性计算模块
============================
Calculates thermal properties of food from composition and temperature.
Source: Choi, Y., & Okos, M. R. (1986). "Effects of temperature and composition
        on the thermal properties of foods." Food Engineering and Process
        Applications, Vol.1, pp.93-101.

Usage:
    from scripts.choi_okos import choi_okos_properties

    props = choi_okos_properties(
        composition={"water": 0.7, "protein": 0.2, "fat": 0.08, "carb": 0.01, "ash": 0.01},
        T_C=20.0
    )
    # props.Cp_J_kgK, props.k_W_mK, props.rho_kg_m3, props.alpha_m2_s

CLI:
    python3 scripts/choi_okos.py --water 0.7 --protein 0.2 --fat 0.08 --carb 0.01 --ash 0.01 --T 20
"""

import os
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_k, None)

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

# ── Valid temperature range ────────────────────────────────────────────────────
T_MIN_C = -40.0   # °C
T_MAX_C = 150.0   # °C


@dataclass
class ThermalProperties:
    """Thermal properties of a food material at a given temperature."""
    T_C: float          # Temperature (°C)
    Cp_J_kgK: float     # Specific heat capacity (J/kg·K)
    k_W_mK: float       # Thermal conductivity (W/m·K)
    rho_kg_m3: float    # Density (kg/m³)
    alpha_m2_s: float   # Thermal diffusivity (m²/s)
    composition: dict   # Input composition


# ══════════════════════════════════════════════════════════════════════════════
# Pure component equations (Choi & Okos 1986)
# All T in °C, all results in SI units.
# ══════════════════════════════════════════════════════════════════════════════

def _cp_pure(T: float) -> dict[str, float]:
    """Specific heat capacity (J/kg·K) for each pure component."""
    return {
        "water":   4128.9 - 90.864e-3 * T + 547.31e-6 * T**2,
        "protein": 2008.2 + 1208.9e-3 * T - 131.29e-6 * T**2,
        "fat":     1984.2 + 1473.3e-3 * T - 4800.8e-6 * T**2,
        "carb":    1548.8 + 1962.5e-3 * T - 5939.9e-6 * T**2,
        "ash":     1092.6 + 1889.6e-3 * T - 3681.7e-6 * T**2,
    }


def _k_pure(T: float) -> dict[str, float]:
    """Thermal conductivity (W/m·K) for each pure component."""
    return {
        "water":   0.57109 + 0.0017625 * T - 6.7036e-6 * T**2,
        "protein": 0.17881 + 0.0011958 * T - 2.7178e-6 * T**2,
        "fat":     0.18071 - 0.00027604 * T - 1.7749e-7 * T**2,
        "carb":    0.20141 + 0.0013874 * T - 4.3312e-6 * T**2,
        "ash":     0.32961 + 0.0014011 * T - 2.9069e-6 * T**2,
    }


def _rho_pure(T: float) -> dict[str, float]:
    """Density (kg/m³) for each pure component."""
    return {
        "water":   997.18 + 3.1439e-3 * T - 3.7574e-3 * T**2,
        "protein": 1329.9 - 0.5184 * T,
        "fat":     925.59 - 0.41757 * T,
        "carb":    1599.1 - 0.31046 * T,
        "ash":     2423.8 - 0.28063 * T,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Mixing rules
# ══════════════════════════════════════════════════════════════════════════════

def _cp_mix(X: dict[str, float], T: float) -> float:
    """Specific heat capacity — mass fraction weighted (J/kg·K)."""
    cp = _cp_pure(T)
    return sum(X.get(comp, 0.0) * cp[comp] for comp in cp)


def _rho_mix(X: dict[str, float], T: float) -> float:
    """Density — volume fraction weighted (parallel resistors) (kg/m³)."""
    rho = _rho_pure(T)
    # rho_mix = 1 / Σ(Xi / rho_i)
    vol_sum = sum(X.get(comp, 0.0) / max(rho[comp], 1e-6) for comp in rho)
    if vol_sum <= 0:
        return 1000.0  # fallback
    return 1.0 / vol_sum


def _k_mix(X: dict[str, float], T: float) -> float:
    """Thermal conductivity — volume fraction weighted (W/m·K)."""
    k = _k_pure(T)
    rho = _rho_pure(T)

    # Compute volume fractions: Xv_i = (X_i / rho_i) / Σ(X_j / rho_j)
    vol_denominators = {
        comp: X.get(comp, 0.0) / max(rho[comp], 1e-6)
        for comp in rho
    }
    total_vol = sum(vol_denominators.values())
    if total_vol <= 0:
        return 0.5  # fallback

    Xv = {comp: vol_denominators[comp] / total_vol for comp in rho}
    return sum(Xv[comp] * k[comp] for comp in k)


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def choi_okos_properties(
    composition: dict[str, float],
    T_C: float,
) -> ThermalProperties:
    """
    Calculate thermal properties of a food material.

    Args:
        composition: Mass fractions for each component.
                     Keys: "water", "protein", "fat", "carb", "ash".
                     Values must sum to ≈ 1.0.
        T_C: Temperature in °C. Valid range: -40 to 150°C.

    Returns:
        ThermalProperties dataclass with Cp, k, rho, alpha.

    Example:
        # Beef ribeye composition
        props = choi_okos_properties(
            {"water": 0.70, "protein": 0.20, "fat": 0.08, "carb": 0.01, "ash": 0.01},
            T_C=20.0
        )
    """
    # Normalize keys to expected names
    comp_map = {
        "water": "water", "moisture": "water",
        "protein": "protein", "prot": "protein",
        "fat": "fat", "lipid": "fat",
        "carb": "carb", "carbohydrate": "carb", "cho": "carb",
        "ash": "ash", "mineral": "ash",
    }
    X: dict[str, float] = {}
    for key, val in composition.items():
        mapped = comp_map.get(key.lower(), key.lower())
        X[mapped] = X.get(mapped, 0.0) + val

    # Fill missing components with 0
    for comp in ("water", "protein", "fat", "carb", "ash"):
        X.setdefault(comp, 0.0)

    # Warn if composition doesn't sum to 1
    total = sum(X.values())
    if abs(total - 1.0) > 0.05:
        import warnings
        warnings.warn(
            f"Composition sums to {total:.3f} (expected ≈ 1.0). "
            "Results may be inaccurate.",
            stacklevel=2,
        )

    # Temperature range check
    if not T_MIN_C <= T_C <= T_MAX_C:
        import warnings
        warnings.warn(
            f"Temperature {T_C}°C is outside Choi-Okos valid range "
            f"({T_MIN_C} to {T_MAX_C}°C).",
            stacklevel=2,
        )

    Cp = _cp_mix(X, T_C)
    rho = _rho_mix(X, T_C)
    k = _k_mix(X, T_C)
    alpha = k / max(rho * Cp, 1e-9)

    return ThermalProperties(
        T_C=T_C,
        Cp_J_kgK=Cp,
        k_W_mK=k,
        rho_kg_m3=rho,
        alpha_m2_s=alpha,
        composition=composition,
    )


def generate_choi_okos_overlay_jsonl() -> list[dict]:
    """
    Generate SymPy-formatted overlay entries for Choi-Okos formulas.
    Returns list of dicts to be written as JSONL.
    """
    entries = []

    # ── Cp equations ──────────────────────────────────────────────────────────
    cp_formulas = [
        ("water",   "4128.9 - 90.864e-3*T + 547.31e-6*T**2",  "Choi-Okos Cp Water"),
        ("protein", "2008.2 + 1208.9e-3*T - 131.29e-6*T**2",  "Choi-Okos Cp Protein"),
        ("fat",     "1984.2 + 1473.3e-3*T - 4800.8e-6*T**2",  "Choi-Okos Cp Fat"),
        ("carb",    "1548.8 + 1962.5e-3*T - 5939.9e-6*T**2",  "Choi-Okos Cp Carbohydrate"),
        ("ash",     "1092.6 + 1889.6e-3*T - 3681.7e-6*T**2",  "Choi-Okos Cp Ash"),
    ]
    for comp, expr, name in cp_formulas:
        entries.append({
            "id": f"EQ_PROP_EMP_CHOIOKOS_CP_{comp.upper()}",
            "source": "Choi & Okos 1986",
            "domain": "thermal_dynamics",
            "scientific_statement": (
                f"Specific heat capacity of pure {comp} as a function of temperature "
                f"(Choi-Okos 1986, -40°C to 150°C)"
            ),
            "boundary_conditions": ["T in range -40°C to 150°C", f"pure {comp} component"],
            "citation_quote": f"Cp_{comp} = {expr} [J/kg·K], T in °C",
            "formula": {
                "has_formula": True,
                "formula_type": "scientific_law",
                "formula_name": name,
                "sympy_expression": expr,
                "symbols": {
                    "variables": [
                        {"symbol": "T", "description": "Temperature", "unit": "°C"}
                    ],
                    "parameters": [],
                    "constants": [
                        {"symbol": f"Cp_{comp}", "description": f"Specific heat of {comp}", "unit": "J/(kg·K)"}
                    ],
                },
                "applicable_range": {"T": {"min": -40, "max": 150, "unit": "°C"}},
                "formula_source": "direct_from_text",
            },
        })

    # ── k equations ───────────────────────────────────────────────────────────
    k_formulas = [
        ("water",   "0.57109 + 0.0017625*T - 6.7036e-6*T**2",  "Choi-Okos k Water"),
        ("protein", "0.17881 + 0.0011958*T - 2.7178e-6*T**2",  "Choi-Okos k Protein"),
        ("fat",     "0.18071 - 0.00027604*T - 1.7749e-7*T**2", "Choi-Okos k Fat"),
        ("carb",    "0.20141 + 0.0013874*T - 4.3312e-6*T**2",  "Choi-Okos k Carbohydrate"),
        ("ash",     "0.32961 + 0.0014011*T - 2.9069e-6*T**2",  "Choi-Okos k Ash"),
    ]
    for comp, expr, name in k_formulas:
        entries.append({
            "id": f"EQ_PROP_EMP_CHOIOKOS_K_{comp.upper()}",
            "source": "Choi & Okos 1986",
            "domain": "thermal_dynamics",
            "scientific_statement": (
                f"Thermal conductivity of pure {comp} as a function of temperature "
                f"(Choi-Okos 1986, -40°C to 150°C)"
            ),
            "boundary_conditions": ["T in range -40°C to 150°C", f"pure {comp} component"],
            "citation_quote": f"k_{comp} = {expr} [W/m·K], T in °C",
            "formula": {
                "has_formula": True,
                "formula_type": "scientific_law",
                "formula_name": name,
                "sympy_expression": expr,
                "symbols": {
                    "variables": [
                        {"symbol": "T", "description": "Temperature", "unit": "°C"}
                    ],
                    "parameters": [],
                    "constants": [
                        {"symbol": f"k_{comp}", "description": f"Thermal conductivity of {comp}", "unit": "W/(m·K)"}
                    ],
                },
                "applicable_range": {"T": {"min": -40, "max": 150, "unit": "°C"}},
                "formula_source": "direct_from_text",
            },
        })

    # ── rho equations ─────────────────────────────────────────────────────────
    rho_formulas = [
        ("water",   "997.18 + 3.1439e-3*T - 3.7574e-3*T**2", "Choi-Okos rho Water"),
        ("protein", "1329.9 - 0.5184*T",                      "Choi-Okos rho Protein"),
        ("fat",     "925.59 - 0.41757*T",                     "Choi-Okos rho Fat"),
        ("carb",    "1599.1 - 0.31046*T",                     "Choi-Okos rho Carbohydrate"),
        ("ash",     "2423.8 - 0.28063*T",                     "Choi-Okos rho Ash"),
    ]
    for comp, expr, name in rho_formulas:
        entries.append({
            "id": f"EQ_PROP_EMP_CHOIOKOS_RHO_{comp.upper()}",
            "source": "Choi & Okos 1986",
            "domain": "thermal_dynamics",
            "scientific_statement": (
                f"Density of pure {comp} as a function of temperature "
                f"(Choi-Okos 1986, -40°C to 150°C)"
            ),
            "boundary_conditions": ["T in range -40°C to 150°C", f"pure {comp} component"],
            "citation_quote": f"rho_{comp} = {expr} [kg/m³], T in °C",
            "formula": {
                "has_formula": True,
                "formula_type": "scientific_law",
                "formula_name": name,
                "sympy_expression": expr,
                "symbols": {
                    "variables": [
                        {"symbol": "T", "description": "Temperature", "unit": "°C"}
                    ],
                    "parameters": [],
                    "constants": [
                        {"symbol": f"rho_{comp}", "description": f"Density of {comp}", "unit": "kg/m³"}
                    ],
                },
                "applicable_range": {"T": {"min": -40, "max": 150, "unit": "°C"}},
                "formula_source": "direct_from_text",
            },
        })

    # ── Mixing rule: Cp (mass fraction weighted) ──────────────────────────────
    entries.append({
        "id": "EQ_PROP_EMP_CHOIOKOS_CP_MIX",
        "source": "Choi & Okos 1986",
        "domain": "thermal_dynamics",
        "scientific_statement": (
            "Specific heat of food mixture by mass-fraction weighting of pure components (Choi-Okos 1986)"
        ),
        "boundary_conditions": ["mass fractions sum to 1.0", "T in range -40°C to 150°C"],
        "citation_quote": "Cp_mix = Xw*Cp_water + Xp*Cp_protein + Xf*Cp_fat + Xc*Cp_carb + Xa*Cp_ash",
        "formula": {
            "has_formula": True,
            "formula_type": "empirical_rule",
            "formula_name": "Choi-Okos Cp Mixture (Mass-Weighted)",
            "sympy_expression": "Xw*Cp_water + Xp*Cp_protein + Xf*Cp_fat + Xc*Cp_carb + Xa*Cp_ash",
            "symbols": {
                "variables": [
                    {"symbol": "Cp_water",   "description": "Cp of water component",       "unit": "J/(kg·K)"},
                    {"symbol": "Cp_protein", "description": "Cp of protein component",     "unit": "J/(kg·K)"},
                    {"symbol": "Cp_fat",     "description": "Cp of fat component",         "unit": "J/(kg·K)"},
                    {"symbol": "Cp_carb",    "description": "Cp of carbohydrate component","unit": "J/(kg·K)"},
                    {"symbol": "Cp_ash",     "description": "Cp of ash component",         "unit": "J/(kg·K)"},
                ],
                "parameters": [
                    {"symbol": "Xw", "description": "Mass fraction of water",       "unit": "dimensionless"},
                    {"symbol": "Xp", "description": "Mass fraction of protein",     "unit": "dimensionless"},
                    {"symbol": "Xf", "description": "Mass fraction of fat",         "unit": "dimensionless"},
                    {"symbol": "Xc", "description": "Mass fraction of carbohydrate","unit": "dimensionless"},
                    {"symbol": "Xa", "description": "Mass fraction of ash",         "unit": "dimensionless"},
                ],
                "constants": [],
            },
            "applicable_range": {"T": {"min": -40, "max": 150, "unit": "°C"}},
            "formula_source": "direct_from_text",
        },
    })

    # ── Mixing rule: rho (volume fraction parallel) ───────────────────────────
    entries.append({
        "id": "EQ_PROP_EMP_CHOIOKOS_RHO_MIX",
        "source": "Choi & Okos 1986",
        "domain": "thermal_dynamics",
        "scientific_statement": (
            "Density of food mixture by inverse volume fraction (parallel model) (Choi-Okos 1986)"
        ),
        "boundary_conditions": ["mass fractions sum to 1.0", "T in range -40°C to 150°C"],
        "citation_quote": "1/rho_mix = Xw/rho_water + Xp/rho_protein + Xf/rho_fat + Xc/rho_carb + Xa/rho_ash",
        "formula": {
            "has_formula": True,
            "formula_type": "empirical_rule",
            "formula_name": "Choi-Okos Density Mixture (Volume-Weighted)",
            "sympy_expression": "1 / (Xw/rho_water + Xp/rho_protein + Xf/rho_fat + Xc/rho_carb + Xa/rho_ash)",
            "symbols": {
                "variables": [
                    {"symbol": "rho_water",   "description": "Density of water component",   "unit": "kg/m³"},
                    {"symbol": "rho_protein", "description": "Density of protein component", "unit": "kg/m³"},
                    {"symbol": "rho_fat",     "description": "Density of fat component",     "unit": "kg/m³"},
                    {"symbol": "rho_carb",    "description": "Density of carbohydrate",      "unit": "kg/m³"},
                    {"symbol": "rho_ash",     "description": "Density of ash component",     "unit": "kg/m³"},
                ],
                "parameters": [
                    {"symbol": "Xw", "description": "Mass fraction of water",       "unit": "dimensionless"},
                    {"symbol": "Xp", "description": "Mass fraction of protein",     "unit": "dimensionless"},
                    {"symbol": "Xf", "description": "Mass fraction of fat",         "unit": "dimensionless"},
                    {"symbol": "Xc", "description": "Mass fraction of carbohydrate","unit": "dimensionless"},
                    {"symbol": "Xa", "description": "Mass fraction of ash",         "unit": "dimensionless"},
                ],
                "constants": [],
            },
            "formula_source": "direct_from_text",
        },
    })

    # ── Thermal diffusivity ───────────────────────────────────────────────────
    entries.append({
        "id": "EQ_THERM_LAW_THERMAL_DIFFUSIVITY",
        "source": "Fundamental heat transfer",
        "domain": "thermal_dynamics",
        "scientific_statement": "Thermal diffusivity from conductivity, density, and specific heat capacity",
        "boundary_conditions": [],
        "citation_quote": "alpha = k / (rho * Cp)",
        "formula": {
            "has_formula": True,
            "formula_type": "scientific_law",
            "formula_name": "Thermal Diffusivity Definition",
            "sympy_expression": "k / (rho * Cp)",
            "symbols": {
                "variables": [
                    {"symbol": "alpha", "description": "Thermal diffusivity", "unit": "m²/s"},
                    {"symbol": "k",     "description": "Thermal conductivity", "unit": "W/(m·K)"},
                    {"symbol": "rho",   "description": "Density",             "unit": "kg/m³"},
                    {"symbol": "Cp",    "description": "Specific heat capacity","unit": "J/(kg·K)"},
                ],
                "parameters": [],
                "constants": [],
            },
            "formula_source": "direct_from_text",
        },
    })

    return entries


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Choi-Okos 食品热物性计算"
    )
    parser.add_argument("--water",   type=float, default=0.70, help="Water mass fraction")
    parser.add_argument("--protein", type=float, default=0.20, help="Protein mass fraction")
    parser.add_argument("--fat",     type=float, default=0.08, help="Fat mass fraction")
    parser.add_argument("--carb",    type=float, default=0.01, help="Carbohydrate mass fraction")
    parser.add_argument("--ash",     type=float, default=0.01, help="Ash mass fraction")
    parser.add_argument("--T",       type=float, default=20.0, help="Temperature (°C)")
    parser.add_argument(
        "--generate-overlay",
        action="store_true",
        help="Write Choi-Okos SymPy formulas to output/l0_computable/choi_okos_formulas.jsonl",
    )
    args = parser.parse_args()

    if args.generate_overlay:
        out_path = Path(__file__).resolve().parents[1] / "output" / "l0_computable" / "choi_okos_formulas.jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        entries = generate_choi_okos_overlay_jsonl()
        with open(out_path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"Written {len(entries)} Choi-Okos formula entries → {out_path}")
        return

    comp = {
        "water":   args.water,
        "protein": args.protein,
        "fat":     args.fat,
        "carb":    args.carb,
        "ash":     args.ash,
    }
    props = choi_okos_properties(composition=comp, T_C=args.T)

    print(f"\n{'='*55}")
    print(f"  Choi-Okos Thermal Properties @ T={args.T}°C")
    print(f"{'='*55}")
    print(f"  Composition: water={args.water:.3f} protein={args.protein:.3f} "
          f"fat={args.fat:.3f} carb={args.carb:.3f} ash={args.ash:.3f}")
    print(f"  Sum = {sum(comp.values()):.3f}")
    print(f"{'─'*55}")
    print(f"  Cp  = {props.Cp_J_kgK:>9.1f}  J/(kg·K)  [water: ~4200, meat: ~3400-3700]")
    print(f"  k   = {props.k_W_mK:>9.5f}  W/(m·K)   [meat: ~0.4-0.5]")
    print(f"  ρ   = {props.rho_kg_m3:>9.1f}  kg/m³     [meat: ~1050-1100]")
    print(f"  α   = {props.alpha_m2_s:>9.2e}  m²/s      [meat: ~1.3e-7]")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
