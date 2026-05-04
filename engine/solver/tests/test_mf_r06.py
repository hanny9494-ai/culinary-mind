"""Tests for MF-R06 Stevens_Power_Law."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_r06


class TestMFR06(unittest.TestCase):

    def test_I_one_returns_k(self):
        out = mf_r06.solve({"k": 2.5, "I": 1.0, "n": 0.67})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 2.5)

    def test_n_one_linear_response(self):
        out = mf_r06.solve({"k": 2.5, "I": 4.0, "n": 1.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 10.0)
        self.assertTrue(any("linear" in a for a in out["assumptions"]))

    def test_negative_intensity_rejected(self):
        out = mf_r06.solve({"k": 2.5, "I": -1.0, "n": 0.67})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_r06.solve({"k": math.nan, "I": 1.0, "n": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_zero_n_rejected(self):
        out = mf_r06.solve({"k": 2.5, "I": 1.0, "n": 0.0})
        self.assertFalse(out["validity"]["passed"])

    def test_assumption_for_I_one(self):
        out = mf_r06.solve({"k": 2.5, "I": 1.0, "n": 0.67})
        self.assertTrue(any("S = k" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
