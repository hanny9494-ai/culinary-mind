"""MF-K07 Binding_Equilibrium — ligand-protein binding fraction.

Formula:
    K_a = [PL] / ([P]·[L])    (association constant)
    f_bound = K_a·L_free / (1 + K_a·L_free)  (for excess ligand)

Inputs:
    K_a [L/mol]:    association constant (OR K_d = 1/K_a)
    L_total [mol/L]: total ligand
    P_total [mol/L]: total protein

Output:
    f_bound (fraction of protein bound, [0,1])
"""
from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds

TOOL_ID = "MF-K07"
TOOL_CANONICAL_NAME = "Binding_Equilibrium"
CITATIONS = [
    "Bell & Labuza (2000) Moisture sorption — protein binding",
    "Tinoco et al. Physical Chemistry — binding equilibria",
]


@validate_bounds("MF-K07")
def solve(params: dict) -> dict:
    val = Validator()
    assumptions = [
        "single binding site (1:1 stoichiometry)",
        "L_free ≈ L_total when L >> P",
    ]
    ka = params.get("K_a", params.get("Ka"))
    kd = params.get("K_d", params.get("Kd"))
    l_total = params.get("L_total", params.get("L"))
    p_total = params.get("P_total", params.get("P"))

    # Allow K_d instead of K_a
    if ka is None and kd is not None:
        val.require_positive("K_d", kd)
        if isinstance(kd, (int, float)) and not isinstance(kd, bool) and math.isfinite(kd) and kd > 0:
            ka = 1.0 / float(kd)
            assumptions.append(f"K_a derived from K_d: K_a = 1/K_d = {ka:.3g}")

    val.require_positive("K_a", ka)
    val.require_positive("L_total", l_total)
    if p_total is not None:
        val.require_positive("P_total", p_total, allow_zero=True)

    f_bound = None
    if (
        isinstance(ka, (int, float)) and not isinstance(ka, bool) and math.isfinite(ka) and ka > 0
        and isinstance(l_total, (int, float)) and not isinstance(l_total, bool) and math.isfinite(l_total) and l_total > 0
    ):
        ka_f = float(ka)
        L_t = float(l_total)
        if isinstance(p_total, (int, float)) and not isinstance(p_total, bool) and math.isfinite(p_total) and p_total > 0:
            # Exact 1:1 binding mass balance:
            #   [PL] = (1/2)·{(P + L + 1/Ka) - sqrt[(P + L + 1/Ka)² - 4PL]}
            #   f_bound = [PL]/P_total
            P_t = float(p_total)
            sum_t = P_t + L_t + 1.0 / ka_f
            disc = sum_t * sum_t - 4.0 * P_t * L_t
            if disc < 0:
                disc = 0.0  # numerical guard; should not be < 0 mathematically
            pl_conc = 0.5 * (sum_t - math.sqrt(disc))
            f_bound = pl_conc / P_t
            assumptions.append("exact 1:1 binding mass-balance solved (no L_free approx)")
        else:
            # Excess-ligand approximation
            kl = ka_f * L_t
            f_bound = kl / (1.0 + kl)
            assumptions.append("excess-ligand approx (no P_total supplied)")

    return build_result(
        value=f_bound if f_bound is not None else float("nan"),
        unit="dimensionless",
        symbol="f_bound",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"K_a": ka, "K_d": kd, "L_total": l_total, "P_total": p_total},
        provenance=provenance_for(tool_id=TOOL_ID, tool_canonical_name=TOOL_CANONICAL_NAME, citations=CITATIONS),
        llm_summary=llm_summary_for(
            value=f_bound if f_bound is not None else float("nan"),
            unit="dimensionless", symbol="f_bound",
            tool_canonical_name=TOOL_CANONICAL_NAME, tool_id=TOOL_ID,
        ),
    )
