"""Shared helpers for the engine.solver MF tools.

Each solver returns a dict shaped like:

    {
        "result":        {"value": <float>, "unit": <str>, "symbol": <str>},
        "assumptions":   ["<plain-text assumption 1>", ...],
        "validity":      {"passed": <bool>, "issues": [<str>, ...]},
        "inputs_used":   {<echo of params actually consumed>},
    }

`validity.passed` is True when no `issues` were appended. `assumptions`
documents anything the solver decided on the caller's behalf
(e.g. "semi-infinite slab", "computed alpha from k/rho/Cp").

We also expose a tiny `Validator` helper used by every solver so the
range / sign checks read consistently.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

ABSOLUTE_ZERO_C = -273.15


# ── Validator ───────────────────────────────────────────────────────────────

class Validator:
    """Accumulates issues; final `result()` returns `{passed, issues}`.

    Methods follow a `require_*` naming convention. They return the
    Validator for chaining and DO NOT raise — solvers can keep going
    even with violations and let the caller decide what to do with a
    `validity.passed == False` response.
    """

    def __init__(self) -> None:
        self.issues: list[str] = []

    def require_finite(self, name: str, value: Any) -> "Validator":
        # P2.1 (PR #20 D69 review): reject bool explicitly. `True`/`False` are
        # subclasses of `int`, so the previous isinstance(value, (int, float))
        # check let `True`/`False` pass as numeric. Use math.isfinite for the
        # NaN/inf case — clearer than `value != value or value in (inf, -inf)`.
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            self.issues.append(f"{name} must be finite, got {value!r}")
        return self

    def require_positive(self, name: str, value: Any, *,
                         allow_zero: bool = False) -> "Validator":
        self.require_finite(name, value)
        # Mirror the bool/finite guard so we don't run comparisons on dud values.
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and math.isfinite(value):
            if allow_zero and value < 0:
                self.issues.append(f"{name} must be ≥ 0 (got {value})")
            elif not allow_zero and value <= 0:
                self.issues.append(f"{name} must be > 0 (got {value})")
        return self

    def require_in_range(self, name: str, value: Any,
                         lo: float, hi: float, *,
                         hint: str = "") -> "Validator":
        self.require_finite(name, value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and math.isfinite(value):
            if value < lo or value > hi:
                tail = f" — {hint}" if hint else ""
                self.issues.append(
                    f"{name}={value} outside applicable range [{lo}, {hi}]{tail}"
                )
        return self

    def require_temperature_celsius(self, name: str, value: Any) -> "Validator":
        self.require_finite(name, value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and math.isfinite(value):
            if value < ABSOLUTE_ZERO_C:
                self.issues.append(
                    f"{name}={value}°C below absolute zero "
                    f"({ABSOLUTE_ZERO_C}°C)"
                )
        return self

    def warn_if(self, condition: bool, message: str) -> "Validator":
        if condition:
            self.issues.append(message)
        return self

    def result(self) -> dict[str, Any]:
        return {"passed": len(self.issues) == 0, "issues": list(self.issues)}


# ── Result builder ──────────────────────────────────────────────────────────

def build_result(*,
                 value: float,
                 unit: str,
                 symbol: str,
                 assumptions: Iterable[str],
                 validity: dict,
                 inputs_used: dict) -> dict:
    return {
        "result":      {"value": value, "unit": unit, "symbol": symbol},
        "assumptions": list(assumptions),
        "validity":    validity,
        "inputs_used": dict(inputs_used),
    }
