"""Tests for MF-K04 F_Value."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_k04


class TestMFK04(unittest.TestCase):

    def test_constant_reference_temperature_for_60s_returns_1_min(self):
        out = mf_k04.solve({"T_C": 121.1, "time": 60.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 1.0)

    def test_callable_profile_integrated_with_quad(self):
        out = mf_k04.solve({"T_profile": lambda _t: 131.1, "t_start": 0.0, "t_end": 60.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 10.0, places=5)
        self.assertTrue(any("scipy.quad" in a for a in out["assumptions"]))

    def test_sampled_profile_integrated_with_simpson(self):
        out = mf_k04.solve({"times_s": [0.0, 30.0, 60.0], "temperatures_C": [121.1, 121.1, 121.1]})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 1.0)
        self.assertTrue(any("scipy.simpson" in a for a in out["assumptions"]))

    def test_negative_z_rejected(self):
        out = mf_k04.solve({"T_C": 121.1, "time": 60.0, "z": -10.0})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_k04.solve({"times_s": [0.0, math.inf], "temperatures_C": [121.1, math.nan]})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_negative_time_rejected(self):
        out = mf_k04.solve({"T_C": 121.1, "time": -1.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("time" in i for i in out["validity"]["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
