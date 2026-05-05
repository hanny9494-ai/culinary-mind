"""MF-K02 D_Value — decimal reduction time at constant temperature.

Formula:
    D = -t / log10(N / N0)

References:
    - Thermal death time kinetics; pure algebra with optional fitting handled
      outside this atomic forward solver.

Inputs:
    t or time [s], N0 [CFU or matching count unit], N [same unit].

Assumptions:
    - constant treatment temperature
    - first-order log-linear inactivation
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for


TOOL_ID = 'MF-K02'
TOOL_CANONICAL_NAME = 'D_Value'
CITATIONS = [
    'Jay, Modern Food Microbiology Ch.17',
    'Toledo, Fundamentals of Food Process Engineering Ch.9',
    'van Boekel, Kinetic Modeling of Reactions in Foods Ch.13',
]



def solve(params: dict) -> dict:
    """Compute decimal reduction time D in seconds."""
    val = Validator()
    assumptions: list[str] = [
        "constant temperature",
        "log-linear first-order survivor curve",
    ]

    time_s = params.get("t", params.get("time"))
    n0 = params.get("N0")
    n = params.get("N")

    val.require_positive("t", time_s)
    val.require_positive("N0", n0)
    val.require_positive("N", n)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (time_s, n0, n))
        and time_s > 0.0 and n0 > 0.0 and n > 0.0
    ):
        if n >= n0:
            val.issues.append("N must be less than N0 for thermal inactivation")
        else:
            log_reduction = -math.log10(float(n) / float(n0))
            value = float(time_s) / log_reduction
            if math.isclose(log_reduction, 1.0, rel_tol=1e-12, abs_tol=1e-12):
                assumptions.append("1-log reduction → D equals treatment time")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="s",
        symbol="D",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"t": time_s, "N0": n0, "N": n},
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if value is not None else float("nan"),
            unit="s",
            symbol="D",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
