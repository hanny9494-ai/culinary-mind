"""MF-T09 Respiration_Heat — postharvest produce respiration heat.

Formula:
    Q_resp = a · exp(b · T_C)

Inputs:
    a [W/kg]:   preexponential coefficient
    b [1/°C]:   temperature coefficient
    T_C [°C]:   storage temperature

Output:
    Q_resp (specific respiration heat, W/kg)

References:
    - ASHRAE Handbook: Refrigeration — Heat of respiration for fresh produce
    - Becker et al. (1996) Heat & mass transfer in horticultural products
"""
from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds

TOOL_ID = "MF-T09"
TOOL_CANONICAL_NAME = "Respiration_Heat"
CITATIONS = [
    "ASHRAE Handbook 2022 Refrigeration — Postharvest heat of respiration",
    "Becker, Misra & Fricke (1996) HVAC&R Research 2:4 — Fresh produce",
]


@validate_bounds("MF-T09")
def solve(params: dict) -> dict:
    val = Validator()
    assumptions = ["empirical exponential T-dependence", "single produce species"]
    a = params.get("a", params.get("a_coef"))
    b = params.get("b", params.get("b_coef"))
    t_c = params.get("T_C", params.get("T_c"))
    val.require_positive("a", a, allow_zero=True)
    val.require_finite("b", b)
    val.require_temperature_celsius("T_C", t_c)

    q_resp = None
    if all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
           for x in (a, b, t_c)) and a >= 0:
        arg = float(b) * float(t_c)
        if arg > 700.0:
            q_resp = float("inf")
            val.issues.append(f"WARN: exponent {arg} too large — capped")
        elif arg < -700.0:
            q_resp = 0.0
        else:
            q_resp = float(a) * math.exp(arg)

    return build_result(
        value=q_resp if q_resp is not None else float("nan"),
        unit="W/kg",
        symbol="Q_resp",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"a": a, "b": b, "T_C": t_c},
        provenance=provenance_for(tool_id=TOOL_ID, tool_canonical_name=TOOL_CANONICAL_NAME, citations=CITATIONS),
        llm_summary=llm_summary_for(
            value=q_resp if q_resp is not None else float("nan"),
            unit="W/kg", symbol="Q_resp",
            tool_canonical_name=TOOL_CANONICAL_NAME, tool_id=TOOL_ID,
        ),
    )
