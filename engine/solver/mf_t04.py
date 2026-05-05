"""MF-T04 Nusselt_Correlation — convective heat transfer correlation.

Equation:
    Nu = C · Re^m · Pr^n

The Nusselt number `Nu` is then converted (downstream, by the caller)
to a film coefficient via:

    h = Nu · k_fluid / L_characteristic

We do **not** compute h directly here — it depends on the fluid
conductivity and characteristic length which are external inputs not
listed in the MF-T04 row of `mother_formulas.yaml`. If the caller
supplies `k_fluid` and `L_characteristic`, we'll compute h as a bonus
and return it under `result.extras.h`.

Inputs (per yaml MF-T04):
    Runtime variables: Re, Pr               (dimensionless)
    One-of-inputs:     [C, m, n]            empirical fit constants
"""

from __future__ import annotations

from typing import Any

from ._common import Validator, build_result, llm_summary_for, provenance_for


TOOL_ID = 'MF-T04'
TOOL_CANONICAL_NAME = 'Nusselt_Correlation'
CITATIONS = [
    'Singh & Heldman, Introduction to Food Engineering Ch.4',
    'Toledo, Fundamentals of Food Process Engineering Ch.7',
]



def solve(params: dict) -> dict:
    val = Validator()
    assumptions = [
        "single-phase forced convection",
        "C/m/n must match the geometry/flow regime "
        "of the substrate — see MF-T04 notes",
    ]

    re = params.get("Re")
    pr = params.get("Pr")
    c, m, n = params.get("C"), params.get("m"), params.get("n")

    val.require_positive("Re", re)
    val.require_positive("Pr", pr)
    val.require_positive("C", c)
    val.require_finite("m", m)
    val.require_finite("n", n)

    nu = float("nan")
    if all(isinstance(x, (int, float)) for x in (re, pr, c, m, n)) and re > 0 and pr > 0 and c > 0:
        nu = float(c) * (float(re) ** float(m)) * (float(pr) ** float(n))

    # Optional film coefficient bonus
    extras: dict[str, Any] = {}
    k_fluid = params.get("k_fluid")
    l_char  = params.get("L_characteristic")
    if k_fluid is not None and l_char is not None:
        val.require_positive("k_fluid", k_fluid)
        val.require_positive("L_characteristic", l_char)
        if isinstance(k_fluid, (int, float)) and isinstance(l_char, (int, float)):
            if k_fluid > 0 and l_char > 0 and nu == nu:   # not NaN
                extras["h"] = nu * float(k_fluid) / float(l_char)
                extras["h_unit"] = "W/(m²·K)"
                assumptions.append(
                    f"film coefficient h = Nu·k_fluid/L_characteristic "
                    f"= {nu:.3f}·{k_fluid}/{l_char}"
                )

    inputs_used = {"Re": re, "Pr": pr, "C": c, "m": m, "n": n}
    if k_fluid is not None:           inputs_used["k_fluid"] = k_fluid
    if l_char is not None:            inputs_used["L_characteristic"] = l_char

    out = build_result(
        value=nu,
        unit="dimensionless",
        symbol="Nu",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used=inputs_used,
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=nu,
            unit="dimensionless",
            symbol="Nu",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
            extra_outputs=extras,
        ),
    )
    if extras:
        out["result"]["extras"] = extras
    return out
