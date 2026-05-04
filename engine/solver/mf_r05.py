"""MF-R05 WLF_Equation — Williams-Landel-Ferry shift factor.

Formula:
    log10(aT) = -C1 · (T - Tg) / (C2 + (T - Tg))

References:
    - Williams-Landel-Ferry equation; pure algebra per D65.

Inputs:
    T, Tg, optional C1=17.44, C2=51.6.

Assumptions:
    - T and Tg use a consistent °C/K interval scale
    - default constants are referenced to Tg
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result


def solve(params: dict) -> dict:
    """Compute WLF shift factor aT."""
    val = Validator()
    assumptions: list[str] = [
        "WLF constants referenced to Tg",
        "temperature difference T - Tg uses °C/K interval units",
    ]

    temp = params.get("T")
    tg = params.get("Tg")
    c1 = params.get("C1", 17.44)
    c2 = params.get("C2", 51.6)

    val.require_temperature_celsius("T", temp)
    val.require_temperature_celsius("Tg", tg)
    val.require_positive("C1", c1)
    val.require_positive("C2", c2)

    value: float | None = None
    if (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (temp, tg, c1, c2))
        and all(math.isfinite(float(x)) for x in (temp, tg, c1, c2))
        and c1 > 0.0 and c2 > 0.0
    ):
        delta = float(temp) - float(tg)
        denom = float(c2) + delta
        if denom <= 0.0:
            val.issues.append("C2 + (T - Tg) must be > 0 for WLF")
        else:
            log10_at = -float(c1) * delta / denom
            value = 10.0 ** log10_at
            if math.isclose(delta, 0.0, abs_tol=1e-12):
                assumptions.append("T = Tg → aT = 1")
            if delta < 0.0 or delta > 100.0:
                assumptions.append("outside common WLF range Tg <= T <= Tg + 100")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="dimensionless",
        symbol="aT",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"T": temp, "Tg": tg, "C1": c1, "C2": c2},
    )
