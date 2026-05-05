"""MF-C05 Q10_Rule — temperature sensitivity of a rate.

Formula:
    Q10 = (k2/k1)^(10/(T2 - T1))

References:
    - Q10 empirical temperature coefficient; pure algebra per D65.

Inputs:
    k1, k2, T1 [°C], T2 [°C].

Assumptions:
    - same reaction or process measured at both temperatures
    - Q10 is empirical over the interval T1 to T2
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for


TOOL_ID = 'MF-C05'
TOOL_CANONICAL_NAME = 'Q10_Rule'
CITATIONS = [
    'Toledo, Fundamentals of Food Process Engineering Ch.8',
    'van Boekel, Kinetic Modeling of Reactions in Foods Ch.5',
]



def solve(params: dict) -> dict:
    """Compute Q10."""
    val = Validator()
    assumptions: list[str] = [
        "same process at both temperatures",
        "empirical interval Q10",
    ]

    k1 = params.get("k1")
    k2 = params.get("k2")
    t1 = params.get("T1")
    t2 = params.get("T2")

    val.require_positive("k1", k1)
    val.require_positive("k2", k2)
    val.require_temperature_celsius("T1", t1)
    val.require_temperature_celsius("T2", t2)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (k1, k2, t1, t2))
        and all(math.isfinite(float(x)) for x in (k1, k2, t1, t2))
        and k1 > 0.0 and k2 > 0.0
    ):
        delta_t = float(t2) - float(t1)
        if delta_t == 0.0:
            val.issues.append("T2 must differ from T1")
        else:
            value = (float(k2) / float(k1)) ** (10.0 / delta_t)
            if math.isclose(delta_t, 10.0, rel_tol=1e-12, abs_tol=1e-12):
                assumptions.append("10°C interval → Q10 = k2/k1")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="dimensionless",
        symbol="Q10",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"k1": k1, "k2": k2, "T1": t1, "T2": t2},
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if value is not None else float("nan"),
            unit="dimensionless",
            symbol="Q10",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
