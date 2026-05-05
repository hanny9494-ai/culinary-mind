"""MF-T05 Plank_Freezing — freezing time by Plank's equation.

Formula:
    t_f = (rho · L · d) / (T_f - T_inf) · (P/h + R · d/k)

References:
    - Plank freezing-time model as used in food engineering texts.

Inputs:
    rho [kg/m³], L or L_f [J/kg], d or a [m], T_f [°C], T_inf or T_m [°C],
    h [W/(m² K)], k [W/(m K)], optional geometry slab/cylinder/sphere or
    explicit geometry factors P and R.

Assumptions:
    - uniform initial freezing point
    - constant thermal properties
    - slab defaults P=1/2 and R=1/8 when geometry factors are omitted
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for


TOOL_ID = 'MF-T05'
TOOL_CANONICAL_NAME = 'Plank_Freezing'
CITATIONS = [
    'Singh & Heldman, Introduction to Food Engineering Ch.7',
    'Handbook of Food Engineering Ch.7',
]



GEOMETRY_FACTORS = {
    "slab": (0.5, 0.125),
    "cylinder": (0.25, 0.0625),
    "sphere": (0.1667, 0.04167),
}


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


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
    geometry_raw = params.get("geometry", "slab")
    geometry = geometry_raw.lower() if isinstance(geometry_raw, str) else None
    if geometry not in GEOMETRY_FACTORS:
        val.issues.append(f"geometry must be one of {list(GEOMETRY_FACTORS)}, got {geometry_raw!r}")
    effective_geometry = geometry if geometry in GEOMETRY_FACTORS else "slab"
    p_default, r_default = GEOMETRY_FACTORS[effective_geometry]
    p_factor = params.get("P", p_default)
    r_factor = params.get("R", params.get("R_c", r_default))

    if "P" not in params and "R" not in params and "R_c" not in params:
        assumptions.append(
            f"using {effective_geometry} default geometry factors P={p_default}, R={r_default}"
        )

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
    if _is_finite_number(t_f) and _is_finite_number(t_inf):
        delta_t = float(t_f) - float(t_inf)
        if delta_t <= 0.0:
            val.issues.append("T_f must be warmer than T_inf so T_f - T_inf > 0")

    value: float | None = None
    if (
        delta_t is not None and delta_t > 0.0
        and all(_is_finite_number(x) for x in (rho, latent, d, h, k, p_factor, r_factor))
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
            "h": h, "k": k, "geometry": geometry_raw, "P": p_factor, "R": r_factor,
        },
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if value is not None else float("nan"),
            unit="s",
            symbol="t_f",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
