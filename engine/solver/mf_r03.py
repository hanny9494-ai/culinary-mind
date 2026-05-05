"""MF-R03 Casson_Model — Casson yield-flow relation.

Formula:
    sqrt(tau) = sqrt(tau_0) + sqrt(K_C · gamma_dot)

References:
    - Casson model used for chocolate and yield-stress foods.

Inputs:
    tau_0 or tau_c [Pa], K_C or eta_c [Pa·s], gamma_dot [s^-1].

Assumptions:
    - steady isothermal shear
    - Casson square-root stress relation
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for


TOOL_ID = 'MF-R03'
TOOL_CANONICAL_NAME = 'Casson_Model'
CITATIONS = [
    'Rao, Engineering Properties of Foods Ch.2',
    'Bourne, Food Texture and Viscosity Ch.3',
]



def solve(params: dict) -> dict:
    """Compute Casson shear stress tau in Pa."""
    val = Validator()
    assumptions: list[str] = [
        "steady isothermal simple shear",
        "Casson square-root stress form",
    ]

    tau_0 = params.get("tau_0", params.get("tau_c"))
    k_c = params.get("K_C", params.get("eta_c"))
    gamma_dot = params.get("gamma_dot")

    val.require_positive("tau_0", tau_0, allow_zero=True)
    val.require_positive("K_C", k_c)
    val.require_positive("gamma_dot", gamma_dot, allow_zero=True)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (tau_0, k_c, gamma_dot))
        and all(math.isfinite(float(x)) for x in (tau_0, k_c, gamma_dot))
        and tau_0 >= 0.0 and k_c > 0.0 and gamma_dot >= 0.0
    ):
        value = (math.sqrt(float(tau_0)) + math.sqrt(float(k_c) * float(gamma_dot))) ** 2
        if gamma_dot == 0.0:
            assumptions.append("gamma_dot = 0 → tau = tau_0")
        if tau_0 == 0.0:
            assumptions.append("tau_0 = 0 → Casson relation reduces to linear stress")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="Pa",
        symbol="tau",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"tau_0": tau_0, "K_C": k_c, "gamma_dot": gamma_dot},
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
