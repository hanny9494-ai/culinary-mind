"""MF-M11 SCFE_Solubility — Supercritical CO2 Extraction solubility (Chrastil-style).

Formula (Chrastil 1982):
    ln(y_solute) = k · ln(rho_CO2) + a/T_K + b

Inputs:
    rho_CO2 [kg/m³]:   SC-CO2 density
    T_K [K] or T_C [°C]:  temperature
    k [-]:             Chrastil exponent (default 5.0)
    a [K]:             Chrastil temperature coefficient (default -3000)
    b [-]:             Chrastil intercept (default -20.0)

Output:
    y_solute (mole fraction, dimensionless)
"""
from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds

TOOL_ID = "MF-M11"
TOOL_CANONICAL_NAME = "SCFE_Solubility"
CITATIONS = [
    "Chrastil (1982) J Phys Chem 86:3016 — Solubility in dense gases",
    "Brunner (1994) Gas Extraction — Theory & Practice",
]


@validate_bounds("MF-M11")
def solve(params: dict) -> dict:
    val = Validator()
    assumptions = ["Chrastil 1982 empirical correlation", "supercritical CO2 phase"]
    rho = params.get("rho_CO2", params.get("rho"))
    t_k = params.get("T_K")
    t_c = params.get("T_C", params.get("T_c"))
    k = params.get("k", 5.0)
    a = params.get("a", -3000.0)
    b = params.get("b", -20.0)

    val.require_positive("rho_CO2", rho)
    val.require_finite("k", k)
    val.require_finite("a", a)
    val.require_finite("b", b)

    if t_k is None and t_c is not None:
        val.require_temperature_celsius("T_C", t_c)
        if isinstance(t_c, (int, float)) and not isinstance(t_c, bool) and math.isfinite(t_c):
            t_k = float(t_c) + 273.15
    val.require_positive("T_K", t_k)

    y_solute = None
    if all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
           for x in (rho, t_k, k, a, b)) and rho > 0 and t_k > 0:
        ln_y = float(k) * math.log(float(rho)) + float(a) / float(t_k) + float(b)
        if ln_y > 700:
            y_solute = float("inf")
        elif ln_y < -700:
            y_solute = 0.0
        else:
            y_solute = math.exp(ln_y)

    return build_result(
        value=y_solute if y_solute is not None else float("nan"),
        unit="dimensionless (mole fraction)",
        symbol="y_solute",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"rho_CO2": rho, "T_K": t_k, "T_C": t_c, "k": k, "a": a, "b": b},
        provenance=provenance_for(tool_id=TOOL_ID, tool_canonical_name=TOOL_CANONICAL_NAME, citations=CITATIONS),
        llm_summary=llm_summary_for(
            value=y_solute if y_solute is not None else float("nan"),
            unit="mole fraction", symbol="y_solute",
            tool_canonical_name=TOOL_CANONICAL_NAME, tool_id=TOOL_ID,
        ),
    )
