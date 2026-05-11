"""MF-T06 Protein_Denaturation — sigmoid (van't Hoff / DSC) model.

Formula:
    f_native(T) = 1 / (1 + exp((T_C - T_d) / sigma))

where sigma is the transition steepness derived from the denaturation
enthalpy via the van 't Hoff relation:

    sigma ≈ R · T_d_K² / dH_d   (units: K)

Inputs:
    T_d [°C]:    midpoint denaturation temperature
    dH_d [kJ/mol]: van 't Hoff enthalpy (controls steepness)
    T_C [°C]:    current temperature
    sigma_override [°C, optional]: bypass dH_d-derived steepness

Output:
    f_native (native protein fraction in [0, 1])

References:
    - Privalov & Khechinashvili (1974) Stability of proteins
    - Belitz et al., Food Chemistry §1 (protein denaturation)
"""

from __future__ import annotations

import math
from typing import Any

from ._common import (
    Validator,
    build_result,
    llm_summary_for,
    provenance_for,
    validate_bounds,
)

TOOL_ID = "MF-T06"
TOOL_CANONICAL_NAME = "Protein_Denaturation"
CITATIONS = [
    "Privalov & Khechinashvili (1974) J Mol Biol — protein stability",
    "Belitz, Grosch, Schieberle, Food Chemistry §1.4 — denaturation",
    "Singh & Heldman, Intro to Food Engineering — thermal kinetics",
]

_R_GAS_J = 8.31446261815324  # J/(mol·K)


@validate_bounds("MF-T06")
def solve(params: dict) -> dict:
    """Compute native protein fraction f_native at temperature T_C."""
    val = Validator()
    assumptions: list[str] = [
        "two-state native ⇌ denatured equilibrium",
        "van 't Hoff transition centered at T_d",
        "sigma derived from dH_d unless explicitly overridden",
    ]

    t_d = params.get("T_d")
    dh_d = params.get("dH_d")
    t_c = params.get("T_C", params.get("T_c"))
    sigma_override = params.get("sigma_override")

    val.require_temperature_celsius("T_d", t_d)
    val.require_temperature_celsius("T_C", t_c)
    val.require_positive("dH_d", dh_d)
    if sigma_override is not None:
        val.require_positive("sigma_override", sigma_override)

    f_native: float | None = None
    if (
        all(
            isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
            for x in (t_d, t_c, dh_d)
        )
        and dh_d > 0
    ):
        if sigma_override is not None and isinstance(sigma_override, (int, float)) \
                and not isinstance(sigma_override, bool) and math.isfinite(sigma_override) \
                and sigma_override > 0:
            sigma = float(sigma_override)
            assumptions.append("sigma supplied via sigma_override")
        else:
            # van 't Hoff steepness: sigma ≈ R T_d_K² / dH_d (in K, equiv to °C)
            t_d_k = float(t_d) + 273.15
            dh_d_j = float(dh_d) * 1000.0  # kJ/mol → J/mol
            sigma = _R_GAS_J * t_d_k * t_d_k / dh_d_j
            assumptions.append(
                f"sigma from van 't Hoff: R·T_d²/dH_d = {sigma:.3g}°C"
            )

        # Clamp argument to avoid math.exp overflow on extreme T_C
        arg = (float(t_c) - float(t_d)) / sigma
        if arg > 700.0:
            f_native = 0.0
        elif arg < -700.0:
            f_native = 1.0
        else:
            f_native = 1.0 / (1.0 + math.exp(arg))

    return build_result(
        value=f_native if f_native is not None else float("nan"),
        unit="dimensionless",
        symbol="f_native",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={
            "T_d": t_d,
            "dH_d": dh_d,
            "T_C": t_c,
            "sigma_override": sigma_override,
        },
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=f_native if f_native is not None else float("nan"),
            unit="dimensionless",
            symbol="f_native",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
