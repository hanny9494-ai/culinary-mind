"""Tests for MF-C03 DLVO_Theory."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_c03


class TestMFC03(unittest.TestCase):

    def test_large_distance_approaches_zero(self):
        out = mf_c03.solve({"A_H": 1.0e-20, "kappa": 1.0e8, "zeta": 0.05, "epsilon": 78.5, "T": 298.15, "D": 1.0e-3})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertLess(abs(out["result"]["value"]), 1.0e-22)

    def test_zeta_creates_energy_barrier(self):
        out = mf_c03.solve({"A_H": 1.0e-20, "kappa": 1.0e8, "zeta": 0.05, "epsilon": 78.5, "T": 298.15, "D": 1.0e-9})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertGreater(out["result"]["value"], 0.0)
        self.assertTrue(any("energy barrier" in a for a in out["assumptions"]))

    def test_zero_zeta_removes_repulsion(self):
        out = mf_c03.solve({"A_H": 1.0e-20, "kappa": 1.0e8, "zeta": 0.0, "epsilon": 78.5, "T": 298.15, "D": 1.0e-9})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertLess(out["result"]["value"], 0.0)
        self.assertTrue(any("no electrostatic" in a for a in out["assumptions"]))

    def test_negative_hamaker_rejected(self):
        out = mf_c03.solve({"A_H": -1.0e-20, "kappa": 1.0e8, "zeta": 0.05, "epsilon": 78.5, "T": 298.15, "D": 1.0e-9})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_c03.solve({"A_H": 1.0e-20, "kappa": math.inf, "zeta": 0.05, "epsilon": math.nan, "T": 298.15, "D": 1.0e-9})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_default_radius_assumption(self):
        out = mf_c03.solve({"A_H": 1.0e-20, "kappa": 1.0e8, "zeta": 0.05, "epsilon": 78.5, "T": 298.15, "D": 1.0e-9})
        self.assertTrue(any("r=1 µm" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
