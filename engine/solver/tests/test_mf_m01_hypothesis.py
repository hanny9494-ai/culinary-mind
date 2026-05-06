"""P1-21b: Hypothesis property tests for MF-M01 Fick_2nd_Law."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_m01
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    float_in_bounds,
    near_boundary,
    output_bounds_for,
)


class TestMFM01PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        C_init=float_in_bounds("MF-M01", "C_init"),
        C_boundary=float_in_bounds("MF-M01", "C_boundary"),
        D_eff=st.floats(min_value=1.0e-13, max_value=1.0e-7, allow_nan=False, allow_infinity=False),
        x_position=float_in_bounds("MF-M01", "x_position"),
        time=float_in_bounds("MF-M01", "time"),
    )
    def test_in_bounds_inputs_return_finite_bounded_concentration(
        self, C_init: float, C_boundary: float, D_eff: float, x_position: float, time: float
    ) -> None:
        out = mf_m01.solve({
            "C_init": C_init,
            "C_boundary": C_boundary,
            "D_eff": D_eff,
            "x_position": x_position,
            "time": time,
        })

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-M01")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])
        span_tol = max(1.0e-9, 1.0e-12 * max(abs(C_init), abs(C_boundary), 1.0))
        self.assertGreaterEqual(value, min(C_init, C_boundary) - span_tol)
        self.assertLessEqual(value, max(C_init, C_boundary) + span_tol)


class TestMFM01PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        low_D=near_boundary("MF-M01", "D_eff", side="below_min"),
        high_D=near_boundary("MF-M01", "D_eff", side="above_max"),
    )
    def test_D_eff_near_hard_bounds_fails_validity(self, low_D: float, high_D: float) -> None:
        low = mf_m01.solve({
            "C_init": 10.0,
            "C_boundary": 100.0,
            "D_eff": low_D,
            "x_position": 0.01,
            "time": 60.0,
        })
        high = mf_m01.solve({
            "C_init": 10.0,
            "C_boundary": 100.0,
            "D_eff": high_D,
            "x_position": 0.01,
            "time": 60.0,
        })

        self.assertFalse(low["validity"]["passed"])
        self.assertTrue(
            any("D_eff" in issue and "outside bounds" in issue for issue in low["validity"]["issues"]),
            msg=low["validity"]["issues"],
        )
        self.assertFalse(high["validity"]["passed"])
        self.assertTrue(
            any("D_eff" in issue and "outside bounds" in issue for issue in high["validity"]["issues"]),
            msg=high["validity"]["issues"],
        )


class TestMFM01PropertyAsymptote(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        C_init=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        C_boundary=st.floats(min_value=200.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        D_eff=st.floats(min_value=1.0e-12, max_value=1.0e-9, allow_nan=False, allow_infinity=False),
        x_position=st.floats(min_value=0.001, max_value=0.05, allow_nan=False, allow_infinity=False),
    )
    def test_distance_to_boundary_concentration_decays_over_time(
        self, C_init: float, C_boundary: float, D_eff: float, x_position: float
    ) -> None:
        distances = []
        for time in (0.0, 10.0, 100.0, 1000.0, 10_000.0):
            out = mf_m01.solve({
                "C_init": C_init,
                "C_boundary": C_boundary,
                "D_eff": D_eff,
                "x_position": x_position,
                "time": time,
            })
            self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
            distances.append(abs(out["result"]["value"] - C_boundary))

        for earlier, later in zip(distances, distances[1:]):
            self.assertLessEqual(later, earlier + 1.0e-9, msg=distances)


if __name__ == "__main__":
    unittest.main(verbosity=2)
