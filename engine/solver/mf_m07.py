"""MF-M07 Solubility_Partition — octanol-water partition coefficient.

Formula:
    K_partition = c_oil / c_water = 10^logP

Inputs:
    logP [-]:           octanol-water partition log10
    S_water [mol/L]:    water solubility (optional, advisory)
    T_C [°C]:           current temperature (advisory)

Output:
    K_partition (oil/water concentration ratio, dimensionless)

References:
    - Sangster (1997) Octanol-Water Partition Coefficients
    - Bell & Labuza, Moisture sorption (food applications of logP)
"""
from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds

TOOL_ID = "MF-M07"
TOOL_CANONICAL_NAME = "Solubility_Partition"
CITATIONS = [
    "Sangster (1997) Octanol-Water Partition Coefficients of Simple Organic Compounds",
    "Hansch & Leo (1995) Exploring QSAR — Fundamentals & Applications",
]


@validate_bounds("MF-M07")
def solve(params: dict) -> dict:
    val = Validator()
    assumptions = ["log10 base; K_partition > 1 (logP > 0) implies oil preference (hydrophobic)"]
    logp = params.get("logP", params.get("log_p"))
    s_water = params.get("S_water")
    t_c = params.get("T_C", params.get("T_c"))

    val.require_finite("logP", logp)
    if s_water is not None:
        val.require_positive("S_water", s_water)
    if t_c is not None:
        val.require_temperature_celsius("T_C", t_c)

    k_part = None
    if isinstance(logp, (int, float)) and not isinstance(logp, bool) and math.isfinite(logp):
        # Clamp huge logP to avoid overflow
        if logp > 30:
            k_part = float("inf")
            val.issues.append(f"WARN: logP={logp} → K_partition overflow; capped")
        elif logp < -30:
            k_part = 0.0
        else:
            k_part = math.pow(10.0, float(logp))

    return build_result(
        value=k_part if k_part is not None else float("nan"),
        unit="dimensionless",
        symbol="K_partition",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"logP": logp, "S_water": s_water, "T_C": t_c},
        provenance=provenance_for(tool_id=TOOL_ID, tool_canonical_name=TOOL_CANONICAL_NAME, citations=CITATIONS),
        llm_summary=llm_summary_for(
            value=k_part if k_part is not None else float("nan"),
            unit="dimensionless", symbol="K_partition",
            tool_canonical_name=TOOL_CANONICAL_NAME, tool_id=TOOL_ID,
        ),
    )
