"""MF-R02 Herschel_Bulkley — yield-stress power-law rheology.

Formula:
    tau = tau_0 + K · gamma_dot^n

References:
    - Herschel-Bulkley model; scipy.optimize.curve_fit is the companion
      fitting route, while this solver evaluates the forward relation.

Inputs:
    tau_0 [Pa], K [Pa·s^n], n, gamma_dot [s^-1].

Assumptions:
    - steady isothermal simple shear
    - material has a yield stress plus power-law flow above yield
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds


TOOL_ID = 'MF-R02'
TOOL_CANONICAL_NAME = 'Herschel_Bulkley'
CITATIONS = [
    'Rao, Engineering Properties of Foods Ch.2',
    'Bourne, Food Texture and Viscosity Ch.3',
    'Sahin & Sumnu, Physical Properties of Foods Ch.2',
]



@validate_bounds("MF-R02")
def solve(params: dict) -> dict:
    """Compute shear stress tau in Pa."""
    val = Validator()
    assumptions: list[str] = [
        "steady isothermal simple shear",
        "Herschel-Bulkley yield-stress fluid",
    ]

    tau_0 = params.get("tau_0", params.get("tau0"))
    k_consistency = params.get("K")
    n = params.get("n")
    gamma_dot = params.get("gamma_dot")

    val.require_positive("tau_0", tau_0, allow_zero=True)
    val.require_positive("K", k_consistency)
    val.require_positive("n", n)
    val.require_positive("gamma_dot", gamma_dot, allow_zero=True)
    if isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n):
        if n > 2.0:
            assumptions.append(
                f"n={n} unusually high (>2); typical range 0.1-2.0 for foods. "
                "Verify against rheometer data"
            )

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (tau_0, k_consistency, n, gamma_dot))
        and all(math.isfinite(float(x)) for x in (tau_0, k_consistency, n, gamma_dot))
        and tau_0 >= 0.0 and k_consistency > 0.0 and n > 0.0 and gamma_dot >= 0.0
    ):
        value = float(tau_0) + float(k_consistency) * (float(gamma_dot) ** float(n))
        if gamma_dot == 0.0:
            assumptions.append("gamma_dot = 0 → tau = tau_0")
        if tau_0 == 0.0 and math.isclose(float(n), 1.0, rel_tol=1e-12, abs_tol=1e-12):
            assumptions.append("tau_0 = 0 and n = 1 → Newtonian fluid")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="Pa",
        symbol="tau",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"tau_0": tau_0, "K": k_consistency, "n": n, "gamma_dot": gamma_dot},
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if value is not None else float("nan"),
            unit="Pa",
            symbol="tau",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
