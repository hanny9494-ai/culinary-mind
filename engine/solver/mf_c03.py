"""MF-C03 DLVO_Theory — simplified colloidal interaction potential.

Formula:
    V_T(D) = V_A(D) + V_R(D)
    V_A = -A_H · r / (12D)
    V_R = 64π ε0 εr r (kB T/e)^2 tanh(e ζ/(4kB T))^2 exp(-κD)

References:
    - DLVO van der Waals attraction plus electrostatic double-layer repulsion.
    - scipy.constants for physical constants.

Inputs:
    A_H [J], kappa [1/m], zeta [V], epsilon [relative permittivity],
    T [K], D [m], optional r [m] particle radius (default 1 µm).

Assumptions:
    - equal spherical particles represented by a Derjaguin approximation
    - symmetric electrolyte and constant surface potential
"""

from __future__ import annotations

import math
from typing import Any

from scipy import constants as _constants

from ._common import Validator, build_result, llm_summary_for, provenance_for, validate_bounds


TOOL_ID = 'MF-C03'
TOOL_CANONICAL_NAME = 'DLVO_Theory'
CITATIONS = [
    'Sahin & Sumnu, Physical Properties of Foods Ch.6',
    'Fennema, Food Chemistry Ch.13',
]



@validate_bounds("MF-C03")
def solve(params: dict) -> dict:
    """Compute simplified DLVO interaction energy in J."""
    val = Validator()
    assumptions: list[str] = [
        "Derjaguin equal-sphere approximation",
        "constant surface potential",
    ]

    hamaker = params.get("A_H", params.get("A_hamaker"))
    kappa = params.get("kappa")
    zeta = params.get("zeta")
    epsilon_r = params.get("epsilon", params.get("epsilon_r"))
    temp_k = params.get("T", params.get("T_K"))
    distance = params.get("D")
    radius = params.get("r", 1.0e-6)
    if "r" not in params:
        assumptions.append("particle radius omitted → r=1 µm")

    val.require_positive("A_H", hamaker)
    val.require_positive("kappa", kappa)
    val.require_finite("zeta", zeta)
    val.require_positive("epsilon", epsilon_r)
    val.require_positive("T", temp_k)
    val.require_positive("D", distance)
    val.require_positive("r", radius)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (hamaker, kappa, zeta, epsilon_r, temp_k, distance, radius))
        and all(math.isfinite(float(x)) for x in (hamaker, kappa, zeta, epsilon_r, temp_k, distance, radius))
        and hamaker > 0.0 and kappa > 0.0 and epsilon_r > 0.0
        and temp_k > 0.0 and distance > 0.0 and radius > 0.0
    ):
        thermal_voltage = _constants.k * float(temp_k) / _constants.e
        gamma = math.tanh(float(zeta) / (4.0 * thermal_voltage))
        v_attractive = -float(hamaker) * float(radius) / (12.0 * float(distance))
        v_repulsive = (
            64.0 * math.pi * _constants.epsilon_0 * float(epsilon_r) * float(radius)
            * thermal_voltage ** 2 * gamma ** 2 * math.exp(-float(kappa) * float(distance))
        )
        value = v_attractive + v_repulsive
        if zeta == 0.0:
            assumptions.append("zeta = 0 → no electrostatic repulsion term")
        elif value > 0.0:
            assumptions.append("positive DLVO energy barrier")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="J",
        symbol="V_T",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={
            "A_H": hamaker, "kappa": kappa, "zeta": zeta, "epsilon": epsilon_r,
            "T": temp_k, "D": distance, "r": radius,
        },
        provenance=provenance_for(
            tool_id=TOOL_ID,
            tool_canonical_name=TOOL_CANONICAL_NAME,
            citations=CITATIONS,
        ),
        llm_summary=llm_summary_for(
            value=value if value is not None else float("nan"),
            unit="J",
            symbol="V_T",
            tool_canonical_name=TOOL_CANONICAL_NAME,
            tool_id=TOOL_ID,
        ),
    )
