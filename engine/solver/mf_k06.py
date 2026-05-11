"""MF-K06 Growth_Limit — microbial growth boundary check.

Decision rule:
    growth = (pH ≥ pH_min) ∧ (a_w ≥ a_w_min) ∧ (T_C ≥ T_min) ∧ ([substance] ≤ MIC)

A given combination of (pH, a_w, T_C, substance_conc) is "growth-inhibited"
when ANY of the minimum-condition thresholds fails OR substance ≥ MIC.

Inputs (limits — supply at least one):
    pH_min, a_w_min, T_min, MIC

Inputs (current condition — match supplied limits):
    pH, a_w, T_C, substance_conc

Output:
    growth_inhibited (bool encoded as 0.0/1.0; 1.0 = inhibited)
    + extra_outputs.margins for each axis

References:
    - ICMSF Microorganisms in Foods 6, growth limit tables
    - Pitt & Hocking Fungi and Food Spoilage Ch.5
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

TOOL_ID = "MF-K06"
TOOL_CANONICAL_NAME = "Growth_Limit"
CITATIONS = [
    "ICMSF (2018) Microorganisms in Foods 6 — growth/no-growth limits",
    "Pitt & Hocking (2009) Fungi and Food Spoilage Ch.5",
    "FDA Bad Bug Book — minimum growth conditions",
]


@validate_bounds("MF-K06")
def solve(params: dict) -> dict:
    """Check whether condition (pH, a_w, T, substance) inhibits growth."""
    val = Validator()
    assumptions: list[str] = [
        "AND combination of all supplied limits (hurdle technology)",
        "MIC is for the test substance only (preservative or antimicrobial)",
    ]

    # Limits
    ph_min = params.get("pH_min")
    aw_min = params.get("a_w_min")
    t_min = params.get("T_min")
    mic = params.get("MIC")

    # Current conditions
    ph = params.get("pH")
    aw = params.get("a_w")
    t_c = params.get("T_C", params.get("T_c"))
    subs_conc = params.get("substance_conc")

    # At least one limit/condition pair must be supplied
    pairs = [
        ("pH", ph, "pH_min", ph_min),
        ("a_w", aw, "a_w_min", aw_min),
        ("T_C", t_c, "T_min", t_min),
        ("substance_conc", subs_conc, "MIC", mic),
    ]
    supplied = [(n_v, v, n_l, l) for n_v, v, n_l, l in pairs if l is not None]
    if not supplied:
        val.issues.append("at least one of pH_min/a_w_min/T_min/MIC required")

    # Validate finiteness on supplied limits + their paired current value
    for n_v, v, n_l, l in supplied:
        val.require_finite(n_l, l)
        if v is None:
            val.issues.append(f"{n_v} required when {n_l} supplied")
        else:
            val.require_finite(n_v, v)

    # Range checks
    if ph is not None and isinstance(ph, (int, float)) and not isinstance(ph, bool) and math.isfinite(ph):
        val.require_in_range("pH", ph, 0.0, 14.0)
    if aw is not None and isinstance(aw, (int, float)) and not isinstance(aw, bool) and math.isfinite(aw):
        val.require_in_range("a_w", aw, 0.0, 1.0)

    margins: dict[str, float] = {}
    inhibited = False
    if supplied and not val.issues:
        for n_v, v, n_l, l in supplied:
            if n_v == "substance_conc":
                # substance_conc inhibits when ≥ MIC
                margin = float(v) - float(l)  # positive means above MIC → inhibited
                margins[f"{n_v}_minus_{n_l}"] = margin
                if margin >= 0:
                    inhibited = True
            else:
                # pH/a_w/T_C inhibit when < min
                margin = float(v) - float(l)  # positive means above min → growth ok
                margins[f"{n_v}_minus_{n_l}"] = margin
                if margin < 0:
                    inhibited = True
        if inhibited:
            assumptions.append("growth inhibited by at least one hurdle")
        else:
            assumptions.append("all supplied conditions permit growth")

    value = 1.0 if inhibited else 0.0

    return build_result(
        value=value if not val.issues else float("nan"),
        unit="boolean (1=inhibited, 0=growth-permitted)",
        symbol="growth_inhibited",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={
            "pH_min": ph_min, "a_w_min": aw_min, "T_min": t_min, "MIC": mic,
            "pH": ph, "a_w": aw, "T_C": t_c, "substance_conc": subs_conc,
        },
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if not val.issues else float("nan"),
            unit="boolean",
            symbol="growth_inhibited",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
            extra_outputs={"margins": margins},
        ),
    )
