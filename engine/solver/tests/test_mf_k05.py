"""Tests for MF-K05 Gompertz_Microbial."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_k05


class TestMFK05(unittest.TestCase):

    def test_normal_case_returns_growth_value(self):
        out = mf_k05.solve({"t": 10.0, "A": 5.0, "mu_max": 1.0, "lambda": 2.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertGreater(out["result"]["value"], 0.0)
        self.assertLess(out["result"]["value"], 5.0)

    def test_at_lag_time_is_near_baseline_for_small_A(self):
        out = mf_k05.solve({"t": 2.0, "A": 0.1, "mu_max": 1.0, "lambda": 2.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertLess(out["result"]["value"], 0.01)
        self.assertTrue(any("lag region" in a for a in out["assumptions"]))

    def test_late_time_approaches_A(self):
        out = mf_k05.solve({"t": 100.0, "A": 5.0, "mu_max": 1.0, "lambda": 2.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 5.0, places=6)
        self.assertTrue(any("asymptote" in a for a in out["assumptions"]))

    def test_negative_time_rejected(self):
        out = mf_k05.solve({"t": -1.0, "A": 5.0, "mu_max": 1.0, "lambda": 2.0})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_k05.solve({"t": 1.0, "A": math.inf, "mu_max": math.nan, "lambda": 2.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_zero_A_rejected(self):
        out = mf_k05.solve({"t": 1.0, "A": 0.0, "mu_max": 1.0, "lambda": 2.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("A" in i for i in out["validity"]["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
