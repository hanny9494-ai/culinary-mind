"""Tests for MF-M01 Fick_2nd_Law semi-infinite-slab diffusion solver."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_m01


class TestMFM01(unittest.TestCase):

    def test_t_zero_returns_c_init(self):
        out = mf_m01.solve({
            "C_init": 0.0, "C_boundary": 1.0,
            "time": 0.0, "x_position": 0.001,
            "D_eff": 1e-10,
        })
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.0)

    def test_surface_equals_c_boundary(self):
        out = mf_m01.solve({
            "C_init": 0.0, "C_boundary": 1.0,
            "time": 100.0, "x_position": 0.0,
            "D_eff": 1e-10,
        })
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 1.0)

    def test_far_x_approaches_c_init(self):
        out = mf_m01.solve({
            "C_init": 5.0, "C_boundary": 0.0,
            "time": 100.0, "x_position": 0.5,   # very far
            "D_eff": 1e-10,
        })
        self.assertAlmostEqual(out["result"]["value"], 5.0, places=4)

    def test_d_eff_outside_food_range_warns(self):
        # 1e-5 m²/s is gas-phase fast — flagged as suspicious
        out = mf_m01.solve({
            "C_init": 0.0, "C_boundary": 1.0,
            "time": 1.0, "x_position": 0.001,
            "D_eff": 1e-5,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("typical food range" in i
                            for i in out["validity"]["issues"]))

    def test_negative_d_eff_flagged(self):
        out = mf_m01.solve({
            "C_init": 0.0, "C_boundary": 1.0,
            "time": 100.0, "x_position": 0.001,
            "D_eff": -1e-10,
        })
        self.assertFalse(out["validity"]["passed"])

    def test_x_exceeds_thickness(self):
        out = mf_m01.solve({
            "C_init": 0.0, "C_boundary": 1.0,
            "time": 100.0, "x_position": 0.05, "thickness": 0.01,
            "D_eff": 1e-10,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("exceeds slab thickness" in i
                            for i in out["validity"]["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
