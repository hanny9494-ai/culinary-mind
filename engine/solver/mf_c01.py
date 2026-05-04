"""MF-C01 Stokes_Sedimentation — terminal velocity of a small sphere.

Formula:
    v = 2 · r² · (rho_p - rho_f) · g / (9 · eta)

References:
    - Stokes terminal-velocity relation.
    - fluids.v_terminal for positive-density-contrast settling at standard g.

Inputs:
    r [m], rho_p [kg/m³], rho_f [kg/m³], eta or mu [Pa·s], optional g.

Assumptions:
    - spherical particle
    - dilute suspension
    - Stokes regime Re < 0.5
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result

try:
    from fluids import v_terminal as _fluids_v_terminal
except ImportError:  # pragma: no cover
    _fluids_v_terminal = None


def solve(params: dict) -> dict:
    """Compute signed terminal velocity in m/s."""
    val = Validator()
    assumptions: list[str] = [
        "spherical particle",
        "dilute suspension",
        "Stokes laminar regime",
    ]

    radius = params.get("r")
    rho_p = params.get("rho_p")
    rho_f = params.get("rho_f")
    eta = params.get("eta", params.get("mu"))
    g = params.get("g", 9.81)

    val.require_positive("r", radius)
    val.require_positive("rho_p", rho_p)
    val.require_positive("rho_f", rho_f)
    val.require_positive("eta", eta)
    val.require_positive("g", g)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (radius, rho_p, rho_f, eta, g))
        and all(math.isfinite(float(x)) for x in (radius, rho_p, rho_f, eta, g))
        and radius > 0.0 and rho_p > 0.0 and rho_f > 0.0 and eta > 0.0 and g > 0.0
    ):
        if rho_p > rho_f and _fluids_v_terminal is not None and math.isclose(float(g), 9.81, rel_tol=5e-4):
            try:
                value = float(_fluids_v_terminal(D=2.0 * float(radius),
                                                 rhop=float(rho_p),
                                                 rho=float(rho_f),
                                                 mu=float(eta),
                                                 Method="Stokes"))
                assumptions.append("using fluids.v_terminal Method='Stokes' (Re<<1 assumed)")
            except Exception as exc:
                assumptions.append(f"fluids unavailable ({exc}), using analytical Stokes formula")
        if value is None:
            value = 2.0 * float(radius) ** 2 * (float(rho_p) - float(rho_f)) * float(g) / (9.0 * float(eta))
            if rho_p < rho_f:
                assumptions.append("rho_p < rho_f → negative velocity indicates creaming/upward motion")
            elif math.isclose(float(rho_p), float(rho_f), rel_tol=1e-12, abs_tol=1e-12):
                assumptions.append("rho_p = rho_f → neutral buoyancy")

        reynolds = float(rho_f) * abs(value) * (2.0 * float(radius)) / float(eta)
        if reynolds >= 0.5:
            val.issues.append(f"Stokes regime violated: Re={reynolds:.3g} >= 0.5")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="m/s",
        symbol="v",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"r": radius, "rho_p": rho_p, "rho_f": rho_f, "eta": eta, "g": g},
    )
