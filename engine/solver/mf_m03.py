"""MF-M03 Antoine_Equation — saturation vapor pressure.

Formula:
    log10(P_mmHg) = A - B / (T_C + C)

References:
    - CoolProp PropsSI saturation pressure is preferred.
    - Antoine water constants are used as a fallback.

Inputs:
    substance (default Water), T_C [°C], optional Antoine A/B/C.

Assumptions:
    - saturated liquid-vapor equilibrium
    - pressure output is Pa
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result

try:
    from CoolProp.CoolProp import PropsSI
except ImportError:  # pragma: no cover
    PropsSI = None


_MMHG_TO_PA = 133.32236842105263
_WATER_ANTOINE = (8.07131, 1730.63, 233.426)


def _antoine_pressure_pa(t_c: float, a: float, b: float, c: float) -> float:
    return (10.0 ** (a - b / (t_c + c))) * _MMHG_TO_PA


def solve(params: dict) -> dict:
    """Compute saturation vapor pressure in Pa."""
    val = Validator()
    assumptions: list[str] = ["saturated vapor pressure", "pressure reported in Pa"]

    substance = params.get("substance", "Water")
    t_c = params.get("T_C", params.get("T_c"))
    a = params.get("A")
    b = params.get("B")
    c = params.get("C")

    if not isinstance(substance, str) or not substance:
        val.issues.append("substance must be a non-empty string")
    val.require_temperature_celsius("T_C", t_c)
    if (
        isinstance(substance, str) and substance.lower() == "water"
        and isinstance(t_c, (int, float)) and not isinstance(t_c, bool)
        and math.isfinite(t_c) and (t_c < 0.0 or t_c > 100.0)
    ):
        assumptions.append(
            f"T_C={t_c} C outside Antoine water validity 0-100 C; "
            "result extrapolated if Antoine fallback is used, accuracy degraded"
        )

    value: float | None = None
    if isinstance(t_c, (int, float)) and not isinstance(t_c, bool) and math.isfinite(t_c):
        if PropsSI is not None and isinstance(substance, str) and substance:
            try:
                value = float(PropsSI("P", "T", float(t_c) + 273.15, "Q", 0, substance))
                assumptions.append("CoolProp PropsSI saturation pressure")
            except Exception as exc:
                assumptions.append(f"CoolProp unavailable for {substance}: {exc}")

        if value is None:
            if a is None and b is None and c is None and substance.lower() == "water":
                a, b, c = _WATER_ANTOINE
                assumptions.append("water Antoine fallback constants")
            for name, number in (("A", a), ("B", b), ("C", c)):
                val.require_finite(name, number)
            if (
                all(isinstance(x, (int, float)) and not isinstance(x, bool)
                    for x in (a, b, c))
                and all(math.isfinite(float(x)) for x in (a, b, c))
            ):
                if math.isclose(float(t_c) + float(c), 0.0, abs_tol=1e-12):
                    val.issues.append("T_C + C must not be zero in Antoine equation")
                else:
                    value = _antoine_pressure_pa(float(t_c), float(a), float(b), float(c))

    return build_result(
        value=value if value is not None else float("nan"),
        unit="Pa",
        symbol="P_sat",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"substance": substance, "T_C": t_c, "A": a, "B": b, "C": c},
    )
