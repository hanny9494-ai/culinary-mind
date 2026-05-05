"""MF-M04 Henderson_Hasselbalch — buffer pH relation.

Formula:
    pH = pKa + log10([A-] / [HA])

References:
    - Henderson-Hasselbalch equation; pure algebra per D65.

Inputs:
    pKa, A_minus_conc, HA_conc.

Assumptions:
    - activities are approximated by concentrations
    - acid/base pair is monoprotic for the selected pKa
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds


TOOL_ID = 'MF-M04'
TOOL_CANONICAL_NAME = 'Henderson_Hasselbalch'
CITATIONS = [
    'Fennema, Food Chemistry Ch.2',
    'Belitz et al., Food Chemistry',
]



@validate_bounds("MF-M04")
def solve(params: dict) -> dict:
    """Compute buffer pH."""
    val = Validator()
    assumptions: list[str] = [
        "activities approximated by concentrations",
        "selected pKa corresponds to this conjugate acid/base pair",
    ]

    pka = params.get("pKa")
    a_minus = params.get("A_minus_conc", params.get("A_minus"))
    ha = params.get("HA_conc", params.get("HA"))

    val.require_finite("pKa", pka)
    val.require_positive("A_minus_conc", a_minus)
    val.require_positive("HA_conc", ha)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (pka, a_minus, ha))
        and all(math.isfinite(float(x)) for x in (pka, a_minus, ha))
        and a_minus > 0.0 and ha > 0.0
    ):
        ratio = float(a_minus) / float(ha)
        value = float(pka) + math.log10(ratio)
        if math.isclose(ratio, 1.0, rel_tol=1e-12, abs_tol=1e-12):
            assumptions.append("[A-] = [HA] → pH = pKa")
        elif ratio < 0.1 or ratio > 10.0:
            assumptions.append("A-/HA outside central buffer range; pH estimate is extrapolated")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="pH",
        symbol="pH",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"pKa": pka, "A_minus_conc": a_minus, "HA_conc": ha},
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if value is not None else float("nan"),
            unit="pH",
            symbol="pH",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
