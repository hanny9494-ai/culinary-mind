"""Tests for MF-T02-Cp Choi_Okos specific heat."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_t02_cp


class TestMFT02Cp(unittest.TestCase):

    def test_pure_water_returns_reference_cp(self):
        out = mf_t02_cp.solve({"composition": {"water": 1.0}, "T_c": 25.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertLess(abs(out["result"]["value"] - 4180.0) / 4180.0, 0.01)

    def test_pure_fat_returns_reference_cp(self):
        out = mf_t02_cp.solve({
            "composition": {
                "fat": 1.0, "water": 0.0, "protein": 0.0,
                "carb": 0.0, "fiber": 0.0, "ash": 0.0,
            },
            "T_C": 25.0,
        })
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 2018.0, delta=10.0)

    def test_percent_composition_is_normalized(self):
        out = mf_t02_cp.solve({
            "composition": {"water": 70.0, "protein": 10.0, "fat": 10.0, "carb": 8.0, "ash": 2.0},
            "T_c": 25.0,
        })
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any("normalized composition" in a for a in out["assumptions"]))
        self.assertGreater(out["result"]["value"], 2500.0)

    def test_result_contract_is_atomic_float(self):
        """P0-2: result.value is a scalar float with a plain heat-capacity unit."""
        out = mf_t02_cp.solve({"composition": {"water": 1.0}, "T_C": 25.0})
        self.assertIsInstance(out["result"]["value"], float)
        self.assertEqual(out["result"]["unit"], "J/(kg·K)")
        self.assertEqual(out["result"]["symbol"], "Cp")

    def test_negative_composition_rejected(self):
        out = mf_t02_cp.solve({"composition": {"water": 1.1, "fat": -0.1}, "T_c": 25.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("composition.fat" in i for i in out["validity"]["issues"]))

    def test_nan_inf_inputs_rejected(self):
        out = mf_t02_cp.solve({"composition": {"water": math.nan}, "T_c": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_temperature_below_absolute_zero_rejected(self):
        out = mf_t02_cp.solve({"composition": {"water": 1.0}, "T_c": -300.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("absolute zero" in i for i in out["validity"]["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
