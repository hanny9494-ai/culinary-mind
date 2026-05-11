"""MF-T07 Dielectric_Properties — RF/Microwave volumetric heating.

Formula:
    P_abs = 2 · π · f · ε₀ · ε'' · |E|²

where:
    f       [Hz]  — RF or microwave frequency
    ε''     [-]   — dielectric loss factor
    |E|     [V/m] — local electric field magnitude
    ε₀      = 8.8541878128e-12 F/m  (permittivity of free space)
    P_abs   [W/m³] — volumetric absorbed power density

Inputs:
    epsilon_double_prime
    frequency [Hz]
    E_field [V/m]

Output:
    P_abs (volumetric absorbed power, W/m³)

References:
    - Singh & Heldman Ch.5 — Microwave processing
    - Datta & Davidson (2000) Microwave food processing
    - Buffler (1993) Microwave Cooking & Processing
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

TOOL_ID = "MF-T07"
TOOL_CANONICAL_NAME = "Dielectric_Properties"
CITATIONS = [
    "Singh & Heldman, Intro Food Engineering Ch.5 — microwave",
    "Datta & Davidson (2000) J Food Sci 65:1 — MW food processing",
    "Buffler, Microwave Cooking & Processing (1993)",
]

_EPSILON_0 = 8.8541878128e-12  # F/m


@validate_bounds("MF-T07")
def solve(params: dict) -> dict:
    """Compute volumetric absorbed power density P_abs."""
    val = Validator()
    assumptions: list[str] = [
        "uniform |E| within the volume element",
        "ε'' treated as effective dielectric loss factor",
        "no magnetic loss contribution (non-magnetic food)",
    ]

    eps2 = params.get("epsilon_double_prime", params.get("epsilon_pp"))
    freq = params.get("frequency", params.get("f"))
    e_field = params.get("E_field", params.get("E"))

    val.require_positive("epsilon_double_prime", eps2, allow_zero=True)
    val.require_positive("frequency", freq)
    val.require_positive("E_field", e_field, allow_zero=True)

    p_abs: float | None = None
    if all(
        isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
        for x in (eps2, freq, e_field)
    ) and eps2 >= 0 and freq > 0 and e_field >= 0:
        p_abs = 2.0 * math.pi * float(freq) * _EPSILON_0 * float(eps2) * float(e_field) ** 2

    return build_result(
        value=p_abs if p_abs is not None else float("nan"),
        unit="W/m³",
        symbol="P_abs",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={
            "epsilon_double_prime": eps2,
            "frequency": freq,
            "E_field": e_field,
        },
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=p_abs if p_abs is not None else float("nan"),
            unit="W/m³",
            symbol="P_abs",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
