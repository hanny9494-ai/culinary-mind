"""MF-C02 HLB_Griffin — Griffin hydrophile-lipophile balance.

Formula:
    HLB = 20 · M_h / (M_h + M_l)

References:
    - Griffin HLB mass-fraction rule; pure algebra per D65.

Inputs:
    M_h hydrophilic mass, M_l lipophilic mass. Alias M may be used for total
    mass; then M_l = M - M_h.

Assumptions:
    - nonionic surfactant
    - masses are on a consistent basis
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result


def solve(params: dict) -> dict:
    """Compute Griffin HLB."""
    val = Validator()
    assumptions: list[str] = ["Griffin nonionic surfactant HLB"]

    m_h = params.get("M_h", params.get("Mh"))
    if "M_l" in params or "Ml" in params:
        m_l = params.get("M_l", params.get("Ml"))
    else:
        total = params.get("M")
        m_l = None
        if total is not None and isinstance(m_h, (int, float)) and not isinstance(m_h, bool):
            m_l = total - m_h
            assumptions.append("computed M_l = M - M_h")

    val.require_positive("M_h", m_h, allow_zero=True)
    val.require_positive("M_l", m_l, allow_zero=True)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (m_h, m_l))
        and all(math.isfinite(float(x)) for x in (m_h, m_l))
        and m_h >= 0.0 and m_l >= 0.0
    ):
        total_mass = float(m_h) + float(m_l)
        if total_mass <= 0.0:
            val.issues.append("M_h + M_l must be > 0")
        else:
            value = 20.0 * float(m_h) / total_mass
            if math.isclose(float(m_h), float(m_l), rel_tol=1e-12, abs_tol=1e-12):
                assumptions.append("M_h = M_l → HLB = 10")
            if value >= 8.0:
                assumptions.append("HLB in typical oil-in-water emulsifier range")
            elif value <= 6.0:
                assumptions.append("HLB in typical water-in-oil/antifoam range")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="dimensionless",
        symbol="HLB",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"M_h": m_h, "M_l": m_l},
    )
