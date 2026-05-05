"""MF-K01 Michaelis_Menten — enzyme reaction rate.

Equation:
    v = Vmax · [S] / (Km + [S])

Asymptotic regimes (notes from yaml):
    [S] ≫ Km  →  v ≈ Vmax           (zeroth order)
    [S] ≪ Km  →  v ≈ Vmax · [S]/Km  (first order)

Inputs (per `config/mother_formulas.yaml` → MF-K01):
    Runtime variables: S            mol/L
    One-of-inputs:     [Vmax, Km]   mol/(L·s), mol/L
"""

from __future__ import annotations

from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for


TOOL_ID = 'MF-K01'
TOOL_CANONICAL_NAME = 'Michaelis_Menten'
CITATIONS = [
    'van Boekel, Kinetic Modeling of Reactions in Foods Ch.9',
    'Belitz et al., Food Chemistry Ch.2',
    'Fennema, Food Chemistry Ch.6',
]



def solve(params: dict) -> dict:
    val = Validator()
    assumptions = ["steady state", "single substrate", "no inhibition"]

    s    = params.get("S")
    vmax = params.get("Vmax")
    km   = params.get("Km")

    val.require_positive("S", s, allow_zero=True)
    val.require_positive("Vmax", vmax)
    val.require_positive("Km", km)

    v: float | None = None
    if all(isinstance(x, (int, float)) for x in (s, vmax, km)) and s >= 0 and vmax > 0 and km > 0:
        v = float(vmax) * float(s) / (float(km) + float(s))
        # Annotate the regime
        if s >= 10 * km:
            assumptions.append(
                f"[S]/Km = {s/km:.1f} ≥ 10 → near-zeroth-order regime "
                f"(v ≈ Vmax)"
            )
        elif s <= km / 10.0:
            assumptions.append(
                f"[S]/Km = {s/km:.3f} ≤ 0.1 → near-first-order regime "
                f"(v ≈ Vmax·S/Km)"
            )

    return build_result(
        value=v if v is not None else float("nan"),
        unit="mol/(L·s)",
        symbol="v",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"S": s, "Vmax": vmax, "Km": km},
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=v if v is not None else float("nan"),
            unit="mol/(L·s)",
            symbol="v",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
