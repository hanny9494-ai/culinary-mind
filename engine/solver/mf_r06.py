"""MF-R06 Stevens_Power_Law — perceived intensity from stimulus intensity.

Formula:
    S = k · I^n

References:
    - Stevens' psychophysical power law; pure algebra per D65.

Inputs:
    k, I, n.

Assumptions:
    - stimulus scale is non-negative
    - k and n are fitted for one sensory modality
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result


def solve(params: dict) -> dict:
    """Compute perceived intensity S."""
    val = Validator()
    assumptions: list[str] = [
        "single-modality Stevens power law",
        "stimulus intensity is non-negative",
    ]

    k_coeff = params.get("k")
    intensity = params.get("I")
    n = params.get("n")

    val.require_positive("k", k_coeff)
    val.require_positive("I", intensity, allow_zero=True)
    val.require_positive("n", n)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (k_coeff, intensity, n))
        and all(math.isfinite(float(x)) for x in (k_coeff, intensity, n))
        and k_coeff > 0.0 and intensity >= 0.0 and n > 0.0
    ):
        value = float(k_coeff) * (float(intensity) ** float(n))
        if math.isclose(float(intensity), 1.0, rel_tol=1e-12, abs_tol=1e-12):
            assumptions.append("I = 1 → S = k")
        if math.isclose(float(n), 1.0, rel_tol=1e-12, abs_tol=1e-12):
            assumptions.append("n = 1 → linear stimulus-response")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="perceived intensity units",
        symbol="S",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"k": k_coeff, "I": intensity, "n": n},
    )
