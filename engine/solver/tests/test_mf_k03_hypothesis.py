"""P1-21b: Hypothesis property tests for MF-K03 z_Value."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_k03
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    output_bounds_for,
)


class TestMFK03PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        T1=st.floats(min_value=-50.0, max_value=180.0, allow_nan=False, allow_infinity=False),
        delta_T=st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False),
        D2=st.floats(min_value=1.0e-3, max_value=1.0e3, allow_nan=False, allow_infinity=False),
        log_ratio=st.floats(min_value=0.1, max_value=3.0, allow_nan=False, allow_infinity=False),
    )
    def test_in_bounds_decreasing_d_with_heating_returns_positive_z(
        self, T1: float, delta_T: float, D2: float, log_ratio: float
    ) -> None:
        D1 = D2 * (10.0 ** log_ratio)
        out = mf_k03.solve({"T1": T1, "T2": T1 + delta_T, "D1": D1, "D2": D2})

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-K03")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreater(value, 0.0)
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])


class TestMFK03PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        T1=st.floats(min_value=-40.0, max_value=190.0, allow_nan=False, allow_infinity=False),
        D=st.floats(min_value=1.0e-3, max_value=1.0e6, allow_nan=False, allow_infinity=False),
    )
    def test_equal_d_values_or_equal_temperatures_fail_validity(
        self, T1: float, D: float
    ) -> None:
        same_d = mf_k03.solve({"T1": T1, "T2": T1 + 10.0, "D1": D, "D2": D})
        same_t = mf_k03.solve({"T1": T1, "T2": T1, "D1": 10.0, "D2": 1.0})

        self.assertFalse(same_d["validity"]["passed"])
        self.assertTrue(
            any("D1 and D2 must differ" in issue for issue in same_d["validity"]["issues"]),
            msg=same_d["validity"]["issues"],
        )
        self.assertFalse(same_t["validity"]["passed"])
        self.assertTrue(
            any("T2 must differ from T1" in issue for issue in same_t["validity"]["issues"]),
            msg=same_t["validity"]["issues"],
        )


class TestMFK03PropertyThermalResistanceLaw(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        T1=st.floats(min_value=-20.0, max_value=120.0, allow_nan=False, allow_infinity=False),
        D2=st.floats(min_value=1.0e-3, max_value=1.0e3, allow_nan=False, allow_infinity=False),
    )
    def test_z_decreases_with_d_ratio_and_increases_with_temperature_span(
        self, T1: float, D2: float
    ) -> None:
        low_ratio = mf_k03.solve({"T1": T1, "T2": T1 + 20.0, "D1": D2 * 10.0, "D2": D2})
        high_ratio = mf_k03.solve({"T1": T1, "T2": T1 + 20.0, "D1": D2 * 100.0, "D2": D2})
        small_delta = mf_k03.solve({"T1": T1, "T2": T1 + 10.0, "D1": D2 * 100.0, "D2": D2})
        large_delta = mf_k03.solve({"T1": T1, "T2": T1 + 40.0, "D1": D2 * 100.0, "D2": D2})

        for out in (low_ratio, high_ratio, small_delta, large_delta):
            self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])

        self.assertLessEqual(
            high_ratio["result"]["value"],
            low_ratio["result"]["value"] + 1.0e-9,
        )
        self.assertGreaterEqual(
            large_delta["result"]["value"],
            small_delta["result"]["value"] - 1.0e-9,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
