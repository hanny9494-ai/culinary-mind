"""Tests for MF-M10 Membrane_Transport."""
from __future__ import annotations
import math, unittest
from engine.solver import mf_m10

class TestMFM10(unittest.TestCase):
    def test_normal_flux(self):
        out = mf_m10.solve({"P_solute": 1e-7, "thickness": 1e-4, "dC": 100.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 1e-7 * 100.0 / 1e-4)

    def test_zero_gradient_no_flux(self):
        out = mf_m10.solve({"P_solute": 1e-7, "thickness": 1e-4, "dC": 0.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertEqual(out["result"]["value"], 0.0)

    def test_negative_dC_negative_flux(self):
        out = mf_m10.solve({"P_solute": 1e-7, "thickness": 1e-4, "dC": -50.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertLess(out["result"]["value"], 0)

    def test_zero_thickness_rejected(self):
        out = mf_m10.solve({"P_solute": 1e-7, "thickness": 0.0, "dC": 100.0})
        self.assertFalse(out["validity"]["passed"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
