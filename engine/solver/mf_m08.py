"""MF-M08 Gas_Permeability — packaging film gas/vapor flux.

Formula:
    Q_perm = P_O2 · (delta_p / thickness)    (Fick-like steady-state)

Inputs:
    P_O2 or P_CO2 [cm³·mil/(m²·day·atm)] OR WVTR [g/(m²·day)]
    thickness [m]
    delta_p [atm] (pressure differential)
    T_C [°C]
    RH [%]

Output:
    Q_perm (gas flux through film)
"""
from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds

TOOL_ID = "MF-M08"
TOOL_CANONICAL_NAME = "Gas_Permeability"
CITATIONS = [
    "ASTM D3985 — Oxygen Transmission Rate test method",
    "Robertson (2013) Food Packaging Principles & Practice",
]


@validate_bounds("MF-M08")
def solve(params: dict) -> dict:
    val = Validator()
    assumptions = [
        "steady-state Fickian permeation",
        "Q = P · ΔP / L (in supplied units)",
    ]
    perm = params.get("P_O2", params.get("P_CO2", params.get("permeability")))
    thickness = params.get("thickness")
    delta_p = params.get("delta_p", 1.0)
    t_c = params.get("T_C")
    rh = params.get("RH")

    val.require_positive("permeability", perm)
    val.require_positive("thickness", thickness)
    val.require_positive("delta_p", delta_p, allow_zero=True)
    if t_c is not None:
        val.require_temperature_celsius("T_C", t_c)
    if rh is not None:
        val.require_in_range("RH", rh, 0.0, 100.0)

    q_perm = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
            for x in (perm, thickness, delta_p))
        and perm > 0 and thickness > 0 and delta_p >= 0
    ):
        q_perm = float(perm) * float(delta_p) / float(thickness)

    return build_result(
        value=q_perm if q_perm is not None else float("nan"),
        unit="permeability·atm/m (input-unit·atm/m)",
        symbol="Q_perm",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"permeability": perm, "thickness": thickness, "delta_p": delta_p, "T_C": t_c, "RH": rh},
        provenance=provenance_for(tool_id=TOOL_ID, tool_canonical_name=TOOL_CANONICAL_NAME, citations=CITATIONS),
        llm_summary=llm_summary_for(
            value=q_perm if q_perm is not None else float("nan"),
            unit="permeability·atm/m", symbol="Q_perm",
            tool_canonical_name=TOOL_CANONICAL_NAME, tool_id=TOOL_ID,
        ),
    )
