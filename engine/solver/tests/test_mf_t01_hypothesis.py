"""P1-21b: Hypothesis property tests for MF-T01 Fourier_1D."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_t01
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    float_in_bounds,
    near_boundary,
    output_bounds_for,
)


class TestMFT01PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        T_init=float_in_bounds("MF-T01", "T_init"),
        T_boundary=float_in_bounds("MF-T01", "T_boundary"),
        time=float_in_bounds("MF-T01", "time"),
        x_position=float_in_bounds("MF-T01", "x_position"),
        alpha=float_in_bounds("MF-T01", "alpha"),
    )
    def test_in_bounds_inputs_return_finite_bounded_temperature(
        self, T_init: float, T_boundary: float, time: float, x_position: float, alpha: float
    ) -> None:
        out = mf_t01.solve({
            "T_init": T_init,
            "T_boundary": T_boundary,
            "time": time,
            "x_position": x_position,
            "alpha": alpha,
        })

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-T01")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])
        span_tol = max(1.0e-9, 1.0e-12 * max(abs(T_init), abs(T_boundary), 1.0))
        self.assertGreaterEqual(value, min(T_init, T_boundary) - span_tol)
        self.assertLessEqual(value, max(T_init, T_boundary) + span_tol)


class TestMFT01PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(T_init=near_boundary("MF-T01", "T_init", side="below_min"))
    def test_T_init_just_below_min_fails_validity(self, T_init: float) -> None:
        out = mf_t01.solve({
            "T_init": T_init,
            "T_boundary": 100.0,
            "time": 60.0,
            "x_position": 0.005,
            "alpha": 1.4e-7,
        })

        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(
            any("T_init" in issue and "outside bounds" in issue for issue in out["validity"]["issues"]),
            msg=out["validity"]["issues"],
        )

    @settings(max_examples=200, deadline=2000)
    @given(T_boundary=near_boundary("MF-T01", "T_boundary", side="above_max"))
    def test_T_boundary_just_above_max_fails_validity(self, T_boundary: float) -> None:
        out = mf_t01.solve({
            "T_init": 20.0,
            "T_boundary": T_boundary,
            "time": 60.0,
            "x_position": 0.005,
            "alpha": 1.4e-7,
        })

        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(
            any("T_boundary" in issue and "outside bounds" in issue for issue in out["validity"]["issues"]),
            msg=out["validity"]["issues"],
        )


class TestMFT01PropertyMonotonicity(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        T_init=st.floats(min_value=-30.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        T_boundary=st.floats(min_value=80.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        x_position=st.floats(min_value=0.0, max_value=0.05, allow_nan=False, allow_infinity=False),
        alpha=st.floats(min_value=1.0e-8, max_value=1.0e-6, allow_nan=False, allow_infinity=False),
    )
    def test_temperature_is_nondecreasing_in_time_when_heating(
        self, T_init: float, T_boundary: float, x_position: float, alpha: float
    ) -> None:
        values = []
        for time in (0.0, 1.0, 10.0, 60.0, 300.0):
            out = mf_t01.solve({
                "T_init": T_init,
                "T_boundary": T_boundary,
                "time": time,
                "x_position": x_position,
                "alpha": alpha,
            })
            self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
            values.append(out["result"]["value"])

        for earlier, later in zip(values, values[1:]):
            self.assertGreaterEqual(later, earlier - 1.0e-9, msg=values)


if __name__ == "__main__":
    unittest.main(verbosity=2)
