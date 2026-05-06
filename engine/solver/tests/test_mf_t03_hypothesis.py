"""P1-21b: Hypothesis property tests for MF-T03 Arrhenius."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_t03
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    float_in_bounds,
    log_float,
    near_boundary,
    ordered_float_pair,
    output_bounds_for,
)


class TestMFT03PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        A=log_float(-30.0, 30.0),
        Ea=float_in_bounds("MF-T03", "Ea"),
        T_K=float_in_bounds("MF-T03", "T_K"),
    )
    def test_in_bounds_inputs_return_finite_bounded_rate(self, A: float, Ea: float, T_K: float) -> None:
        out = mf_t03.solve({"A": A, "Ea": Ea, "T_K": T_K})

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-T03")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])


class TestMFT03PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(T_K=st.one_of(st.just(0.0), near_boundary("MF-T03", "T_K", side="below_min")))
    def test_temperature_at_or_below_lower_bound_fails_validity(self, T_K: float) -> None:
        out = mf_t03.solve({"A": 1.0e6, "Ea": 50_000.0, "T_K": T_K})

        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(
            any("T_K" in issue for issue in out["validity"]["issues"]),
            msg=out["validity"]["issues"],
        )


class TestMFT03PropertyMonotonicity(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        A=log_float(-6.0, 12.0),
        Ea=st.floats(min_value=0.0, max_value=250_000.0, allow_nan=False, allow_infinity=False),
        T_pair=ordered_float_pair(min_value=250.0, max_value=500.0),
    )
    def test_rate_is_nondecreasing_with_absolute_temperature(
        self, A: float, Ea: float, T_pair: tuple[float, float]
    ) -> None:
        low_T, high_T = T_pair
        low = mf_t03.solve({"A": A, "Ea": Ea, "T_K": low_T})
        high = mf_t03.solve({"A": A, "Ea": Ea, "T_K": high_T})

        self.assertTrue(low["validity"]["passed"], msg=low["validity"]["issues"])
        self.assertTrue(high["validity"]["passed"], msg=high["validity"]["issues"])
        self.assertGreaterEqual(high["result"]["value"], low["result"]["value"] - 1.0e-300)


if __name__ == "__main__":
    unittest.main(verbosity=2)
