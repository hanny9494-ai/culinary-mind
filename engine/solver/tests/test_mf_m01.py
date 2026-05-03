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

    # ── P1.1 boundary-condition tests (PR #20 D69 review) ─────────────────

    def test_negative_c_init_flagged(self):
        # Concentrations are mol/m³ or kg/m³ — negative values are non-physical.
        out = mf_m01.solve({
            "C_init": -1.0, "C_boundary": 1.0,
            "time": 100.0, "x_position": 0.001,
            "D_eff": 1e-10,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("C_init" in i and "≥ 0" in i
                            for i in out["validity"]["issues"]),
                        msg=out["validity"]["issues"])

    def test_negative_c_boundary_flagged(self):
        out = mf_m01.solve({
            "C_init": 0.0, "C_boundary": -2.5,
            "time": 100.0, "x_position": 0.001,
            "D_eff": 1e-10,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("C_boundary" in i and "≥ 0" in i
                            for i in out["validity"]["issues"]),
                        msg=out["validity"]["issues"])

    def test_zero_concentrations_still_valid(self):
        # allow_zero=True means C_init=0 / C_boundary=0 must keep passing
        # (e.g. starting from pure solvent and diffusing in).
        out = mf_m01.solve({
            "C_init": 0.0, "C_boundary": 0.0,
            "time": 100.0, "x_position": 0.001,
            "D_eff": 1e-10,
        })
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.0)

    def test_nan_c_init_flagged(self):
        out = mf_m01.solve({
            "C_init": float("nan"), "C_boundary": 1.0,
            "time": 100.0, "x_position": 0.001,
            "D_eff": 1e-10,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("C_init" in i and "finite" in i
                            for i in out["validity"]["issues"]),
                        msg=out["validity"]["issues"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ── P1.2 thickness boundary tests (PR #20 Round 2 review) ─────────────────

class TestMFM01Thickness(unittest.TestCase):
    """Mirror the mf_t01 thickness validation — require_positive when supplied."""

    def test_zero_thickness_flagged(self):
        out = mf_m01.solve({
            "C_init": 0.0, "C_boundary": 1.0,
            "time": 100.0, "x_position": 0.001,
            "thickness": 0.0,
            "D_eff": 1e-10,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("thickness" in i and "> 0" in i
                            for i in out["validity"]["issues"]),
                        msg=out["validity"]["issues"])

    def test_negative_thickness_flagged(self):
        out = mf_m01.solve({
            "C_init": 0.0, "C_boundary": 1.0,
            "time": 100.0, "x_position": 0.001,
            "thickness": -0.01,
            "D_eff": 1e-10,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("thickness" in i and "> 0" in i
                            for i in out["validity"]["issues"]),
                        msg=out["validity"]["issues"])

    def test_nan_thickness_flagged(self):
        out = mf_m01.solve({
            "C_init": 0.0, "C_boundary": 1.0,
            "time": 100.0, "x_position": 0.001,
            "thickness": float("nan"),
            "D_eff": 1e-10,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("thickness" in i and "finite" in i
                            for i in out["validity"]["issues"]),
                        msg=out["validity"]["issues"])

    def test_inf_thickness_flagged(self):
        out = mf_m01.solve({
            "C_init": 0.0, "C_boundary": 1.0,
            "time": 100.0, "x_position": 0.001,
            "thickness": float("inf"),
            "D_eff": 1e-10,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("thickness" in i and "finite" in i
                            for i in out["validity"]["issues"]),
                        msg=out["validity"]["issues"])

    def test_thickness_omitted_still_passes(self):
        # Backward compat: thickness optional; existing behavior unchanged when omitted.
        out = mf_m01.solve({
            "C_init": 0.0, "C_boundary": 1.0,
            "time": 100.0, "x_position": 0.001,
            "D_eff": 1e-10,
        })
        self.assertTrue(out["validity"]["passed"])
