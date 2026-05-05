"""MF-M02 GAB_Isotherm — Guggenheim-Anderson-de Boer moisture isotherm.

Formula:
    W = W_m · C · K · a_w / ((1 - K a_w) · (1 - K a_w + C K a_w))

References:
    - GAB sorption isotherm; scipy.optimize.curve_fit is the fitting route.

Inputs:
    a_w or aw, W_m or Xm [kg water/kg dry solid], C, K.

Assumptions:
    - equilibrium water activity
    - GAB constants are fitted for the same food and temperature
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for


TOOL_ID = 'MF-M02'
TOOL_CANONICAL_NAME = 'GAB_Isotherm'
CITATIONS = [
    'Rao, Engineering Properties of Foods Ch.7',
    'Toledo, Fundamentals of Food Process Engineering Ch.12',
    'Handbook of Food Engineering Ch.11',
    'Sahin & Sumnu, Physical Properties of Foods Ch.5',
]



def solve(params: dict) -> dict:
    """Compute equilibrium moisture content W."""
    val = Validator()
    assumptions: list[str] = [
        "equilibrium sorption state",
        "GAB parameters are temperature- and product-specific",
    ]

    aw = params.get("a_w", params.get("aw"))
    w_m = params.get("W_m", params.get("Xm"))
    c = params.get("C")
    k = params.get("K")

    val.require_positive("a_w", aw, allow_zero=True)
    val.require_positive("W_m", w_m)
    val.require_positive("C", c)
    val.require_positive("K", k)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (aw, w_m, c, k))
        and all(math.isfinite(float(x)) for x in (aw, w_m, c, k))
        and aw >= 0.0 and w_m > 0.0 and c > 0.0 and k > 0.0
    ):
        if aw >= 1.0:
            val.issues.append("a_w must be < 1 for the GAB isotherm")
        elif k * aw >= 1.0:
            val.issues.append("K · a_w must be < 1 to avoid the GAB singularity")
        else:
            denom = (1.0 - float(k) * float(aw)) * (
                1.0 - float(k) * float(aw) + float(c) * float(k) * float(aw)
            )
            value = float(w_m) * float(c) * float(k) * float(aw) / denom
            if aw == 0.0:
                assumptions.append("a_w = 0 → W = 0")
            elif aw > 0.8:
                assumptions.append("high-water-activity extrapolation; verify fitted GAB range")
            if math.isclose(float(k), 1.0, rel_tol=1e-12, abs_tol=1e-12):
                assumptions.append("K = 1 → BET-like special case")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="kg water/kg dry solid",
        symbol="W",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"a_w": aw, "W_m": w_m, "C": c, "K": k},
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if value is not None else float("nan"),
            unit="kg water/kg dry solid",
            symbol="W",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
