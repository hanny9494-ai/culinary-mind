"""MF-T05 Plank_Freezing — freezing time by Plank's equation.

Formula:
    t_f = (rho · L · d) / (T_f - T_inf) · (P/h + R · d/k)

References:
    - Plank freezing-time model as used in food engineering texts.

Inputs:
    rho [kg/m³], L or L_f [J/kg], d or a [m], T_f [°C], T_inf or T_m [°C],
    h [W/(m² K)], k [W/(m K)], optional geometry factors P and R.

Assumptions:
    - uniform initial freezing point
    - constant thermal properties
    - slab defaults P=1/2 and R=1/8 when geometry factors are omitted
"""

from __future__ import annotations

from typing import Any

from ._common import Validator, build_result


def solve(params: dict) -> dict:
    """Estimate freezing time in seconds."""
    val = Validator()
    assumptions: list[str] = [
        "Plank quasi-steady freezing front",
        "constant rho, latent heat, h, and k",
    ]

    rho = params.get("rho")
    latent = params.get("L", params.get("L_f"))
    d = params.get("d", params.get("a"))
    t_f = params.get("T_f")
    t_inf = params.get("T_inf", params.get("T_m"))
    h = params.get("h")
    k = params.get("k")
    p_factor = params.get("P", 0.5)
    r_factor = params.get("R", params.get("R_c", 0.125))

    if "P" not in params:
        assumptions.append("P omitted → slab default P=1/2")
    if "R" not in params and "R_c" not in params:
        assumptions.append("R omitted → slab default R=1/8")

    val.require_positive("rho", rho)
    val.require_positive("L", latent)
    val.require_positive("d", d)
    val.require_temperature_celsius("T_f", t_f)
    val.require_temperature_celsius("T_inf", t_inf)
    val.require_positive("h", h)
    val.require_positive("k", k)
    val.require_positive("P", p_factor)
    val.require_positive("R", r_factor, allow_zero=True)

    delta_t: float | None = None
    if (
        isinstance(t_f, (int, float)) and not isinstance(t_f, bool)
        and isinstance(t_inf, (int, float)) and not isinstance(t_inf, bool)
    ):
        delta_t = float(t_f) - float(t_inf)
        if delta_t <= 0.0:
            val.issues.append("T_f must be warmer than T_inf so T_f - T_inf > 0")

    value: float | None = None
    if (
        delta_t is not None and delta_t > 0.0
        and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                for x in (rho, latent, d, h, k, p_factor, r_factor))
        and rho > 0.0 and latent > 0.0 and d > 0.0 and h > 0.0 and k > 0.0
        and p_factor > 0.0 and r_factor >= 0.0
    ):
        value = (
            float(rho) * float(latent) * float(d) / delta_t
            * (float(p_factor) / float(h) + float(r_factor) * float(d) / float(k))
        )
        if r_factor == 0.0:
            assumptions.append("R = 0 → conduction resistance term omitted")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="s",
        symbol="t_f",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={
            "rho": rho, "L": latent, "d": d, "T_f": t_f, "T_inf": t_inf,
            "h": h, "k": k, "P": p_factor, "R": r_factor,
        },
    )
