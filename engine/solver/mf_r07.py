"""MF-R07 Griffith_Fracture — brittle fracture stress.

Formula:
    sigma_f = sqrt(2 · E · gamma_s / (pi · a))

References:
    - Griffith brittle fracture criterion.

Inputs:
    E [Pa], gamma_s [J/m²], a [m] crack half-length.

Assumptions:
    - brittle linear-elastic fracture
    - crack half-length a is the dominant flaw size
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds


TOOL_ID = 'MF-R07'
TOOL_CANONICAL_NAME = 'Griffith_Fracture'
CITATIONS = [
    'Bourne, Food Texture and Viscosity Ch.3',
]



@validate_bounds("MF-R07")
def solve(params: dict) -> dict:
    """Compute Griffith fracture stress in Pa."""
    val = Validator()
    assumptions = [
        "brittle linear-elastic material",
        "a is crack half-length",
    ]

    young = params.get("E")
    gamma_s = params.get("gamma_s")
    crack = params.get("a")

    val.require_positive("E", young)
    val.require_positive("gamma_s", gamma_s)
    val.require_positive("a", crack)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (young, gamma_s, crack))
        and all(math.isfinite(float(x)) for x in (young, gamma_s, crack))
        and young > 0.0 and gamma_s > 0.0 and crack > 0.0
    ):
        value = math.sqrt(2.0 * float(young) * float(gamma_s) / (math.pi * float(crack)))
        if crack < 1e-5:
            assumptions.append("small crack length produces high fracture stress")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="Pa",
        symbol="sigma_f",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"E": young, "gamma_s": gamma_s, "a": crack},
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if value is not None else float("nan"),
            unit="Pa",
            symbol="sigma_f",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
