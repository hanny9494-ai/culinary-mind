"""Tests for MF-M06 Latent_Heat."""
from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from engine.solver import mf_m06


class TestMFM06(unittest.TestCase):

    def test_water_100c_matches_reference_latent_heat(self):
        out = mf_m06.solve({"substance": "Water", "T_C": 100.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertLess(abs(out["result"]["value"] - 2_257_000.0) / 2_257_000.0, 0.01)

    def test_water_25c_is_larger_than_at_boiling_point(self):
        out = mf_m06.solve({"substance": "Water", "T_C": 25.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertGreater(out["result"]["value"], 2_300_000.0)

    def test_below_absolute_zero_rejected(self):
        out = mf_m06.solve({"substance": "Water", "T_C": -300.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("absolute zero" in i for i in out["validity"]["issues"]))

    def test_nan_inf_inputs_rejected(self):
        out = mf_m06.solve({"substance": "Water", "T_C": math.nan})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_nonempty_substance_required(self):
        out = mf_m06.solve({"substance": "", "T_C": 100.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("substance" in i for i in out["validity"]["issues"]))

    def test_assumption_records_coolprop_or_fallback(self):
        out = mf_m06.solve({"substance": "Water", "T_C": 100.0})
        self.assertTrue(any("CoolProp" in a or "Watson" in a for a in out["assumptions"]))

    def test_non_water_without_coolprop_fails_validity(self):
        """P0-3: non-water without CoolProp must fail validity instead of NaN-pass."""
        with patch("engine.solver.mf_m06.PropsSI", None):
            out = mf_m06.solve({"substance": "ethanol", "T_C": 25.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("CoolProp required" in i for i in out["validity"]["issues"]))
        self.assertTrue(any("ethanol" in i.lower() for i in out["validity"]["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
