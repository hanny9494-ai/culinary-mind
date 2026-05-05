"""MF-K05 Gompertz_Microbial — modified Gompertz growth curve.

Formula:
    log10(N/N0) = A · exp(-exp(mu_max · e/A · (lambda - t) + 1))

References:
    - Modified Gompertz microbial growth model.
    - scipy.optimize.curve_fit is the companion fitting route; this solver
      evaluates the forward model.

Inputs:
    t or time_h [h], A [log10 units], mu_max or μmax [log10/h], lambda or lag [h].

Assumptions:
    - growth is represented on a log10(N/N0) basis
    - A is the asymptotic log increase
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds


TOOL_ID = 'MF-K05'
TOOL_CANONICAL_NAME = 'Gompertz_Microbial'
CITATIONS = [
    'van Boekel, Kinetic Modeling of Reactions in Foods Ch.12',
    'Jay, Modern Food Microbiology Ch.3',
]



def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@validate_bounds("MF-K05")
def solve(params: dict) -> dict:
    """Evaluate the modified Gompertz growth curve."""
    val = Validator()
    assumptions: list[str] = [
        "log10(N/N0) response",
        "modified Gompertz growth form",
    ]

    t_h = params.get("t", params.get("time_h"))
    a_asym = params.get("A")
    mu_max = params.get("mu_max", params.get("μmax", params.get("mu")))
    lag = params.get("lambda", params.get("lag", params.get("lambda_h")))

    val.require_finite("t", t_h)
    val.require_positive("A", a_asym)
    val.require_positive("mu_max", mu_max, allow_zero=True)
    val.require_positive("lambda", lag, allow_zero=True)

    value: float | None = None
    if (
        all(_is_finite_number(x) for x in (t_h, a_asym, mu_max, lag))
        and a_asym > 0.0 and mu_max >= 0.0 and lag >= 0.0
    ):
        inner = float(mu_max) * math.e / float(a_asym) * (float(lag) - float(t_h)) + 1.0
        inner = max(min(inner, 700.0), -700.0)
        outer = math.exp(inner)
        outer = max(min(outer, 700.0), -700.0)
        value = float(a_asym) * math.exp(-outer)
        if t_h < 0.0:
            assumptions.append("t < 0 → Gompertz curve evaluated by extrapolation")
        if t_h <= lag:
            assumptions.append("t within lag region → growth remains near baseline")
        elif value >= 0.95 * float(a_asym):
            assumptions.append("late-time asymptote reached")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="log10(N/N0)",
        symbol="log10(N/N0)",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"t": t_h, "A": a_asym, "mu_max": mu_max, "lambda": lag},
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if value is not None else float("nan"),
            unit="log10(N/N0)",
            symbol="log10(N/N0)",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
