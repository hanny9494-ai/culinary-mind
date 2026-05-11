"""Tests for MF-K07 Binding_Equilibrium."""
from __future__ import annotations
import math, unittest
from engine.solver import mf_k07

class TestMFK07(unittest.TestCase):
    def test_K_a_L_eq_1_half_bound(self):
        out = mf_k07.solve({"K_a": 1.0e6, "L_total": 1.0e-6})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.5)

    def test_high_K_a_high_binding(self):
        out = mf_k07.solve({"K_a": 1.0e9, "L_total": 1.0e-3})
        self.assertTrue(out["validity"]["passed"])
        self.assertGreater(out["result"]["value"], 0.99)

    def test_low_K_a_low_binding(self):
        out = mf_k07.solve({"K_a": 1.0, "L_total": 1.0e-6})
        self.assertTrue(out["validity"]["passed"])
        self.assertLess(out["result"]["value"], 0.01)

    def test_K_d_to_K_a_conversion(self):
        out_a = mf_k07.solve({"K_a": 1.0e7, "L_total": 1.0e-6})
        out_d = mf_k07.solve({"K_d": 1.0e-7, "L_total": 1.0e-6})
        self.assertAlmostEqual(out_a["result"]["value"], out_d["result"]["value"])

    def test_negative_L_rejected(self):
        out = mf_k07.solve({"K_a": 1.0e6, "L_total": -1e-6})
        self.assertFalse(out["validity"]["passed"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
