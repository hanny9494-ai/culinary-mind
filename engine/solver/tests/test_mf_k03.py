"""Tests for MF-K03 z_Value."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_k03


class TestMFK03(unittest.TestCase):

    def test_normal_case_returns_10c(self):
        out = mf_k03.solve({"T1": 121.0, "T2": 131.0, "D1": 10.0, "D2": 1.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 10.0)

    def test_reversed_temperature_pair_still_valid_when_D_reverses(self):
        out = mf_k03.solve({"T1": 131.0, "T2": 121.0, "D1": 1.0, "D2": 10.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 10.0)

    def test_negative_D_rejected(self):
        out = mf_k03.solve({"T1": 121.0, "T2": 131.0, "D1": -10.0, "D2": 1.0})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_k03.solve({"T1": math.nan, "T2": 131.0, "D1": 10.0, "D2": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_same_temperature_rejected(self):
        out = mf_k03.solve({"T1": 121.0, "T2": 121.0, "D1": 10.0, "D2": 1.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("T2 must differ" in i for i in out["validity"]["issues"]))

    def test_assumption_appended_for_common_z_value(self):
        out = mf_k03.solve({"T1": 121.0, "T2": 131.0, "D1": 10.0, "D2": 1.0})
        self.assertTrue(any("10°C" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
