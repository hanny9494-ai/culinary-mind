"""Tests for MF-T01 Fourier_1D semi-infinite-slab solver."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_t01


class TestMFT01(unittest.TestCase):

    # ── Happy paths ────────────────────────────────────────────────────────

    def test_t_equals_zero_returns_t_init(self):
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 0.0, "x_position": 0.005,
            "alpha": 1.4e-7,
        })
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 20.0)
        self.assertEqual(out["result"]["symbol"], "T(x,t)")
        self.assertEqual(out["result"]["unit"], "°C")

    def test_x_at_surface_equals_t_boundary(self):
        # erfc(0) = 1 → T(0, t) = T_boundary
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 60.0, "x_position": 0.0,
            "alpha": 1.4e-7,
        })
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 100.0)

    def test_far_x_approaches_t_init(self):
        # Very large x relative to penetration depth → erfc → 0 → T → T_init
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 60.0, "x_position": 1.0,   # 1m
            "alpha": 1.4e-7,
            # Don't pass thickness — semi-infinite assumption holds at 1m
        })
        # validity should be passed (no thickness given)
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 20.0, places=4)

    # ── Material props from k/rho/Cp ───────────────────────────────────────

    def test_alpha_from_k_rho_cp(self):
        # α = k/(ρ·Cp). Use water-like numbers.
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 60.0, "x_position": 0.005,
            "k": 0.6, "rho": 1000.0, "Cp": 4180.0,
        })
        self.assertTrue(out["validity"]["passed"])
        self.assertIn("computed thermal diffusivity", " ".join(out["assumptions"]))
        self.assertEqual(out["inputs_used"]["k"], 0.6)
        self.assertEqual(out["inputs_used"]["rho"], 1000.0)
        self.assertEqual(out["inputs_used"]["Cp"], 4180.0)

    def test_must_supply_alpha_or_full_kRhoCp(self):
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 60.0, "x_position": 0.005,
            "k": 0.6, "rho": 1000.0,   # missing Cp
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("alpha" in i.lower() or "k, rho, cp" in i.lower()
                            for i in out["validity"]["issues"]))

    # ── Validity checks ────────────────────────────────────────────────────

    def test_negative_alpha_flagged(self):
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 60.0, "x_position": 0.005,
            "alpha": -1.0e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("alpha" in i for i in out["validity"]["issues"]))

    def test_below_absolute_zero_flagged(self):
        out = mf_t01.solve({
            "T_init": -300.0, "T_boundary": 100.0,
            "time": 60.0, "x_position": 0.005,
            "alpha": 1.4e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("absolute zero" in i for i in out["validity"]["issues"]))

    def test_x_exceeds_thickness_flagged(self):
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 60.0, "x_position": 0.5, "thickness": 0.01,
            "alpha": 1.4e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("exceeds slab thickness" in i for i in out["validity"]["issues"]))

    def test_long_time_violates_semi_infinite(self):
        # Long time + thin slab → penetration depth ≈ 2·sqrt(αt)
        # exceeds half thickness.
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 1.0e6, "x_position": 0.001, "thickness": 0.005,
            "alpha": 1.4e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("semi-infinite assumption violated" in i
                            for i in out["validity"]["issues"]))

    # ── P1.2 thickness boundary-condition tests (PR #20 D69 review) ───────

    def test_zero_thickness_flagged(self):
        # thickness=0 collapses the semi-infinite assumption.
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 60.0, "x_position": 0.0, "thickness": 0.0,
            "alpha": 1.4e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("thickness" in i and "> 0" in i
                            for i in out["validity"]["issues"]),
                        msg=out["validity"]["issues"])

    def test_negative_thickness_flagged(self):
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 60.0, "x_position": 0.005, "thickness": -0.01,
            "alpha": 1.4e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("thickness" in i and "> 0" in i
                            for i in out["validity"]["issues"]),
                        msg=out["validity"]["issues"])

    def test_nan_thickness_flagged(self):
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 60.0, "x_position": 0.005,
            "thickness": float("nan"),
            "alpha": 1.4e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("thickness" in i and "finite" in i
                            for i in out["validity"]["issues"]),
                        msg=out["validity"]["issues"])

    def test_inf_thickness_flagged(self):
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 60.0, "x_position": 0.005,
            "thickness": float("inf"),
            "alpha": 1.4e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("thickness" in i and "finite" in i
                            for i in out["validity"]["issues"]),
                        msg=out["validity"]["issues"])

    def test_thickness_omitted_still_passes(self):
        # Backward-compat: thickness is optional; omitting it must still pass.
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0,
            "time": 60.0, "x_position": 0.005,
            "alpha": 1.4e-7,
        })
        self.assertTrue(out["validity"]["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
