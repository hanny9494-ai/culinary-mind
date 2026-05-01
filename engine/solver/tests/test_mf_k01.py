"""Tests for MF-K01 Michaelis-Menten solver."""
from __future__ import annotations

import unittest

from engine.solver import mf_k01


class TestMFK01(unittest.TestCase):

    def test_basic_rate(self):
        # v = Vmax · S / (Km + S)
        out = mf_k01.solve({"S": 1.0, "Vmax": 2.0, "Km": 1.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 1.0)
        self.assertEqual(out["result"]["symbol"], "v")

    def test_s_much_greater_than_km_zeroth_order_note(self):
        out = mf_k01.solve({"S": 100.0, "Vmax": 2.0, "Km": 1.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertGreater(out["result"]["value"], 1.95)
        self.assertLess(out["result"]["value"], 2.0)
        self.assertTrue(any("zeroth-order" in a for a in out["assumptions"]))

    def test_s_much_less_than_km_first_order_note(self):
        out = mf_k01.solve({"S": 0.05, "Vmax": 2.0, "Km": 1.0})
        self.assertTrue(out["validity"]["passed"])
        # v ≈ Vmax · S/Km = 2 · 0.05/1 = 0.1
        self.assertAlmostEqual(out["result"]["value"], 2.0 * 0.05 / 1.05, places=6)
        self.assertTrue(any("first-order" in a for a in out["assumptions"]))

    def test_s_zero_returns_zero(self):
        out = mf_k01.solve({"S": 0.0, "Vmax": 2.0, "Km": 1.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.0)

    def test_negative_s_flagged(self):
        out = mf_k01.solve({"S": -0.1, "Vmax": 2.0, "Km": 1.0})
        self.assertFalse(out["validity"]["passed"])

    def test_missing_vmax_flagged(self):
        out = mf_k01.solve({"S": 1.0, "Km": 1.0})
        self.assertFalse(out["validity"]["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
