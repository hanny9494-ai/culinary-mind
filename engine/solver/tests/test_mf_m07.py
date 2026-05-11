"""Tests for MF-M07 Solubility_Partition."""
from __future__ import annotations
import math, unittest
from engine.solver import mf_m07

class TestMFM07(unittest.TestCase):
    def test_logP_zero_K_eq_1(self):
        out = mf_m07.solve({"logP": 0.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 1.0)

    def test_logP_positive_K_gt_1(self):
        out = mf_m07.solve({"logP": 2.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 100.0)

    def test_logP_negative_K_lt_1(self):
        out = mf_m07.solve({"logP": -1.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.1)

    def test_logP_nan_rejected(self):
        out = mf_m07.solve({"logP": math.nan})
        self.assertFalse(out["validity"]["passed"])

    def test_negative_S_water_rejected(self):
        out = mf_m07.solve({"logP": 1.0, "S_water": -1.0})
        self.assertFalse(out["validity"]["passed"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
