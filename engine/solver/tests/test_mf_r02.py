"""Tests for MF-R02 Herschel_Bulkley."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_r02


class TestMFR02(unittest.TestCase):

    def test_normal_case_returns_known_value(self):
        out = mf_r02.solve({"tau_0": 5.0, "K": 2.0, "n": 0.5, "gamma_dot": 100.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 25.0)

    def test_zero_shear_returns_yield_stress(self):
        out = mf_r02.solve({"tau_0": 5.0, "K": 2.0, "n": 0.5, "gamma_dot": 0.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 5.0)
        self.assertTrue(any("gamma_dot = 0" in a for a in out["assumptions"]))

    def test_negative_tau0_rejected(self):
        out = mf_r02.solve({"tau_0": -1.0, "K": 2.0, "n": 0.5, "gamma_dot": 100.0})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_r02.solve({"tau_0": 5.0, "K": math.inf, "n": 0.5, "gamma_dot": math.nan})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_zero_n_rejected(self):
        out = mf_r02.solve({"tau_0": 0.0, "K": 1.0, "n": 0.0, "gamma_dot": 10.0})
        self.assertFalse(out["validity"]["passed"])

    def test_n_above_two_warns_but_remains_valid(self):
        """P1-5: n>2 is unusual but not a hard Herschel-Bulkley failure."""
        out = mf_r02.solve({"tau_0": 1.0, "K": 0.5, "n": 2.5, "gamma_dot": 4.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any("unusually high" in a for a in out["assumptions"]))

    def test_newtonian_assumption(self):
        out = mf_r02.solve({"tau_0": 0.0, "K": 0.001, "n": 1.0, "gamma_dot": 100.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any("Newtonian" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
