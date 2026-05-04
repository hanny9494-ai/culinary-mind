"""Tests for MF-R03 Casson_Model."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_r03


class TestMFR03(unittest.TestCase):

    def test_normal_case_returns_known_value(self):
        out = mf_r03.solve({"tau_0": 4.0, "K_C": 0.25, "gamma_dot": 100.0})
        expected = (math.sqrt(4.0) + math.sqrt(0.25 * 100.0)) ** 2
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], expected)

    def test_zero_shear_returns_tau0(self):
        out = mf_r03.solve({"tau_0": 4.0, "K_C": 0.25, "gamma_dot": 0.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 4.0)
        self.assertTrue(any("gamma_dot = 0" in a for a in out["assumptions"]))

    def test_negative_tau0_rejected(self):
        out = mf_r03.solve({"tau_0": -4.0, "K_C": 0.25, "gamma_dot": 100.0})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_r03.solve({"tau_0": 4.0, "K_C": math.nan, "gamma_dot": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_zero_kc_rejected(self):
        out = mf_r03.solve({"tau_0": 4.0, "K_C": 0.0, "gamma_dot": 100.0})
        self.assertFalse(out["validity"]["passed"])

    def test_zero_tau0_assumption(self):
        out = mf_r03.solve({"tau_0": 0.0, "K_C": 0.25, "gamma_dot": 100.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any("tau_0 = 0" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
