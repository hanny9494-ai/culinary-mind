"""Shared helpers for the engine.solver MF tools.

Each solver returns a dict shaped like:

    {
        "result":        {"value": <float>, "unit": <str>, "symbol": <str>},
        "assumptions":   ["<plain-text assumption 1>", ...],
        "validity":      {"passed": <bool>, "issues": [<str>, ...]},
        "inputs_used":   {<echo of params actually consumed>},
        "provenance":    {<optional tool/source metadata>},
        "llm_summary":   {<optional compact summary for agent/tool wrappers>},
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
                 inputs_used: dict,
                 provenance: dict | None = None,
                 llm_summary: dict | None = None) -> dict:
    out = {
        "result":      {"value": value, "unit": unit, "symbol": symbol},
        "assumptions": list(assumptions),
        "validity":    validity,
        "inputs_used": dict(inputs_used),
    }
    if provenance is not None:
        out["provenance"] = dict(provenance)
    if llm_summary is not None:
        out["llm_summary"] = dict(llm_summary)
    return out


def provenance_for(*,
                   tool_id: str,
                   tool_canonical_name: str,
                   tool_version: str = "1.0",
                   citations: list[str] | None = None,
                   ckg_node_refs: list[dict] | None = None) -> dict:
    """Build standard provenance dict for an MF solver response.

    By default, the solver references its D66 v2 MF node using the lowercase
    namespace form, e.g. `MF-T01` → `{"label": "CKG_MF", "mf_id": "mf_t01"}`.
    """
    if ckg_node_refs is None:
        mf_id_lower = tool_id.lower().replace("-", "_")
        ckg_node_refs = [{"label": "CKG_MF", "mf_id": mf_id_lower}]

    return {
        "tool_id": tool_id,
        "tool_canonical_name": tool_canonical_name,
        "tool_version": tool_version,
        "citations": list(citations or []),
        "ckg_node_refs": list(ckg_node_refs),
    }


def llm_summary_for(*,
                    value: float,
                    unit: str,
                    symbol: str,
                    tool_canonical_name: str,
                    tool_id: str,
                    summary_zh: str | None = None,
                    summary_en: str | None = None,
                    confidence: float | None = None,
                    extra_outputs: dict | None = None) -> dict:
    """Build a compact LLM-facing summary for a solver response.

    If caller-provided summaries are omitted, the default templates are:
    zh: "{tool_canonical_name} 计算 {symbol} = {value:.4g} {unit}"
    en: "{tool_canonical_name} computed {symbol} = {value:.4g} {unit}"
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value):
            value_str = f"{value:.4g}"
        elif math.isnan(value):
            value_str = "NaN"
        else:
            value_str = "Inf" if value > 0 else "-Inf"
    else:
        value_str = repr(value)

    if summary_zh is None:
        summary_zh = (
            f"{tool_canonical_name} 计算 {symbol} = {value_str} {unit}"
        ).strip()
    if summary_en is None:
        summary_en = (
            f"{tool_canonical_name} computed {symbol} = {value_str} {unit}"
        ).strip()

    key_outputs = {"value": value, "unit": unit, "symbol": symbol}
    if extra_outputs:
        key_outputs.update(extra_outputs)

    return {
        "summary_zh": summary_zh,
        "summary_en": summary_en,
        "key_outputs": key_outputs,
        "confidence": confidence,
    }
