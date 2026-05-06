"""P1-21b: Hypothesis property tests for MF-R05 WLF_Equation."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_r05
from engine.solver.tests._hypothesis_helpers import assert_solver_contract, output_bounds_for


class TestMFR05PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        Tg=st.floats(min_value=-50.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        delta=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        C1=st.floats(min_value=1.0, max_value=17.44, allow_nan=False, allow_infinity=False),
        C2=st.floats(min_value=51.6, max_value=200.0, allow_nan=False, allow_infinity=False),
    )
    def test_in_bounds_wlf_window_returns_finite_bounded_shift_factor(
        self, Tg: float, delta: float, C1: float, C2: float
    ) -> None:
        out = mf_r05.solve({"T": Tg + delta, "Tg": Tg, "C1": C1, "C2": C2})

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-R05")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])


class TestMFR05PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        Tg=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        delta=st.floats(min_value=100.001, max_value=250.0, allow_nan=False, allow_infinity=False),
    )
    def test_T_minus_Tg_above_soft_max_warns_without_failing(self, Tg: float, delta: float) -> None:
        out = mf_r05.solve({"T": Tg + delta, "Tg": Tg, "C1": 17.44, "C2": 51.6})

        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(
            any(issue.startswith("WARN:") and "soft bound" in issue for issue in out["validity"]["issues"]),
            msg=out["validity"]["issues"],
        )


class TestMFR05PropertyReferencePoint(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        Tg=st.floats(min_value=-100.0, max_value=300.0, allow_nan=False, allow_infinity=False),
        C1=st.floats(min_value=1.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        C2=st.floats(min_value=10.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    )
    def test_T_equal_Tg_returns_unit_shift_factor(self, Tg: float, C1: float, C2: float) -> None:
        out = mf_r05.solve({"T": Tg, "Tg": Tg, "C1": C1, "C2": C2})

        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 1.0, places=12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
