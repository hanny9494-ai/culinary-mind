"""MF-K03 z_Value — temperature change for one-log D-value change.

Formula:
    z = (T2 - T1) / log10(D1 / D2)

References:
    - Thermal process microbiology z-value relation.

Inputs:
    T1, T2 [°C], D1, D2 [s or matching time unit].

Assumptions:
    - D-values follow a log-linear relation with temperature
    - T1/D1 and T2/D2 describe the same organism and medium
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for


TOOL_ID = 'MF-K03'
TOOL_CANONICAL_NAME = 'z_Value'
CITATIONS = [
    'Jay, Modern Food Microbiology Ch.17',
    'Toledo, Fundamentals of Food Process Engineering Ch.9',
    'Singh & Heldman, Introduction to Food Engineering Ch.5',
]



def solve(params: dict) -> dict:
    """Compute z in °C."""
    val = Validator()
    assumptions = [
        "same organism/medium for both D-values",
        "log-linear thermal resistance curve",
    ]

    t1 = params.get("T1")
    t2 = params.get("T2")
    d1 = params.get("D1")
    d2 = params.get("D2")

    val.require_temperature_celsius("T1", t1)
    val.require_temperature_celsius("T2", t2)
    val.require_positive("D1", d1)
    val.require_positive("D2", d2)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (t1, t2, d1, d2))
        and all(math.isfinite(float(x)) for x in (t1, t2, d1, d2))
        and d1 > 0.0 and d2 > 0.0
    ):
        delta_t = float(t2) - float(t1)
        denom = math.log10(float(d1) / float(d2))
        if delta_t == 0.0:
            val.issues.append("T2 must differ from T1")
        elif denom == 0.0:
            val.issues.append("D1 and D2 must differ to define z")
        else:
            value = delta_t / denom
            if value <= 0.0:
                val.issues.append(
                    "computed z is non-positive; D should decrease as temperature increases"
                )
            elif math.isclose(value, 10.0, rel_tol=1e-9, abs_tol=1e-9):
                assumptions.append("z ≈ 10°C, common thermal-process reference value")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="°C",
        symbol="z",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"T1": t1, "T2": t2, "D1": d1, "D2": d2},
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if value is not None else float("nan"),
            unit="°C",
            symbol="z",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
