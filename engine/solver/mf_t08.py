"""MF-T08 Ohmic_Heating — Joule heating in conducting food.

Formula:
    Q_dot = sigma(T) · |E|^2

where sigma(T) ≈ sigma_25 · (1 + alpha·(T - 25))

Inputs:
    sigma_25 [S/m]:      electrical conductivity at 25°C
    alpha [1/°C]:        temperature coefficient (default 0.0)
    E_field [V/m]:       applied electric field
    T_C [°C]:            current temperature

Output:
    Q_dot (volumetric heating rate W/m³)
"""
from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds

TOOL_ID = "MF-T08"
TOOL_CANONICAL_NAME = "Ohmic_Heating"
CITATIONS = [
    "Sastry & Barach (2000) Ohmic Heating Food Processing",
    "Singh & Heldman Ch.5 — Electrical food processing",
]


@validate_bounds("MF-T08")
def solve(params: dict) -> dict:
    val = Validator()
    assumptions = [
        "linear T-dependence of sigma",
        "uniform |E| in element",
        "Joule heating Q = sigma·E²",
    ]
    sigma_25 = params.get("sigma_25", params.get("sigma_T", params.get("sigma")))
    alpha = params.get("alpha", 0.0)
    e_field = params.get("E_field", params.get("E"))
    t_c = params.get("T_C", params.get("T_c", 25.0))

    val.require_positive("sigma_25", sigma_25, allow_zero=True)
    val.require_finite("alpha", alpha)
    val.require_positive("E_field", e_field, allow_zero=True)
    val.require_temperature_celsius("T_C", t_c)

    q_dot = None
    if all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
           for x in (sigma_25, alpha, e_field, t_c)):
        sigma_t = float(sigma_25) * (1.0 + float(alpha) * (float(t_c) - 25.0))
        if sigma_t < 0:
            val.issues.append(f"WARN: sigma(T)={sigma_t} negative at T_C={t_c}")
            sigma_t = max(sigma_t, 0.0)
        q_dot = sigma_t * float(e_field) ** 2

    return build_result(
        value=q_dot if q_dot is not None else float("nan"),
        unit="W/m³",
        symbol="Q_dot",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"sigma_25": sigma_25, "alpha": alpha, "E_field": e_field, "T_C": t_c},
        provenance=provenance_for(tool_id=TOOL_ID, tool_canonical_name=TOOL_CANONICAL_NAME, citations=CITATIONS),
        llm_summary=llm_summary_for(
            value=q_dot if q_dot is not None else float("nan"),
            unit="W/m³", symbol="Q_dot",
            tool_canonical_name=TOOL_CANONICAL_NAME, tool_id=TOOL_ID,
        ),
    )
