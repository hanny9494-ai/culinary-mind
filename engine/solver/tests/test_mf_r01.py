"""Tests for MF-R01 Power Law (Ostwald-de Waele) solver."""
from __future__ import annotations

import unittest

from engine.solver import mf_r01


class TestMFR01(unittest.TestCase):

    def test_newtonian_n_equals_1(self):
        # τ = K · γ̇ when n = 1
        out = mf_r01.solve({"gamma_dot": 100.0, "K": 0.001, "n": 1.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.1)
        self.assertTrue(any("Newtonian" in a for a in out["assumptions"]))

    def test_pseudoplastic_n_lt_1(self):
        out = mf_r01.solve({"gamma_dot": 100.0, "K": 1.0, "n": 0.5})
        self.assertTrue(out["validity"]["passed"])
        # τ = 1.0 · 100^0.5 = 10
        self.assertAlmostEqual(out["result"]["value"], 10.0)
        self.assertTrue(any("pseudoplastic" in a for a in out["assumptions"]))

    def test_dilatant_n_gt_1(self):
        out = mf_r01.solve({"gamma_dot": 10.0, "K": 1.0, "n": 1.5})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 10.0 ** 1.5)
        self.assertTrue(any("dilatant" in a for a in out["assumptions"]))

    def test_zero_shear_rate_returns_zero(self):
        out = mf_r01.solve({"gamma_dot": 0.0, "K": 1.0, "n": 0.5})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.0)

    def test_n_outside_range_flagged(self):
        out = mf_r01.solve({"gamma_dot": 10.0, "K": 1.0, "n": 5.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("applicable_range" in i or "outside" in i
                            for i in out["validity"]["issues"]))

    def test_negative_K_flagged(self):
        out = mf_r01.solve({"gamma_dot": 10.0, "K": -1.0, "n": 0.5})
        self.assertFalse(out["validity"]["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
