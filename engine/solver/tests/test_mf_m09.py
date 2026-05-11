"""Tests for MF-M09 Osmotic_Pressure."""
from __future__ import annotations
import math, unittest
from engine.solver import mf_m09

class TestMFM09(unittest.TestCase):
    def test_1M_glucose_at_25C(self):
        out = mf_m09.solve({"M": 1.0, "T_K": 298.15})
        self.assertTrue(out["validity"]["passed"])
        # π = 1·1000·8.314·298.15 ≈ 2.479 MPa
        self.assertAlmostEqual(out["result"]["value"], 2.479e6, delta=1e4)

    def test_NaCl_van_t_Hoff_factor_2(self):
        out = mf_m09.solve({"M": 1.0, "T_K": 298.15, "i": 2.0})
        self.assertTrue(out["validity"]["passed"])
        # Should double
        out_glucose = mf_m09.solve({"M": 1.0, "T_K": 298.15})
        self.assertAlmostEqual(out["result"]["value"], 2 * out_glucose["result"]["value"])

    def test_T_C_to_T_K_conversion(self):
        out = mf_m09.solve({"M": 0.5, "T_C": 25.0})
        self.assertTrue(out["validity"]["passed"])

    def test_zero_M_zero_pi(self):
        out = mf_m09.solve({"M": 0.0, "T_K": 298.15})
        self.assertTrue(out["validity"]["passed"])
        self.assertEqual(out["result"]["value"], 0.0)

    def test_negative_T_rejected(self):
        out = mf_m09.solve({"M": 1.0, "T_K": -10.0})
        self.assertFalse(out["validity"]["passed"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
