"""Tests for MF-T02 Choi_Okos."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_t02


class TestMFT02(unittest.TestCase):

    def test_pure_water_returns_reference_properties(self):
        out = mf_t02.solve({"composition": {"water": 1.0}, "T_c": 25.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        props = out["result"]["value"]
        self.assertLess(abs(props["k"] - 0.604) / 0.604, 0.01)
        self.assertLess(abs(props["Cp"] - 4180.0) / 4180.0, 0.01)
        self.assertLess(abs(props["rho"] - 997.0) / 997.0, 0.01)

    def test_percent_composition_is_normalized(self):
        out = mf_t02.solve({
            "composition": {"water": 70.0, "protein": 10.0, "fat": 10.0, "carb": 8.0, "ash": 2.0},
            "T_c": 25.0,
        })
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any("normalized composition" in a for a in out["assumptions"]))
        self.assertGreater(out["result"]["value"]["Cp"], 2500.0)

    def test_zero_components_allowed_when_total_positive(self):
        out = mf_t02.solve({"composition": {"fat": 1.0, "water": 0.0}, "T_c": 20.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertGreater(out["result"]["value"]["rho"], 0.0)

    def test_negative_composition_rejected(self):
        out = mf_t02.solve({"composition": {"water": 1.1, "fat": -0.1}, "T_c": 25.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("composition.fat" in i for i in out["validity"]["issues"]))

    def test_nan_inf_inputs_rejected(self):
        out = mf_t02.solve({"composition": {"water": math.nan}, "T_c": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_temperature_below_absolute_zero_rejected(self):
        out = mf_t02.solve({"composition": {"water": 1.0}, "T_c": -300.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("absolute zero" in i for i in out["validity"]["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
