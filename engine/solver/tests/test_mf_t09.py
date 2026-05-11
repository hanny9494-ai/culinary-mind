"""Tests for MF-T09 Respiration_Heat."""
from __future__ import annotations
import math, unittest
from engine.solver import mf_t09

class TestMFT09(unittest.TestCase):
    def test_at_zero_T_C_returns_a(self):
        out = mf_t09.solve({"a": 0.05, "b": 0.08, "T_C": 0.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.05)

    def test_known_apple_storage(self):
        # apple ~0.045 W/kg at 4°C, b~0.08
        out = mf_t09.solve({"a": 0.045, "b": 0.08, "T_C": 4.0})
        self.assertTrue(out["validity"]["passed"])
        expected = 0.045 * math.exp(0.08 * 4.0)
        self.assertAlmostEqual(out["result"]["value"], expected)

    def test_negative_a_rejected(self):
        out = mf_t09.solve({"a": -0.05, "b": 0.08, "T_C": 4.0})
        self.assertFalse(out["validity"]["passed"])

    def test_higher_T_higher_Q(self):
        out_4 = mf_t09.solve({"a": 0.05, "b": 0.08, "T_C": 4.0})
        out_20 = mf_t09.solve({"a": 0.05, "b": 0.08, "T_C": 20.0})
        self.assertGreater(out_20["result"]["value"], out_4["result"]["value"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
