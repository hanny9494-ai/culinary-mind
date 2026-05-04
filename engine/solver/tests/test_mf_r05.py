"""Tests for MF-R05 WLF_Equation."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_r05


class TestMFR05(unittest.TestCase):

    def test_T_equals_Tg_returns_one(self):
        out = mf_r05.solve({"T": 50.0, "Tg": 50.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 1.0)

    def test_delta_50_returns_known_value(self):
        out = mf_r05.solve({"T": 100.0, "Tg": 50.0})
        expected = 10.0 ** (-17.44 * 50.0 / (51.6 + 50.0))
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], expected)

    def test_negative_C1_rejected(self):
        out = mf_r05.solve({"T": 100.0, "Tg": 50.0, "C1": -1.0})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_r05.solve({"T": math.nan, "Tg": 50.0, "C1": 17.44, "C2": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_denominator_singularity_rejected(self):
        out = mf_r05.solve({"T": -1.6, "Tg": 50.0, "C2": 51.6})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("C2 + (T - Tg)" in i for i in out["validity"]["issues"]))

    def test_assumption_appended_at_Tg(self):
        out = mf_r05.solve({"T": 50.0, "Tg": 50.0})
        self.assertTrue(any("aT = 1" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
