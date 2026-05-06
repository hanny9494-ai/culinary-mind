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


# ── Bounds Validator ────────────────────────────────────────────────────────
import functools
import warnings
from pathlib import Path
from typing import Callable

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - exercised only without dependency
    _yaml = None

_BOUNDS_CACHE: dict = {}
_BOUNDS_PATH = Path(__file__).resolve().parents[2] / "config" / "solver_bounds.yaml"
_MISSING_BOUNDS_WARNED: set[str] = set()
_COMPOSITION_ALIAS_BOUND_NAMES = {"Xw", "Xp", "Xf", "Xc", "Xfiber", "Xa"}


def _load_bounds() -> dict:
    """Load solver_bounds.yaml lazily. Returns {mf_id: solver_spec}."""
    global _BOUNDS_CACHE
    if _BOUNDS_CACHE:
        return _BOUNDS_CACHE
    if _yaml is None:
        warnings.warn(
            "PyYAML not installed; @validate_bounds is a no-op",
            RuntimeWarning,
            stacklevel=2,
        )
        _BOUNDS_CACHE = {"_disabled": True}
        return _BOUNDS_CACHE
    if not _BOUNDS_PATH.exists():
        warnings.warn(
            f"solver_bounds.yaml missing at {_BOUNDS_PATH}; "
            "@validate_bounds is a no-op",
            RuntimeWarning,
            stacklevel=2,
        )
        _BOUNDS_CACHE = {"_disabled": True}
        return _BOUNDS_CACHE
    try:
        data = _yaml.safe_load(_BOUNDS_PATH.read_text(encoding="utf-8"))
        _BOUNDS_CACHE = data.get("solvers", {})
    except Exception as exc:
        warnings.warn(
            f"Failed to load solver_bounds.yaml: {exc}; "
            "@validate_bounds is a no-op",
            RuntimeWarning,
            stacklevel=2,
        )
        _BOUNDS_CACHE = {"_disabled": True}
    return _BOUNDS_CACHE


def _check_param_bound(value: Any, spec: dict, val: Validator, name: str, *,
                       require_finite: bool = False) -> None:
    """Append issue if value violates spec.min/max.

    Soft bounds emit a WARN-prefixed issue, which does not fail validity.
    """
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        if require_finite:
            val.issues.append(f"{name} must be finite, got {value!r}")
        return

    lo = spec.get("min")
    hi = spec.get("max")
    soft = spec.get("soft", False)
    out_of_range = False
    if lo is not None and value < lo:
        out_of_range = True
    if hi is not None and value > hi:
        out_of_range = True
    if out_of_range:
        msg = f"{name}={value} outside bounds [{lo}, {hi}] {spec.get('unit', '')}"
        if soft:
            val.issues.append(
                f"WARN: {msg} (soft bound; result may be extrapolated)"
            )
        else:
            val.issues.append(msg)


def _resolve_dotted(params: dict, dotted: str) -> Any:
    """Resolve 'composition.water' -> params['composition']['water']."""
    cur = params
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _composition_value_for_bounds(params: dict, dotted: str, value: Any) -> Any:
    """Normalize obvious 0-100 composition percentages for bounds checks."""
    if not dotted.startswith("composition."):
        return value
    comp = params.get("composition")
    if not isinstance(comp, dict):
        return value
    numbers = [
        float(v)
        for v in comp.values()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
        and math.isfinite(v)
    ]
    total = sum(numbers)
    if total > 10.0 and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) / total
    return value


def _ratio_value_for_bounds(params: dict, name: str, value: Any) -> Any:
    """Normalize obvious non-fraction two-part weights for bounds checks."""
    if name not in {"w1", "w2"}:
        return value
    other = "w2" if name == "w1" else "w1"
    other_value = params.get(other)
    if not (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and isinstance(other_value, (int, float)) and not isinstance(other_value, bool)
        and math.isfinite(value) and math.isfinite(other_value)
    ):
        return value
    total = float(value) + float(other_value)
    if total > 0.0 and value >= 0.0 and other_value >= 0.0:
        return float(value) / total
    return value


def _scalar_composition_alias_value_for_bounds(params: dict, name: str,
                                               value: Any) -> Any:
    """Normalize T02 scalar composition aliases that are supplied as percents."""
    if name not in _COMPOSITION_ALIAS_BOUND_NAMES:
        return value
    numbers = [
        float(params[alias])
        for alias in _COMPOSITION_ALIAS_BOUND_NAMES
        if alias in params
        and isinstance(params[alias], (int, float))
        and not isinstance(params[alias], bool)
        and math.isfinite(params[alias])
    ]
    total = sum(numbers)
    if total > 10.0 and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) / total
    return value


def _resolve_param_value(params: dict, name: str) -> Any:
    """Resolve direct, dotted, and derived bound parameters."""
    if name == "T_minus_Tg" and name not in params:
        temp = params.get("T")
        tg = params.get("Tg")
        if (
            isinstance(temp, (int, float)) and not isinstance(temp, bool)
            and isinstance(tg, (int, float)) and not isinstance(tg, bool)
            and math.isfinite(temp) and math.isfinite(tg)
        ):
            return float(temp) - float(tg)
        return None
    if "." in name:
        value = _resolve_dotted(params, name)
        return _composition_value_for_bounds(params, name, value)
    value = params.get(name)
    value = _scalar_composition_alias_value_for_bounds(params, name, value)
    return _ratio_value_for_bounds(params, name, value)


def _warn_missing_bounds_once(mf_id: str) -> None:
    if mf_id in _MISSING_BOUNDS_WARNED:
        return
    _MISSING_BOUNDS_WARNED.add(mf_id)
    warnings.warn(
        f"bounds metadata missing for {mf_id}; @validate_bounds is a no-op",
        RuntimeWarning,
        stacklevel=3,
    )


def validate_bounds(mf_id: str, *, output_variant: str | None = None):
    """Decorator wrapping solver.solve(params) with automatic bounds checks.

    Usage:
        @validate_bounds("MF-T01")
        def solve(params: dict) -> dict: ...

    For multi-output T02 split:
        @validate_bounds("MF-T02", output_variant="mf_t02_k")
        def solve(params: dict) -> dict: ...

    Behavior:
        - Pre-call: load bounds.yaml[mf_id]; for each input spec, check params
          value against [min, max]. Soft bounds emit "WARN:" issues.
        - Post-call: check returned result.value against output bounds.
        - Failure mode: append val.issues, never raise.
        - Soft fallback: missing yaml / missing mf_id / yaml-load error
          becomes no-op + RuntimeWarning.
    """
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(params: dict) -> dict:
            bounds = _load_bounds()
            spec = bounds.get(mf_id, {}) if not bounds.get("_disabled") else {}
            if not spec and not bounds.get("_disabled"):
                _warn_missing_bounds_once(mf_id)

            pre_issues: list[str] = []
            for inp in spec.get("inputs", []) or []:
                name = inp["name"]
                value = _resolve_param_value(params, name)
                if value is None:
                    continue
                tmp_val = Validator()
                _check_param_bound(value, inp, tmp_val, name)
                pre_issues.extend(tmp_val.issues)

            result = fn(params)

            if "validity" in result and isinstance(result["validity"], dict):
                existing = list(result["validity"].get("issues", []))
                existing.extend(pre_issues)

                out_spec = None
                if output_variant and "outputs_by_variant" in spec:
                    out_spec = spec["outputs_by_variant"].get(output_variant)
                else:
                    out_spec = spec.get("output")

                if out_spec and "result" in result and "value" in result["result"]:
                    val_check = result["result"]["value"]
                    tmp = Validator()
                    _check_param_bound(
                        val_check,
                        out_spec,
                        tmp,
                        out_spec.get("symbol", "result.value"),
                        require_finite=True,
                    )
                    existing.extend(tmp.issues)

                result["validity"]["issues"] = existing
                result["validity"]["passed"] = not any(
                    not issue.startswith("WARN:") for issue in existing
                )

            return result
        return wrapper
    return deco
