"""MF-T02-k Choi_Okos — food thermal conductivity prediction.

Formula:
    k_mix = sum(phi_i k_i(T)), where phi_i is component volume fraction.

References:
    - Choi, Y. & Okos, M.R. (1986), food component property correlations.
    - CoolProp liquid-water conductivity is used for the pure-water reference
      case when available.

Inputs:
    composition dict with mass fractions for water, protein, fat, carb,
    fiber, ash; or scalar aliases Xw, Xp, Xf, Xc, Xfiber, Xa.
    T_C in deg C.

Assumptions:
    - mass fractions describe the proximate composition
    - component properties are temperature-dependent but pressure-independent
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds


TOOL_ID = 'MF-T02-K'
TOOL_CANONICAL_NAME = 'Choi_Okos_thermal_conductivity'
CITATIONS = [
    'Singh & Heldman, Introduction to Food Engineering Ch.4',
    'Rao, Engineering Properties of Foods Ch.4',
]


try:
    from CoolProp.CoolProp import PropsSI
except ImportError:  # pragma: no cover - exercised only without dependency
    PropsSI = None


_COMPONENTS = ("water", "protein", "fat", "carb", "fiber", "ash")
_ALIASES = {
    "water": ("water", "Xw"),
    "protein": ("protein", "Xp"),
    "fat": ("fat", "Xf"),
    "carb": ("carb", "carbohydrate", "Xc"),
    "fiber": ("fiber", "Xfiber", "Xfi"),
    "ash": ("ash", "Xa"),
}


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _poly(coeffs: tuple[float, float, float], t_c: float) -> float:
    return coeffs[0] + coeffs[1] * t_c + coeffs[2] * t_c * t_c


def _choi_okos_component_props(t_c: float) -> dict[str, dict[str, float]]:
    rho = {
        "water": (997.18, 3.1439e-3, -3.7574e-3),
        "protein": (1329.9, -0.5184, 0.0),
        "fat": (925.59, -0.41757, 0.0),
        "carb": (1599.1, -0.31046, 0.0),
        "fiber": (1311.5, -0.36589, 0.0),
        "ash": (2423.8, -0.28063, 0.0),
    }
    k = {
        "water": (0.57109, 1.7625e-3, -6.7036e-6),
        "protein": (0.17881, 1.1958e-3, -2.7178e-6),
        "fat": (0.18071, -2.7604e-4, -1.7749e-7),
        "carb": (0.20141, 1.3874e-3, -4.3312e-6),
        "fiber": (0.18331, 1.2497e-3, -3.1683e-6),
        "ash": (0.32962, 1.4011e-3, -2.9069e-6),
    }
    return {
        name: {
            "rho": _poly(rho[name], t_c),
            "k": _poly(k[name], t_c),
        }
        for name in _COMPONENTS
    }


def _extract_composition(params: dict[str, Any], val: Validator,
                         assumptions: list[str]) -> dict[str, float]:
    comp = params.get("composition")
    raw: dict[str, Any] = {}
    if comp is not None:
        if not isinstance(comp, dict):
            val.issues.append("composition must be a dict of component mass fractions")
            comp = {}
        raw.update(comp)
    for name, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in params:
                raw[name] = params[alias]
                break

    if not raw:
        val.issues.append(
            "must provide composition dict or component aliases Xw/Xp/Xf/Xc/Xfiber/Xa"
        )

    fractions: dict[str, float] = {}
    for name in _COMPONENTS:
        value = raw.get(name, 0.0)
        val.require_positive(f"composition.{name}", value, allow_zero=True)
        fractions[name] = float(value) if _is_finite_number(value) else 0.0

    total = sum(fractions.values())
    if total <= 0.0:
        val.issues.append("composition mass fractions must sum to a positive value")
        return fractions
    if not math.isclose(total, 1.0, rel_tol=1e-6, abs_tol=1e-9):
        assumptions.append(f"normalized composition mass fractions from total={total:.6g}")
        fractions = {name: value / total for name, value in fractions.items()}
    return fractions


def _pure_water_coolprop(t_c: float) -> float | None:
    if PropsSI is None or not (0.0 <= t_c <= 95.0):
        return None
    try:
        return float(PropsSI("L", "T", t_c + 273.15, "P", 101325.0, "Water"))
    except Exception:
        return None


@validate_bounds("MF-T02", output_variant="mf_t02_k")
def solve(params: dict) -> dict:
    """Predict thermal conductivity k for a food composition at T_C."""
    val = Validator()
    assumptions: list[str] = [
        "mass-fraction composition",
        "Choi-Okos component correlations",
        "pressure effects neglected",
    ]

    t_c = params.get("T_C", params.get("T_c"))
    val.require_temperature_celsius("T_C", t_c)
    if _is_finite_number(t_c):
        val.require_in_range("T_C", t_c, -40.0, 150.0,
                             hint="Choi-Okos food-property correlation range")

    fractions = _extract_composition(params, val, assumptions)

    value: float | None = None
    if _is_finite_number(t_c) and float(t_c) >= -273.15 and sum(fractions.values()) > 0.0 \
            and not any(f < 0.0 for f in fractions.values()):
        if fractions.get("water", 0.0) > 1.0 - 1e-12:
            value = _pure_water_coolprop(float(t_c))
            if value is not None:
                assumptions.append("pure-water thermal conductivity from CoolProp at 101325 Pa")

        if value is None:
            props = _choi_okos_component_props(float(t_c))
            specific_volume = sum(fractions[name] / props[name]["rho"] for name in _COMPONENTS)
            volume_fractions = {
                name: (fractions[name] / props[name]["rho"]) / specific_volume
                for name in _COMPONENTS
            }
            value = sum(volume_fractions[name] * props[name]["k"] for name in _COMPONENTS)

    return build_result(
        value=value if value is not None else float("nan"),
        unit="W/(m·K)",
        symbol="k",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"composition": fractions, "T_C": t_c},
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if value is not None else float("nan"),
            unit="W/(m·K)",
            symbol="k",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
