"""Tests for MF-R04 Gordon_Taylor."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_r04


class TestMFR04(unittest.TestCase):

    def test_normal_case_returns_known_value(self):
        out = mf_r04.solve({"w1": 0.7, "w2": 0.3, "Tg1": 350.0, "Tg2": 150.0, "k": 5.0})
        expected = (0.7 * 350.0 + 5.0 * 0.3 * 150.0) / (0.7 + 5.0 * 0.3)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], expected)

    def test_w1_one_returns_tg1(self):
        out = mf_r04.solve({"w1": 1.0, "w2": 0.0, "Tg1": 350.0, "Tg2": 150.0, "k": 5.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 350.0)
        self.assertTrue(any("Tg_mix = Tg1" in a for a in out["assumptions"]))

    def test_negative_weight_rejected(self):
        out = mf_r04.solve({"w1": -0.1, "w2": 1.1, "Tg1": 350.0, "Tg2": 150.0, "k": 5.0})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_r04.solve({"w1": 0.7, "w2": 0.3, "Tg1": math.nan, "Tg2": 150.0, "k": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_zero_weights_rejected(self):
        out = mf_r04.solve({"w1": 0.0, "w2": 0.0, "Tg1": 350.0, "Tg2": 150.0, "k": 5.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("cannot both be zero" in i for i in out["validity"]["issues"]))

    def test_non_normalized_weights_assumption(self):
        out = mf_r04.solve({"w1": 7.0, "w2": 3.0, "Tg1": 350.0, "Tg2": 150.0, "k": 5.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any("scale-invariant" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
