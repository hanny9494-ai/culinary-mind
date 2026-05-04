"""Tests for MF-M02 GAB_Isotherm."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_m02


class TestMFM02(unittest.TestCase):

    def test_normal_case_returns_known_value(self):
        out = mf_m02.solve({"a_w": 0.5, "W_m": 0.08, "C": 10.0, "K": 0.9})
        expected = 0.08 * 10.0 * 0.9 * 0.5 / ((1.0 - 0.9 * 0.5) * (1.0 - 0.9 * 0.5 + 10.0 * 0.9 * 0.5))
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], expected)

    def test_aw_zero_returns_zero(self):
        out = mf_m02.solve({"a_w": 0.0, "W_m": 0.08, "C": 10.0, "K": 0.9})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.0)
        self.assertTrue(any("a_w = 0" in a for a in out["assumptions"]))

    def test_negative_aw_rejected(self):
        out = mf_m02.solve({"a_w": -0.1, "W_m": 0.08, "C": 10.0, "K": 0.9})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_m02.solve({"a_w": math.nan, "W_m": 0.08, "C": math.inf, "K": 0.9})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_aw_one_rejected(self):
        out = mf_m02.solve({"a_w": 1.0, "W_m": 0.08, "C": 10.0, "K": 0.9})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("a_w must be < 1" in i for i in out["validity"]["issues"]))

    def test_high_aw_assumption_appended(self):
        out = mf_m02.solve({"a_w": 0.85, "W_m": 0.08, "C": 10.0, "K": 0.9})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any("high-water-activity" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
