"""MF-M06 Latent_Heat — vaporization latent heat.

Formula:
    L = h_vapor(T) - h_liquid(T)

References:
    - CoolProp PropsSI saturated-vapor/liquid enthalpy difference.
    - Watson water correlation fallback when CoolProp is unavailable.

Inputs:
    substance (default Water), T_C [°C].

Assumptions:
    - saturated liquid-vapor phase change
    - output is mass-specific latent heat
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result

try:
    from CoolProp.CoolProp import PropsSI
except ImportError:  # pragma: no cover
    PropsSI = None


def _water_watson(t_c: float) -> float:
    t_k = t_c + 273.15
    t_crit = 647.096
    t_boil = 373.15
    h_boil = 2256470.0
    return h_boil * ((1.0 - t_k / t_crit) / (1.0 - t_boil / t_crit)) ** 0.38


def solve(params: dict) -> dict:
    """Compute latent heat of vaporization in J/kg."""
    val = Validator()
    assumptions: list[str] = ["saturated liquid-vapor transition"]

    substance = params.get("substance", "Water")
    t_c = params.get("T_C", params.get("T_c"))

    if not isinstance(substance, str) or not substance:
        val.issues.append("substance must be a non-empty string")
    val.require_temperature_celsius("T_C", t_c)

    value: float | None = None
    if isinstance(t_c, (int, float)) and not isinstance(t_c, bool) and math.isfinite(t_c):
        t_k = float(t_c) + 273.15
        if PropsSI is not None and isinstance(substance, str) and substance:
            try:
                h_v = float(PropsSI("H", "T", t_k, "Q", 1, substance))
                h_l = float(PropsSI("H", "T", t_k, "Q", 0, substance))
                value = h_v - h_l
                assumptions.append("CoolProp saturated enthalpy difference")
            except Exception as exc:
                assumptions.append(f"CoolProp latent heat unavailable for {substance}: {exc}")
        if value is None and isinstance(substance, str) and substance.lower() == "water":
            if t_k >= 647.096:
                val.issues.append("water latent heat is undefined at/above the critical point")
            else:
                value = _water_watson(float(t_c))
                assumptions.append("Watson water fallback correlation")
        if value is None and isinstance(substance, str) and substance \
                and substance.lower() != "water":
            val.issues.append(
                f"latent heat unavailable for substance={substance!r}: "
                "CoolProp required for non-water substances; install CoolProp or restrict to water"
            )

    return build_result(
        value=value if value is not None else float("nan"),
        unit="J/kg",
        symbol="L",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"substance": substance, "T_C": t_c},
    )
