"""P1-21b: Hypothesis property tests for MF-C04 Laplace_Pressure."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_c04
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    near_boundary,
    ordered_float_pair,
    output_bounds_for,
)


class TestMFC04PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        sigma=st.floats(min_value=1.0e-4, max_value=1.0, allow_nan=False, allow_infinity=False),
        R=st.floats(min_value=1.0e-9, max_value=1.0e-2, allow_nan=False, allow_infinity=False),
    )
    def test_in_bounds_inputs_return_finite_bounded_laplace_pressure(self, sigma: float, R: float) -> None:
        out = mf_c04.solve({"sigma": sigma, "R": R})

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-C04")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])


class TestMFC04PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        sigma=near_boundary("MF-C04", "sigma", side="below_min"),
        R=near_boundary("MF-C04", "R", side="below_min"),
    )
    def test_sigma_and_radius_just_below_min_fail_validity(self, sigma: float, R: float) -> None:
        low_sigma = mf_c04.solve({"sigma": sigma, "R": 1.0e-4})
        low_radius = mf_c04.solve({"sigma": 0.05, "R": R})

        self.assertFalse(low_sigma["validity"]["passed"])
        self.assertTrue(
            any("sigma" in issue and "outside bounds" in issue for issue in low_sigma["validity"]["issues"]),
            msg=low_sigma["validity"]["issues"],
        )
        self.assertFalse(low_radius["validity"]["passed"])
        self.assertTrue(
            any("R" in issue and "outside bounds" in issue for issue in low_radius["validity"]["issues"]),
            msg=low_radius["validity"]["issues"],
        )


class TestMFC04PropertyMonotonicity(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        sigma=st.floats(min_value=1.0e-4, max_value=1.0, allow_nan=False, allow_infinity=False),
        radius_pair=ordered_float_pair(min_value=1.0e-9, max_value=1.0e-2),
    )
    def test_laplace_pressure_is_nonincreasing_with_radius(
        self, sigma: float, radius_pair: tuple[float, float]
    ) -> None:
        small_R, large_R = radius_pair
        small = mf_c04.solve({"sigma": sigma, "R": small_R})
        large = mf_c04.solve({"sigma": sigma, "R": large_R})

        self.assertTrue(small["validity"]["passed"], msg=small["validity"]["issues"])
        self.assertTrue(large["validity"]["passed"], msg=large["validity"]["issues"])
        self.assertLessEqual(large["result"]["value"], small["result"]["value"] + 1.0e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
