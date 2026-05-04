"""Tests for MF-M03 Antoine_Equation."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_m03


class TestMFM03(unittest.TestCase):

    def test_water_25c_matches_vapor_pressure_reference(self):
        out = mf_m03.solve({"substance": "Water", "T_C": 25.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertLess(abs(out["result"]["value"] - 3170.0) / 3170.0, 0.02)

    def test_water_100c_near_one_atmosphere(self):
        out = mf_m03.solve({"substance": "Water", "T_C": 100.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertLess(abs(out["result"]["value"] - 101325.0) / 101325.0, 0.02)

    def test_below_absolute_zero_rejected(self):
        out = mf_m03.solve({"substance": "Water", "T_C": -300.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("absolute zero" in i for i in out["validity"]["issues"]))

    def test_nan_inf_inputs_rejected(self):
        out = mf_m03.solve({"substance": "Water", "T_C": math.inf, "A": math.nan})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_custom_antoine_constants_work_without_coolprop_fluid(self):
        out = mf_m03.solve({"substance": "NotACoolPropFluid", "T_C": 25.0, "A": 8.07131, "B": 1730.63, "C": 233.426})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertLess(abs(out["result"]["value"] - 3157.9) / 3157.9, 0.02)

    def test_assumption_records_coolprop_or_fallback(self):
        out = mf_m03.solve({"substance": "Water", "T_C": 25.0})
        self.assertTrue(any("CoolProp" in a or "Antoine fallback" in a for a in out["assumptions"]))

    def test_water_T_above_100_emits_extrapolation_warning(self):
        """P1-4: water outside Antoine 0-100 C range reports extrapolation assumption."""
        out = mf_m03.solve({"substance": "water", "T_C": 150.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any("extrapolat" in a.lower() for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
