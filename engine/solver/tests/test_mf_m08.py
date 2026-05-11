"""Tests for MF-M08 Gas_Permeability."""
from __future__ import annotations
import math, unittest
from engine.solver import mf_m08

class TestMFM08(unittest.TestCase):
    def test_known_oxygen_film(self):
        out = mf_m08.solve({"P_O2": 100.0, "thickness": 1e-4, "delta_p": 0.21})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 100.0 * 0.21 / 1e-4)

    def test_zero_delta_p_no_flux(self):
        out = mf_m08.solve({"P_O2": 100.0, "thickness": 1e-4, "delta_p": 0.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertEqual(out["result"]["value"], 0.0)

    def test_zero_thickness_rejected(self):
        out = mf_m08.solve({"P_O2": 100.0, "thickness": 0.0, "delta_p": 0.21})
        self.assertFalse(out["validity"]["passed"])

    def test_RH_out_of_range_rejected(self):
        out = mf_m08.solve({"P_O2": 100.0, "thickness": 1e-4, "delta_p": 0.21, "RH": 150})
        self.assertFalse(out["validity"]["passed"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
