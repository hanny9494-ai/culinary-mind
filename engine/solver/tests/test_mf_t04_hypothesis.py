"""P1-21b: Hypothesis property tests for MF-T04 Nusselt_Correlation."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_t04
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    near_boundary,
    ordered_float_pair,
    output_bounds_for,
)


class TestMFT04PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        Re=st.floats(min_value=0.001, max_value=1.0e5, allow_nan=False, allow_infinity=False),
        Pr=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        C=st.floats(min_value=1.0e-6, max_value=0.1, allow_nan=False, allow_infinity=False),
        m=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        n=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_in_bounds_correlation_returns_finite_bounded_nusselt(
        self, Re: float, Pr: float, C: float, m: float, n: float
    ) -> None:
        out = mf_t04.solve({"Re": Re, "Pr": Pr, "C": C, "m": m, "n": n})

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-T04")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])


class TestMFT04PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        Re=near_boundary("MF-T04", "Re", side="below_min"),
        Pr=near_boundary("MF-T04", "Pr", side="above_max"),
    )
    def test_Re_and_Pr_near_hard_bounds_fail_validity(self, Re: float, Pr: float) -> None:
        low_re = mf_t04.solve({"Re": Re, "Pr": 7.0, "C": 0.02, "m": 0.8, "n": 0.33})
        high_pr = mf_t04.solve({"Re": 1000.0, "Pr": Pr, "C": 0.02, "m": 0.8, "n": 0.33})

        self.assertFalse(low_re["validity"]["passed"])
        self.assertTrue(any("Re" in issue and "outside bounds" in issue for issue in low_re["validity"]["issues"]))
        self.assertFalse(high_pr["validity"]["passed"])
        self.assertTrue(any("Pr" in issue and "outside bounds" in issue for issue in high_pr["validity"]["issues"]))


class TestMFT04PropertyMonotonicity(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        Re_pair=ordered_float_pair(min_value=0.01, max_value=1.0e5),
        Pr=st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
        C=st.floats(min_value=1.0e-4, max_value=0.1, allow_nan=False, allow_infinity=False),
        m=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
        n=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_nusselt_is_nondecreasing_with_reynolds_number(
        self, Re_pair: tuple[float, float], Pr: float, C: float, m: float, n: float
    ) -> None:
        low_Re, high_Re = Re_pair
        low = mf_t04.solve({"Re": low_Re, "Pr": Pr, "C": C, "m": m, "n": n})
        high = mf_t04.solve({"Re": high_Re, "Pr": Pr, "C": C, "m": m, "n": n})

        self.assertTrue(low["validity"]["passed"], msg=low["validity"]["issues"])
        self.assertTrue(high["validity"]["passed"], msg=high["validity"]["issues"])
        self.assertGreaterEqual(high["result"]["value"], low["result"]["value"] - 1.0e-12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
