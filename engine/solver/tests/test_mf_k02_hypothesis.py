"""P1-21b: Hypothesis property tests for MF-K02 D_Value."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_k02
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    float_in_bounds,
    output_bounds_for,
)


class TestMFK02PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        t=float_in_bounds("MF-K02", "t"),
        N0=st.floats(min_value=10.0, max_value=1.0e12, allow_nan=False, allow_infinity=False),
        log_reduction=st.floats(min_value=1.0, max_value=6.0, allow_nan=False, allow_infinity=False),
    )
    def test_in_bounds_inactivation_returns_finite_positive_d_value(
        self, t: float, N0: float, log_reduction: float
    ) -> None:
        N = N0 / (10.0 ** log_reduction)
        out = mf_k02.solve({"t": t, "N0": N0, "N": N})

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-K02")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreater(value, 0.0)
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])


class TestMFK02PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        N0=st.floats(min_value=1.0, max_value=1.0e12, allow_nan=False, allow_infinity=False),
        growth_fraction=st.floats(min_value=1.0e-6, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_no_reduction_or_population_growth_fails_validity(
        self, N0: float, growth_fraction: float
    ) -> None:
        equal_counts = mf_k02.solve({"t": 60.0, "N0": N0, "N": N0})
        grown_counts = mf_k02.solve({"t": 60.0, "N0": N0, "N": N0 * (1.0 + growth_fraction)})

        self.assertFalse(equal_counts["validity"]["passed"])
        self.assertTrue(
            any("N must be less than N0" in issue for issue in equal_counts["validity"]["issues"]),
            msg=equal_counts["validity"]["issues"],
        )
        self.assertFalse(grown_counts["validity"]["passed"])
        self.assertTrue(
            any("N must be less than N0" in issue for issue in grown_counts["validity"]["issues"]),
            msg=grown_counts["validity"]["issues"],
        )


class TestMFK02PropertyThermalDeathLaw(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        t=st.floats(min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False),
        N0=st.floats(min_value=10_000.0, max_value=1.0e12, allow_nan=False, allow_infinity=False),
    )
    def test_d_value_scales_with_time_and_decreases_with_survivor_loss(
        self, t: float, N0: float
    ) -> None:
        one_log_short = mf_k02.solve({"t": t, "N0": N0, "N": N0 / 10.0})
        one_log_long = mf_k02.solve({"t": 2.0 * t, "N0": N0, "N": N0 / 10.0})
        two_log = mf_k02.solve({"t": t, "N0": N0, "N": N0 / 100.0})

        for out in (one_log_short, one_log_long, two_log):
            self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])

        self.assertGreaterEqual(
            one_log_long["result"]["value"],
            one_log_short["result"]["value"] - 1.0e-9,
        )
        self.assertLessEqual(
            two_log["result"]["value"],
            one_log_short["result"]["value"] + 1.0e-9,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
