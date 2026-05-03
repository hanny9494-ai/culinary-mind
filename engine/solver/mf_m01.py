"""MF-M01 Fick_2nd_Law — 1D unsteady diffusion.

PDE:
    ∂C/∂t = D_eff · ∂²C/∂x²

Analytical semi-infinite slab solution with a step concentration at the
surface (boundary fixed at `C_boundary`, initial uniform `C_init`):

    C(x, t) = C_init + (C_boundary - C_init) · erfc( x / (2·√(D_eff · t)) )

Assumes:
  • semi-infinite slab (probe far from far-side boundary)
  • constant D_eff
  • step boundary at t = 0
  • 1D mass flow

Inputs (per `config/mother_formulas.yaml` → MF-M01):
    Runtime variables: C_init, C_boundary, thickness, time, x_position
    One-of-inputs:     [D_eff]                        m²/s
    Constants:         [dx]   (accepted but unused; analytical mode)

Reasonable D_eff ranges (notes from yaml):
    water in food:     1e-12 to 1e-9   m²/s
    aroma compound:    1e-11 to 1e-8   m²/s
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result


def solve(params: dict) -> dict:
    val = Validator()
    assumptions: list[str] = [
        "semi-infinite slab",
        "step concentration boundary at t=0",
        "constant D_eff",
        "1D mass flow",
    ]

    c_init      = params.get("C_init")
    c_boundary  = params.get("C_boundary")
    t_time      = params.get("time")
    x_pos       = params.get("x_position")
    thickness   = params.get("thickness")
    d_eff       = params.get("D_eff")

    # P1.1 (PR #20 D69 review): C_init / C_boundary are concentrations in
    # mol/m³ or kg/m³ — they must be ≥ 0. require_finite alone let negative
    # values through, violating unit semantics.
    val.require_positive("C_init", c_init, allow_zero=True)
    val.require_positive("C_boundary", c_boundary, allow_zero=True)
    val.require_positive("time", t_time, allow_zero=True)
    val.require_positive("x_position", x_pos, allow_zero=True)
    val.require_positive("D_eff", d_eff)

    # P1.2 (PR #20 Round 2 review): mirror mf_t01.py — when `thickness` is
    # supplied, enforce > 0. thickness=NaN/0/-1/inf previously slipped
    # through; the semi-infinite assumption needs a positive slab depth.
    # `thickness` remains optional (None == not provided).
    if thickness is not None:
        val.require_positive("thickness", thickness, allow_zero=False)

    # Sanity warnings using yaml notes range
    if isinstance(d_eff, (int, float)) and not isinstance(d_eff, bool) and d_eff > 0:
        if d_eff > 1e-7 or d_eff < 1e-13:
            val.issues.append(
                f"D_eff={d_eff} m²/s outside typical food range "
                f"(water 1e-12–1e-9, aroma 1e-11–1e-8); double-check input"
            )

    value: float | None = None
    if (
        all(isinstance(p, (int, float)) and not isinstance(p, bool)
            for p in (c_init, c_boundary, t_time, x_pos, d_eff))
        and t_time >= 0 and x_pos >= 0 and d_eff > 0
        and c_init >= 0 and c_boundary >= 0
    ):
        if t_time == 0:
            value = float(c_init)
            assumptions.append("t = 0 → returns C_init")
        else:
            arg = x_pos / (2.0 * math.sqrt(d_eff * t_time))
            value = float(c_init) + (float(c_boundary) - float(c_init)) * math.erfc(arg)

    # Semi-infinite check (penetration-depth heuristic). Only run when
    # thickness is a positive finite number — otherwise NaN/inf could
    # accidentally satisfy `x_pos > thickness` or skew penetration math.
    if (
        isinstance(thickness, (int, float)) and not isinstance(thickness, bool)
        and math.isfinite(thickness) and thickness > 0
        and isinstance(x_pos, (int, float)) and not isinstance(x_pos, bool)
        and isinstance(t_time, (int, float)) and not isinstance(t_time, bool)
        and isinstance(d_eff, (int, float)) and not isinstance(d_eff, bool)
    ):
        if x_pos > thickness:
            val.issues.append(
                f"x_position={x_pos} m exceeds slab thickness={thickness} m"
            )
        elif t_time > 0 and thickness > 0 and d_eff > 0:
            penetration = 2.0 * math.sqrt(d_eff * t_time)
            if penetration >= thickness / 2.0:
                val.issues.append(
                    f"semi-infinite assumption violated: penetration depth "
                    f"≈ {penetration:.3e} m ≥ thickness/2 = {thickness/2:.3e} m"
                )

    inputs_used = {"C_init": c_init, "C_boundary": c_boundary,
                   "time": t_time, "x_position": x_pos, "D_eff": d_eff}
    if thickness is not None:
        inputs_used["thickness"] = thickness

    return build_result(
        value=value if value is not None else float("nan"),
        unit="kg/m³ or mol/m³ (matches input)",
        symbol="C(x,t)",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used=inputs_used,
    )
