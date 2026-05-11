"""MF-M10 Membrane_Transport — solute flux through membrane (linear-driving-force).

Formula:
    J_solute = P · (c1 - c2) / thickness

Inputs:
    P [m/s]:        solute permeability
    thickness [m]:  membrane thickness
    dC [mol/m³]:    concentration gradient = (c1 - c2)

Output:
    J_solute (mass flux, mol/(m²·s))
"""
from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds

TOOL_ID = "MF-M10"
TOOL_CANONICAL_NAME = "Membrane_Transport"
CITATIONS = [
    "Mulder (1996) Basic Principles of Membrane Technology",
    "Cheryan (1998) Ultrafiltration & Microfiltration Handbook",
]


@validate_bounds("MF-M10")
def solve(params: dict) -> dict:
    val = Validator()
    assumptions = ["linear-driving-force flux model", "steady-state diffusion"]
    p_solute = params.get("P_solute", params.get("P"))
    thickness = params.get("thickness", params.get("L"))
    dc = params.get("dC", params.get("dc", params.get("delta_c")))
    val.require_positive("P_solute", p_solute)
    val.require_positive("thickness", thickness)
    val.require_finite("dC", dc)

    j_solute = None
    if all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
           for x in (p_solute, thickness, dc)) and p_solute > 0 and thickness > 0:
        j_solute = float(p_solute) * float(dc) / float(thickness)

    return build_result(
        value=j_solute if j_solute is not None else float("nan"),
        unit="mol/(m²·s)",
        symbol="J_solute",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"P_solute": p_solute, "thickness": thickness, "dC": dc},
        provenance=provenance_for(tool_id=TOOL_ID, tool_canonical_name=TOOL_CANONICAL_NAME, citations=CITATIONS),
        llm_summary=llm_summary_for(
            value=j_solute if j_solute is not None else float("nan"),
            unit="mol/(m²·s)", symbol="J_solute",
            tool_canonical_name=TOOL_CANONICAL_NAME, tool_id=TOOL_ID,
        ),
    )
