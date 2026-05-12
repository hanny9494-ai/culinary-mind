"""MF-M08 Gas_Permeability — packaging film gas/vapor flux.

Formula:
    Q_perm = P · delta_p / thickness    (Fick-like steady-state)

Inputs (consistent SI; thickness MUST match permeability length unit):
    Option A — SI native:
        permeability [m²·s⁻¹·Pa⁻¹]    (preferred)
        thickness [m]
        delta_p [Pa]
    Option B — industry units (mil-based; solver converts internally):
        P_O2 / P_CO2 [cm³·mil/(m²·day·atm)]
        thickness [m]      (converted to mil internally for consistency)
        delta_p [atm]

    T_C [°C] (advisory, not in flux equation)
    RH [%]  (advisory, not in flux equation)

Output:
    Q_perm (gas flux in input-unit·atm/m for Option B, or mol/(m²·s) for SI Option A)

NOTE: WVTR (water vapor) is a separate quantity; use industry units P_O2-like
      with substance='water vapor' rather than treating WVTR as input here.
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
    t_c = params.get("T_C", params.get("T_c"))
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
        # Detect industry-unit permeability (cm³·mil/...): if perm is large (>0.001), assume industry units
        # Convert thickness m → mil (1 mil = 2.54e-5 m) for unit consistency
        # P [cm³·mil/(m²·day·atm)] × delta_p [atm] / thickness_mil → cm³/(m²·day)
        # This is industry standard formula
        if "P_O2" in params or "P_CO2" in params:
            thickness_mil = float(thickness) / 2.54e-5
            q_perm = float(perm) * float(delta_p) / thickness_mil
            assumptions.append("industry units: thickness m→mil conversion applied")
        else:
            q_perm = float(perm) * float(delta_p) / float(thickness)
            assumptions.append("SI-native: thickness in m, permeability dimensionally compatible")

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
