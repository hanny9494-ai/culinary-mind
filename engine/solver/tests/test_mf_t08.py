"""Tests for MF-T08 Ohmic_Heating."""
from __future__ import annotations
import math, unittest
from engine.solver import mf_t08

class TestMFT08(unittest.TestCase):
    def test_baseline_at_25C(self):
        out = mf_t08.solve({"sigma_25": 0.5, "E_field": 100.0, "T_C": 25.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.5 * 100.0**2)

    def test_higher_T_alpha_positive_increases_Q(self):
        out_25 = mf_t08.solve({"sigma_25": 0.5, "alpha": 0.02, "E_field": 100.0, "T_C": 25.0})
        out_80 = mf_t08.solve({"sigma_25": 0.5, "alpha": 0.02, "E_field": 100.0, "T_C": 80.0})
        self.assertGreater(out_80["result"]["value"], out_25["result"]["value"])

    def test_zero_E_field_no_heat(self):
        out = mf_t08.solve({"sigma_25": 0.5, "E_field": 0.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertEqual(out["result"]["value"], 0.0)

    def test_negative_sigma_rejected(self):
        out = mf_t08.solve({"sigma_25": -0.1, "E_field": 100.0})
        self.assertFalse(out["validity"]["passed"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
