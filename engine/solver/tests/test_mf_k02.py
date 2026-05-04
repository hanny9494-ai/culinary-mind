"""Tests for MF-K02 D_Value."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_k02


class TestMFK02(unittest.TestCase):

    def test_one_log_reduction_in_60s_returns_60s(self):
        out = mf_k02.solve({"t": 60.0, "N0": 1000.0, "N": 100.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 60.0)

    def test_two_log_reduction_returns_half_time(self):
        out = mf_k02.solve({"t": 60.0, "N0": 10000.0, "N": 100.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 30.0)

    def test_negative_time_rejected(self):
        out = mf_k02.solve({"t": -1.0, "N0": 1000.0, "N": 100.0})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_k02.solve({"t": math.nan, "N0": 1000.0, "N": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_no_reduction_rejected(self):
        out = mf_k02.solve({"t": 60.0, "N0": 1000.0, "N": 1000.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("less than N0" in i for i in out["validity"]["issues"]))

    def test_assumption_appended_for_one_log(self):
        out = mf_k02.solve({"t": 60.0, "N0": 10.0, "N": 1.0})
        self.assertTrue(any("1-log reduction" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
