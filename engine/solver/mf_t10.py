"""MF-T10 Starch_Gelatinization — Avrami-like extent kinetics.

Formula:
    α(t) = 1 - exp(-k(T) · t^n)
    k(T) = A · exp(-Ea/(R·T_K))

Inputs:
    T_C [°C]          — current temperature
    time [s]          — heating time
    A [s^-1]          — Avrami pre-exponential
    Ea [J/mol]        — activation energy
    n [-]             — Avrami exponent (typical 1.0–3.0)
    water_content [-] — H₂O mass fraction (advisory; gelatinization needs ≥ ~0.5)

Output:
    alpha (gelatinization extent in [0, 1])

References:
    - Lund (1984) "Starch Gelatinization" CRC Food Sci Tech
    - BeMiller & Whistler (2009) Starch: Chemistry & Technology Ch.7
    - Marabi et al. (2003) — Avrami modeling of starch hydration
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

TOOL_ID = "MF-T10"
TOOL_CANONICAL_NAME = "Starch_Gelatinization"
CITATIONS = [
    "Lund (1984) Starch Gelatinization — CRC Food Sci Tech",
    "BeMiller & Whistler (2009) Starch Ch.7",
    "Marabi et al. (2003) J Food Eng — Avrami starch hydration",
]

_R_GAS_J = 8.31446261815324


@validate_bounds("MF-T10")
def solve(params: dict) -> dict:
    """Compute starch gelatinization extent alpha."""
    val = Validator()
    assumptions: list[str] = [
        "Avrami-like first-order with shape exponent n",
        "k(T) follows Arrhenius",
        "water sufficient for gelatinization (advisory check on water_content)",
    ]

    t_c = params.get("T_C", params.get("T_c"))
    time = params.get("time", params.get("t"))
    a_factor = params.get("A")
    ea = params.get("Ea")
    n = params.get("n", 1.0)
    water = params.get("water_content")

    val.require_temperature_celsius("T_C", t_c)
    val.require_positive("time", time, allow_zero=True)
    val.require_positive("A", a_factor)
    val.require_positive("Ea", ea, allow_zero=True)
    val.require_positive("n", n)
    if water is not None:
        val.require_in_range("water_content", water, 0.0, 1.0)
        if isinstance(water, (int, float)) and not isinstance(water, bool) \
                and math.isfinite(water) and water < 0.30:
            assumptions.append(
                f"water_content={water} < 0.30 — gelatinization likely incomplete"
            )

    alpha: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
            for x in (t_c, time, a_factor, ea, n))
        and time >= 0 and a_factor > 0 and ea >= 0 and n > 0
    ):
        t_k = float(t_c) + 273.15
        k_t = float(a_factor) * math.exp(-float(ea) / (_R_GAS_J * t_k))
        # Compute alpha with overflow protection
        arg = k_t * (float(time) ** float(n))
        if arg > 700.0:
            alpha = 1.0
        elif arg < 0.0:
            alpha = float("nan")  # shouldn't happen with positive inputs
        else:
            alpha = 1.0 - math.exp(-arg)

    return build_result(
        value=alpha if alpha is not None else float("nan"),
        unit="dimensionless",
        symbol="alpha",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={
            "T_C": t_c, "time": time, "A": a_factor, "Ea": ea, "n": n,
            "water_content": water,
        },
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=alpha if alpha is not None else float("nan"),
            unit="dimensionless",
            symbol="alpha",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
