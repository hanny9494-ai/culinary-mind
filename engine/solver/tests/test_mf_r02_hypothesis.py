"""P1-21b: Hypothesis property tests for MF-R02 Herschel_Bulkley."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_r02
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    log_float,
    near_boundary,
    ordered_float_pair,
    output_bounds_for,
)


class TestMFR02PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        tau_0=st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
        K=log_float(-6.0, 1.7),
        n=st.floats(min_value=0.01, max_value=2.0, allow_nan=False, allow_infinity=False),
        gamma_dot=st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    def test_in_bounds_inputs_return_finite_bounded_shear_stress(
        self, tau_0: float, K: float, n: float, gamma_dot: float
    ) -> None:
        out = mf_r02.solve({"tau_0": tau_0, "K": K, "n": n, "gamma_dot": gamma_dot})

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-R02")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])


class TestMFR02PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(n=near_boundary("MF-R02", "n", side="above_max"))
    def test_n_just_above_hard_max_fails_validity(self, n: float) -> None:
        out = mf_r02.solve({"tau_0": 10.0, "K": 2.0, "n": n, "gamma_dot": 10.0})

        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(
            any("n" in issue and "outside bounds" in issue for issue in out["validity"]["issues"]),
            msg=out["validity"]["issues"],
        )


class TestMFR02PropertyMonotonicity(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        tau_0=st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
        K=log_float(-6.0, 1.7),
        n=st.floats(min_value=0.01, max_value=2.0, allow_nan=False, allow_infinity=False),
        gamma_pair=ordered_float_pair(min_value=0.0, max_value=1000.0),
    )
    def test_shear_stress_is_nondecreasing_with_shear_rate(
        self, tau_0: float, K: float, n: float, gamma_pair: tuple[float, float]
    ) -> None:
        low_gamma, high_gamma = gamma_pair
        low = mf_r02.solve({"tau_0": tau_0, "K": K, "n": n, "gamma_dot": low_gamma})
        high = mf_r02.solve({"tau_0": tau_0, "K": K, "n": n, "gamma_dot": high_gamma})

        self.assertTrue(low["validity"]["passed"], msg=low["validity"]["issues"])
        self.assertTrue(high["validity"]["passed"], msg=high["validity"]["issues"])
        self.assertGreaterEqual(high["result"]["value"], low["result"]["value"] - 1.0e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
