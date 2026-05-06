"""P1-21b: Hypothesis property tests for MF-M03 Antoine_Equation."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_m03
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    float_in_bounds,
    ordered_float_pair,
    output_bounds_for,
)


_WATER_ANTOINE_PARAMS = {"A": 8.07131, "B": 1730.63, "C": 233.426}


class TestMFM03PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(T_C=float_in_bounds("MF-M03", "T_C"))
    def test_in_bounds_temperature_returns_finite_positive_pressure(self, T_C: float) -> None:
        params = {"substance": "NotACoolPropFluid", "T_C": T_C, **_WATER_ANTOINE_PARAMS}
        out = mf_m03.solve(params)

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-M03")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreater(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])


class TestMFM03PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(T_C=st.floats(min_value=100.0001, max_value=150.0, allow_nan=False, allow_infinity=False))
    def test_water_above_antoine_range_records_extrapolation_without_failing(self, T_C: float) -> None:
        out = mf_m03.solve({"substance": "water", "T_C": T_C})

        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(
            any("extrapolat" in assumption.lower() for assumption in out["assumptions"]),
            msg=out["assumptions"],
        )


class TestMFM03PropertyMonotonicity(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(T_pair=ordered_float_pair(min_value=0.0, max_value=99.0))
    def test_antoine_pressure_is_nondecreasing_with_temperature(self, T_pair: tuple[float, float]) -> None:
        low_T, high_T = T_pair
        low = mf_m03.solve({"substance": "NotACoolPropFluid", "T_C": low_T, **_WATER_ANTOINE_PARAMS})
        high = mf_m03.solve({"substance": "NotACoolPropFluid", "T_C": high_T, **_WATER_ANTOINE_PARAMS})

        self.assertTrue(low["validity"]["passed"], msg=low["validity"]["issues"])
        self.assertTrue(high["validity"]["passed"], msg=high["validity"]["issues"])
        self.assertGreaterEqual(high["result"]["value"], low["result"]["value"] - 1.0e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
