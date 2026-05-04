"""Tests for MF-T03 Arrhenius."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_t03


class TestMFT03(unittest.TestCase):

    def test_normal_case_returns_known_value(self):
        out = mf_t03.solve({"A": 1.0e10, "Ea": 50000.0, "T_K": 298.0})
        expected = 1.0e10 * math.exp(-50000.0 / (8.31446261815324 * 298.0))
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], expected, places=8)

    def test_zero_activation_energy_returns_A(self):
        out = mf_t03.solve({"A": 42.0, "Ea": 0.0, "T_K": 310.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 42.0)
        self.assertTrue(any("Ea = 0" in a for a in out["assumptions"]))

    def test_negative_A_rejected(self):
        out = mf_t03.solve({"A": -1.0, "Ea": 50000.0, "T_K": 298.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("A" in i for i in out["validity"]["issues"]))

    def test_nan_inf_inputs_rejected(self):
        out = mf_t03.solve({"A": math.nan, "Ea": 50000.0, "T_K": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_zero_kelvin_rejected(self):
        out = mf_t03.solve({"A": 1.0, "Ea": 50000.0, "T_K": 0.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("T_K" in i for i in out["validity"]["issues"]))

    def test_assumption_mentions_kelvin(self):
        out = mf_t03.solve({"A": 1.0, "Ea": 1000.0, "T_K": 300.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertTrue(any("Kelvin" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
