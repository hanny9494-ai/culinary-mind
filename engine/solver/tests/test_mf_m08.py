"""Tests for MF-M08 Gas_Permeability."""
from __future__ import annotations
import math, unittest
from engine.solver import mf_m08

class TestMFM08(unittest.TestCase):
    def test_known_oxygen_film(self):
        # P_O2 industry units → thickness m → mil internally
        # 1e-4 m = 1e-4 / 2.54e-5 = 3.937 mil
        # Q = 100 × 0.21 / 3.937 = 5.334 cm³/(m²·day)
        out = mf_m08.solve({"P_O2": 100.0, "thickness": 1e-4, "delta_p": 0.21})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        thickness_mil = 1e-4 / 2.54e-5
        expected = 100.0 * 0.21 / thickness_mil
        self.assertAlmostEqual(out["result"]["value"], expected, places=4)

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

    def test_T_c_alias_accepted(self):
        out = mf_m08.solve({"P_O2": 100.0, "thickness": 1e-4, "delta_p": 0.21, "T_c": 25.0})
        self.assertTrue(out["validity"]["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
