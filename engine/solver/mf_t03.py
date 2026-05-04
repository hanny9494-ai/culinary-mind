"""MF-T03 Arrhenius — temperature dependence of a rate constant.

Formula:
    k = A · exp(-Ea / (R · T))

References:
    - Classical Arrhenius rate equation; pure algebra per D65.

Inputs:
    A, Ea [J/mol], T_K [K], optional R [J/(mol K)].

Assumptions:
    - T_K is absolute temperature in Kelvin
    - A and Ea are for one dominant mechanism over the temperature interval
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result


_R_GAS = 8.31446261815324


def solve(params: dict) -> dict:
    """Compute Arrhenius rate constant k."""
    val = Validator()
    assumptions: list[str] = [
        "temperature supplied in Kelvin",
        "single Arrhenius activation energy",
    ]

    a_factor = params.get("A")
    ea = params.get("Ea")
    t_k = params.get("T_K", params.get("T"))
    r_gas = params.get("R", _R_GAS)

    val.require_positive("A", a_factor)
    val.require_positive("Ea", ea, allow_zero=True)
    val.require_positive("T_K", t_k)
    val.require_positive("R", r_gas)

    k_value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (a_factor, ea, t_k, r_gas))
        and a_factor > 0.0 and ea >= 0.0 and t_k > 0.0 and r_gas > 0.0
    ):
        if ea == 0.0:
            assumptions.append("Ea = 0 → k = A")
        k_value = float(a_factor) * math.exp(-float(ea) / (float(r_gas) * float(t_k)))

    return build_result(
        value=k_value if k_value is not None else float("nan"),
        unit="same as A",
        symbol="k",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"A": a_factor, "Ea": ea, "T_K": t_k, "R": r_gas},
    )
