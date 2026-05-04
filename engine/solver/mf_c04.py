"""MF-C04 Laplace_Pressure — pressure jump across a spherical interface.

Formula:
    Delta P = 2 sigma / R

References:
    - Young-Laplace equation for a spherical droplet or bubble; pure algebra.

Inputs:
    sigma [N/m], R or r [m].

Assumptions:
    - spherical interface
    - uniform surface tension
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result


def solve(params: dict) -> dict:
    """Compute Laplace pressure in Pa."""
    val = Validator()
    assumptions: list[str] = ["spherical interface", "uniform surface tension"]

    sigma = params.get("sigma", params.get("gamma"))
    radius = params.get("R", params.get("r"))

    val.require_positive("sigma", sigma)
    val.require_positive("R", radius)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (sigma, radius))
        and all(math.isfinite(float(x)) for x in (sigma, radius))
        and sigma > 0.0 and radius > 0.0
    ):
        value = 2.0 * float(sigma) / float(radius)
        if radius <= 1.0e-6:
            assumptions.append("micron-scale interface → large capillary pressure")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="Pa",
        symbol="DeltaP",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"sigma": sigma, "R": radius},
    )
