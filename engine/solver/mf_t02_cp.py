"""MF-T02-Cp Choi_Okos — food specific heat prediction.

Formula:
    Cp_mix = sum(X_i Cp_i(T)).

References:
    - Choi, Y. & Okos, M.R. (1986), food component property correlations.
    - CoolProp liquid-water heat capacity is used for the pure-water reference
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

from ._common import Validator, build_result

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


def _choi_okos_component_cp(t_c: float) -> dict[str, float]:
    cp = {
        "water": (4.1762, -9.0864e-5, 5.4731e-6),
        "protein": (2.0082, 1.2089e-3, -1.3129e-6),
        "fat": (1.9842, 1.4733e-3, -4.8008e-6),
        "carb": (1.5488, 1.9625e-3, -5.9399e-6),
        "fiber": (1.8459, 1.8306e-3, -4.6509e-6),
        "ash": (1.0926, 1.8896e-3, -3.6817e-6),
    }
    return {name: _poly(cp[name], t_c) * 1000.0 for name in _COMPONENTS}


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
        return float(PropsSI("C", "T", t_c + 273.15, "P", 101325.0, "Water"))
    except Exception:
        return None


def solve(params: dict) -> dict:
    """Predict specific heat Cp for a food composition at T_C."""
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
                assumptions.append("pure-water specific heat from CoolProp at 101325 Pa")

        if value is None:
            cp = _choi_okos_component_cp(float(t_c))
            value = sum(fractions[name] * cp[name] for name in _COMPONENTS)

    return build_result(
        value=value if value is not None else float("nan"),
        unit="J/(kg·K)",
        symbol="Cp",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"composition": fractions, "T_C": t_c},
    )
