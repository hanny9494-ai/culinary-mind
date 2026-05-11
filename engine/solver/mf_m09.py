"""MF-M09 Osmotic_Pressure — van't Hoff osmotic pressure.

Formula:
    π = i · M · R · T

Inputs:
    M [mol/L]:  molar concentration of solute (sum over species)
    T_K [K] or T_C [°C]:  absolute temperature
    i [-]:      van't Hoff factor (default 1.0)

Output:
    pi (osmotic pressure, Pa)
"""
from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds

TOOL_ID = "MF-M09"
TOOL_CANONICAL_NAME = "Osmotic_Pressure"
CITATIONS = [
    "Atkins Physical Chemistry — colligative properties",
    "Singh & Heldman — osmotic processes",
]

_R_GAS = 8.31446261815324


@validate_bounds("MF-M09")
def solve(params: dict) -> dict:
    val = Validator()
    assumptions = ["dilute ideal solution, van't Hoff equation"]
    m = params.get("M", params.get("M_osmolar", params.get("c")))
    t_k = params.get("T_K")
    t_c = params.get("T_C", params.get("T_c"))
    i_factor = params.get("i", 1.0)
    val.require_positive("M", m, allow_zero=True)
    val.require_positive("i", i_factor)

    if t_k is None and t_c is not None:
        val.require_temperature_celsius("T_C", t_c)
        if isinstance(t_c, (int, float)) and not isinstance(t_c, bool) and math.isfinite(t_c):
            t_k = float(t_c) + 273.15
            assumptions.append(f"T_K = T_C + 273.15 = {t_k:.2f} K")
    val.require_positive("T_K", t_k)

    pi = None
    if all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
           for x in (m, i_factor, t_k)) and m >= 0 and i_factor > 0 and t_k > 0:
        # M [mol/L] → mol/m³ = 1000 · M
        pi = float(i_factor) * float(m) * 1000.0 * _R_GAS * float(t_k)

    return build_result(
        value=pi if pi is not None else float("nan"),
        unit="Pa",
        symbol="pi",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"M": m, "T_K": t_k, "T_C": t_c, "i": i_factor},
        provenance=provenance_for(tool_id=TOOL_ID, tool_canonical_name=TOOL_CANONICAL_NAME, citations=CITATIONS),
        llm_summary=llm_summary_for(
            value=pi if pi is not None else float("nan"),
            unit="Pa", symbol="pi",
            tool_canonical_name=TOOL_CANONICAL_NAME, tool_id=TOOL_ID,
        ),
    )
