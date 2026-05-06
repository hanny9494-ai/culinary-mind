"""MF-R04 Gordon_Taylor — glass-transition temperature of a binary mixture.

Formula:
    Tg_mix = (w1 · Tg1 + k · w2 · Tg2) / (w1 + k · w2)

References:
    - Gordon-Taylor glass-transition mixing rule; pure algebra per D65.

Inputs:
    w1, w2, Tg1, Tg2, k.

Assumptions:
    - binary mixture
    - Tg inputs use a consistent temperature scale (K or °C)
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds


TOOL_ID = 'MF-R04'
TOOL_CANONICAL_NAME = 'Gordon_Taylor'
CITATIONS = [
    'Rao, Engineering Properties of Foods Ch.3',
    'Handbook of Food Engineering Ch.4',
    'Belitz et al., Food Chemistry',
]



@validate_bounds("MF-R04")
def solve(params: dict) -> dict:
    """Compute mixture glass-transition temperature."""
    val = Validator()
    assumptions: list[str] = [
        "binary Gordon-Taylor mixture",
        "Tg1/Tg2 share the same temperature scale",
    ]

    w1 = params.get("w1")
    w2 = params.get("w2")
    tg1 = params.get("Tg1")
    tg2 = params.get("Tg2")
    k_gt = params.get("k")

    val.require_positive("w1", w1, allow_zero=True)
    val.require_positive("w2", w2, allow_zero=True)
    val.require_temperature_celsius("Tg1", tg1)
    val.require_temperature_celsius("Tg2", tg2)
    val.require_positive("k", k_gt)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (w1, w2, tg1, tg2, k_gt))
        and all(math.isfinite(float(x)) for x in (w1, w2, tg1, tg2, k_gt))
        and w1 >= 0.0 and w2 >= 0.0 and k_gt > 0.0
    ):
        if w1 == 0.0 and w2 == 0.0:
            val.issues.append("w1 and w2 cannot both be zero")
        else:
            denom = float(w1) + float(k_gt) * float(w2)
            value = (float(w1) * float(tg1) + float(k_gt) * float(w2) * float(tg2)) / denom
            if not math.isclose(float(w1) + float(w2), 1.0, rel_tol=1e-9, abs_tol=1e-12):
                assumptions.append("w1 + w2 != 1; Gordon-Taylor ratio is scale-invariant")
            if w1 == 0.0:
                assumptions.append("w1 = 0 → Tg_mix = Tg2")
            elif w2 == 0.0:
                assumptions.append("w2 = 0 → Tg_mix = Tg1")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="same as Tg inputs",
        symbol="Tg_mix",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"w1": w1, "w2": w2, "Tg1": tg1, "Tg2": tg2, "k": k_gt},
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if value is not None else float("nan"),
            unit="same as Tg inputs",
            symbol="Tg_mix",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
