"""Shared Hypothesis strategies for MF solver property-based tests."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from hypothesis import strategies as st


_BOUNDS_PATH = Path(__file__).resolve().parents[3] / "config" / "solver_bounds.yaml"
_BOUNDS = yaml.safe_load(_BOUNDS_PATH.read_text(encoding="utf-8"))["solvers"]

COMPONENTS = ("water", "protein", "fat", "carb", "fiber", "ash")


def bounds_for(mf_id: str) -> dict[str, Any]:
    """Get bounds metadata for one solver."""
    return _BOUNDS[mf_id]


def input_spec_for(mf_id: str, param_name: str) -> dict[str, Any]:
    """Get one input-bound spec by parameter name."""
    for item in bounds_for(mf_id).get("inputs", []):
        if item["name"] == param_name:
            return item
    raise KeyError(f"{param_name!r} not found in bounds for {mf_id}")


def output_bounds_for(mf_id: str, *, variant: str | None = None) -> dict[str, Any]:
    """Get output-bound metadata, including split-output variants."""
    spec = bounds_for(mf_id)
    if variant is not None:
        return spec["outputs_by_variant"][variant]
    return spec["output"]


def float_in_bounds(
    mf_id: str,
    param_name: str,
    *,
    margin: float = 0.01,
) -> st.SearchStrategy[float]:
    """Finite float strategy derived from solver_bounds.yaml.

    ``margin`` shrinks both sides of closed finite ranges to avoid exact
    singularities while still sampling the physical envelope.
    """
    spec = input_spec_for(mf_id, param_name)
    lo = spec.get("min")
    hi = spec.get("max")
    if lo is not None and hi is not None:
        span = float(hi) - float(lo)
        return st.floats(
            min_value=float(lo) + margin * span,
            max_value=float(hi) - margin * span,
            allow_nan=False,
            allow_infinity=False,
        )
    if lo is not None:
        return st.floats(
            min_value=float(lo),
            max_value=float(lo) + 1.0e6,
            allow_nan=False,
            allow_infinity=False,
        )
    if hi is not None:
        return st.floats(
            min_value=float(hi) - 1.0e6,
            max_value=float(hi),
            allow_nan=False,
            allow_infinity=False,
        )
    return st.floats(
        min_value=-1.0e6,
        max_value=1.0e6,
        allow_nan=False,
        allow_infinity=False,
    )


def near_boundary(
    mf_id: str,
    param_name: str,
    *,
    side: str = "above_min",
    epsilon: float | None = None,
) -> st.SearchStrategy[float]:
    """Generate finite floats just inside or just outside a configured bound."""
    spec = input_spec_for(mf_id, param_name)
    lo = spec.get("min")
    hi = spec.get("max")

    if epsilon is None:
        bound = lo if side in {"above_min", "below_min"} else hi
        other = hi if side in {"above_min", "below_min"} else lo
        if bound is None:
            raise ValueError(f"{param_name!r} has no bound for {side}")
        bound_value = float(bound)
        if side in {"above_min", "below_min"} and bound_value > 0.0:
            epsilon = bound_value * 0.5
        elif bound_value != 0.0:
            epsilon = abs(bound_value) * 1.0e-6
        else:
            epsilon = 1.0e-6
        if other is not None:
            epsilon = min(float(epsilon), abs(float(other) - bound_value) * 1.0e-6)
    gap = max(float(epsilon) * 1.0e-6, 1.0e-300)

    if side == "above_min":
        if lo is None:
            raise ValueError(f"{param_name!r} has no lower bound")
        return st.floats(
            min_value=float(lo) + gap,
            max_value=float(lo) + float(epsilon),
            allow_nan=False,
            allow_infinity=False,
        )
    if side == "below_min":
        if lo is None:
            raise ValueError(f"{param_name!r} has no lower bound")
        return st.floats(
            min_value=float(lo) - float(epsilon),
            max_value=float(lo) - gap,
            allow_nan=False,
            allow_infinity=False,
        )
    if side == "below_max":
        if hi is None:
            raise ValueError(f"{param_name!r} has no upper bound")
        return st.floats(
            min_value=float(hi) - float(epsilon),
            max_value=float(hi) - gap,
            allow_nan=False,
            allow_infinity=False,
        )
    if side == "above_max":
        if hi is None:
            raise ValueError(f"{param_name!r} has no upper bound")
        return st.floats(
            min_value=float(hi) + gap,
            max_value=float(hi) + float(epsilon),
            allow_nan=False,
            allow_infinity=False,
        )
    raise ValueError(f"unknown side {side!r}")


def log_float(min_exponent: float, max_exponent: float) -> st.SearchStrategy[float]:
    """Positive finite float sampled uniformly over base-10 exponents."""
    return st.floats(
        min_value=min_exponent,
        max_value=max_exponent,
        allow_nan=False,
        allow_infinity=False,
    ).map(lambda exponent: 10.0 ** exponent)


@st.composite
def composition_fractions(
    draw: st.DrawFn,
    *,
    min_weight: float = 1.0e-3,
) -> dict[str, float]:
    """Generate a normalized six-component proximate composition."""
    weights = [
        draw(
            st.floats(
                min_value=min_weight,
                max_value=1.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        for _ in COMPONENTS
    ]
    total = sum(weights)
    return {name: value / total for name, value in zip(COMPONENTS, weights)}


@st.composite
def ordered_float_pair(
    draw: st.DrawFn,
    *,
    min_value: float,
    max_value: float,
) -> tuple[float, float]:
    """Generate a finite pair sorted in nondecreasing order."""
    a = draw(
        st.floats(
            min_value=min_value,
            max_value=max_value,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    b = draw(
        st.floats(
            min_value=min_value,
            max_value=max_value,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    return (a, b) if a <= b else (b, a)


def assert_solver_contract(testcase: Any, out: dict[str, Any]) -> None:
    """Check the P1-17/P1-22 solver response fields still exist."""
    for key in ("result", "assumptions", "validity", "inputs_used"):
        testcase.assertIn(key, out)
    testcase.assertIn("provenance", out)
    testcase.assertIn("llm_summary", out)

    provenance = out["provenance"]
    testcase.assertIsInstance(provenance, dict)
    for key in ("tool_id", "tool_canonical_name", "tool_version", "citations", "ckg_node_refs"):
        testcase.assertIn(key, provenance)

    llm_summary = out["llm_summary"]
    testcase.assertIsInstance(llm_summary, dict)
    for key in ("summary_zh", "summary_en", "key_outputs"):
        testcase.assertIn(key, llm_summary)
    testcase.assertIsInstance(llm_summary["key_outputs"], dict)
    for key in ("value", "unit", "symbol"):
        testcase.assertIn(key, llm_summary["key_outputs"])
