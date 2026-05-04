"""Tests for MF-C05 Q10_Rule."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_c05


class TestMFC05(unittest.TestCase):

    def test_rate_doubles_over_10c_returns_2(self):
        out = mf_c05.solve({"k1": 1.0, "k2": 2.0, "T1": 20.0, "T2": 30.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 2.0)

    def test_rate_quadruples_over_20c_returns_2(self):
        out = mf_c05.solve({"k1": 1.0, "k2": 4.0, "T1": 20.0, "T2": 40.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 2.0)

    def test_negative_rate_rejected(self):
        out = mf_c05.solve({"k1": -1.0, "k2": 2.0, "T1": 20.0, "T2": 30.0})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_c05.solve({"k1": math.nan, "k2": 2.0, "T1": 20.0, "T2": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_same_temperature_rejected(self):
        out = mf_c05.solve({"k1": 1.0, "k2": 2.0, "T1": 20.0, "T2": 20.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("T2 must differ" in i for i in out["validity"]["issues"]))

    def test_assumption_for_10c_interval(self):
        out = mf_c05.solve({"k1": 1.0, "k2": 2.0, "T1": 20.0, "T2": 30.0})
        self.assertTrue(any("10°C interval" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
