"""P1-21b: Hypothesis property tests for MF-T02-Cp Choi_Okos_Cp."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_t02_cp
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    composition_fractions,
    float_in_bounds,
    near_boundary,
    ordered_float_pair,
    output_bounds_for,
)


class TestMFT02CpPropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        composition=composition_fractions(),
        T_C=float_in_bounds("MF-T02", "T_C"),
    )
    def test_in_bounds_composition_returns_finite_bounded_specific_heat(
        self, composition: dict[str, float], T_C: float
    ) -> None:
        out = mf_t02_cp.solve({"composition": composition, "T_C": T_C})

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-T02", variant="mf_t02_cp")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])


class TestMFT02CpPropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(T_C=near_boundary("MF-T02", "T_C", side="above_max"))
    def test_temperature_just_above_max_fails_validity(self, T_C: float) -> None:
        out = mf_t02_cp.solve({"composition": {"water": 0.8, "fat": 0.2}, "T_C": T_C})

        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(
            any("T_C" in issue and "outside bounds" in issue for issue in out["validity"]["issues"]),
            msg=out["validity"]["issues"],
        )


class TestMFT02CpPropertyMonotonicity(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        water_pair=ordered_float_pair(min_value=0.0, max_value=0.95),
        T_C=st.floats(min_value=-20.0, max_value=120.0, allow_nan=False, allow_infinity=False),
    )
    def test_replacing_fat_with_water_increases_specific_heat(
        self, water_pair: tuple[float, float], T_C: float
    ) -> None:
        low_water, high_water = water_pair
        low = mf_t02_cp.solve({"composition": {"water": low_water, "fat": 1.0 - low_water}, "T_C": T_C})
        high = mf_t02_cp.solve({"composition": {"water": high_water, "fat": 1.0 - high_water}, "T_C": T_C})

        self.assertTrue(low["validity"]["passed"], msg=low["validity"]["issues"])
        self.assertTrue(high["validity"]["passed"], msg=high["validity"]["issues"])
        self.assertGreaterEqual(high["result"]["value"], low["result"]["value"] - 1.0e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
