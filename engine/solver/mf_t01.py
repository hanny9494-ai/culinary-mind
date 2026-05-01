"""MF-T01 Fourier_1D — 1D unsteady heat conduction.

PDE:
    ∂T/∂t = α · ∂²T/∂x²

We expose an analytical *semi-infinite slab* solution with a step
temperature change at the surface (boundary fixed at `T_boundary`,
initial uniform `T_init`):

    T(x, t) = T_init + (T_boundary - T_init) · erfc( x / (2·√(α·t)) )

This is the simplest atomic-tool form of Fourier's law. It assumes:
  • semi-infinite slab (probe far from far-side boundary)
  • constant α (no temperature dependence)
  • step boundary at t = 0
  • 1D heat flow

Inputs (per `config/mother_formulas.yaml` → MF-T01):
  Runtime variables (SI): T_init, T_boundary [°C], thickness [m] (used
  only to validate semi-infinite assumption), time [s], x_position [m].
  One-of-inputs (provide either):
      ['alpha']                        — m²/s
      ['k', 'rho', 'Cp']               — derives α = k / (ρ · Cp)
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result


def _resolve_alpha(params: dict, val: Validator,
                   assumptions: list[str]) -> tuple[float | None, dict]:
    """Return (alpha, inputs_consumed). Mutates val + assumptions."""
    if "alpha" in params:
        a = params["alpha"]
        val.require_positive("alpha", a)
        return a, {"alpha": a}
    needed = ("k", "rho", "Cp")
    if all(p in params for p in needed):
        k, rho, cp = params["k"], params["rho"], params["Cp"]
        for n, v in (("k", k), ("rho", rho), ("Cp", cp)):
            val.require_positive(n, v)
        if all(isinstance(x, (int, float)) and x > 0 for x in (k, rho, cp)):
            a = k / (rho * cp)
            assumptions.append(
                f"computed thermal diffusivity α = k/(ρ·Cp) = "
                f"{k}/({rho}·{cp}) = {a:.4e} m²/s"
            )
            return a, {"k": k, "rho": rho, "Cp": cp}
        return None, {"k": k, "rho": rho, "Cp": cp}
    val.issues.append(
        "must provide either 'alpha' or all of (k, rho, Cp); "
        "see config/mother_formulas.yaml MF-T01.one_of_inputs"
    )
    return None, {}


def solve(params: dict) -> dict:
    """Compute T(x, t) for a semi-infinite slab heated at the surface.

    Required runtime params:
        T_init        °C   uniform initial temperature
        T_boundary    °C   surface temperature held constant for t > 0
        time          s    elapsed time since boundary step (≥ 0)
        x_position    m    depth from the surface (≥ 0)
    Optional:
        thickness     m    slab thickness (for semi-infinite check only;
                           solver warns if x_position > thickness)
        dx            m    accepted but unused — analytical mode skips
                           finite-difference discretisation.
    Plus one of:
        alpha         m²/s
        OR (k, rho, Cp) — α = k/(ρ·Cp)
    """
    val = Validator()
    assumptions: list[str] = ["semi-infinite slab", "step boundary at t=0",
                              "constant α", "1D heat flow"]

    # Runtime
    t_init      = params.get("T_init")
    t_boundary  = params.get("T_boundary")
    t_time      = params.get("time")
    x_pos       = params.get("x_position")
    thickness   = params.get("thickness")

    val.require_temperature_celsius("T_init", t_init)
    val.require_temperature_celsius("T_boundary", t_boundary)
    val.require_positive("time", t_time, allow_zero=True)
    val.require_positive("x_position", x_pos, allow_zero=True)

    # Applicable_range from yaml: T ∈ [-40, 300] °C
    for name, v in (("T_init", t_init), ("T_boundary", t_boundary)):
        if isinstance(v, (int, float)):
            val.require_in_range(name, v, -40, 300,
                                 hint="MF-T01 applicable_range")

    # Material props
    alpha, inputs_consumed = _resolve_alpha(params, val, assumptions)

    # Compute
    value: float | None = None
    if (
        alpha is not None
        and all(isinstance(p, (int, float)) for p in (t_init, t_boundary, t_time, x_pos))
        and t_time >= 0 and x_pos >= 0 and alpha > 0
    ):
        if t_time == 0:
            value = float(t_init)
            assumptions.append("t = 0 → returns T_init")
        else:
            arg = x_pos / (2.0 * math.sqrt(alpha * t_time))
            value = float(t_init) + (float(t_boundary) - float(t_init)) * math.erfc(arg)

    # Semi-infinite check
    if isinstance(thickness, (int, float)) and isinstance(x_pos, (int, float)):
        if x_pos > thickness:
            val.issues.append(
                f"x_position={x_pos} m exceeds slab thickness={thickness} m"
            )
        elif (
            alpha is not None and isinstance(t_time, (int, float))
            and t_time > 0 and thickness > 0
        ):
            # Conservative: if penetration depth ~2·sqrt(α·t) ≥ thickness/2,
            # the semi-infinite assumption breaks down.
            penetration = 2.0 * math.sqrt(alpha * t_time)
            if penetration >= thickness / 2.0:
                val.issues.append(
                    f"semi-infinite assumption violated: penetration depth "
                    f"≈ {penetration:.3e} m ≥ thickness/2 = {thickness/2:.3e} m"
                )

    inputs_used = {"T_init": t_init, "T_boundary": t_boundary,
                   "time": t_time, "x_position": x_pos,
                   **inputs_consumed}
    if thickness is not None:
        inputs_used["thickness"] = thickness

    return build_result(
        value=value if value is not None else float("nan"),
        unit="°C",
        symbol="T(x,t)",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used=inputs_used,
    )
