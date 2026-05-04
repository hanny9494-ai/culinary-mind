"""Tests for MF-C04 Laplace_Pressure."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_c04


class TestMFC04(unittest.TestCase):

    def test_one_mm_water_air_bubble_returns_144_pa(self):
        out = mf_c04.solve({"sigma": 0.072, "R": 0.001})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 144.0)

    def test_half_radius_doubles_pressure(self):
        out = mf_c04.solve({"sigma": 0.072, "R": 0.0005})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 288.0)

    def test_negative_surface_tension_rejected(self):
        out = mf_c04.solve({"sigma": -0.072, "R": 0.001})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_c04.solve({"sigma": math.nan, "R": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_zero_radius_rejected(self):
        out = mf_c04.solve({"sigma": 0.072, "R": 0.0})
        self.assertFalse(out["validity"]["passed"])

    def test_micron_radius_assumption(self):
        out = mf_c04.solve({"sigma": 0.072, "R": 1.0e-6})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any("micron-scale" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
