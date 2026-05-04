"""Tests for MF-T05 Plank_Freezing."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_t05


class TestMFT05(unittest.TestCase):

    def test_beef_slab_returns_known_value(self):
        out = mf_t05.solve({
            "rho": 1050.0, "L": 250000.0, "d": 0.05,
            "T_f": -1.0, "T_inf": -30.0, "h": 20.0, "k": 0.45,
            "P": 0.5, "R": 0.125,
        })
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 17600.574712643676, places=6)

    def test_geometry_defaults_append_assumptions(self):
        out = mf_t05.solve({
            "rho": 1000.0, "L": 334000.0, "d": 0.01,
            "T_f": 0.0, "T_inf": -20.0, "h": 50.0, "k": 0.6,
        })
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any("slab default P" in a for a in out["assumptions"]))
        self.assertTrue(any("slab default R" in a for a in out["assumptions"]))

    def test_R_zero_omits_conduction_term(self):
        out = mf_t05.solve({
            "rho": 1000.0, "L": 334000.0, "d": 0.01,
            "T_f": 0.0, "T_inf": -20.0, "h": 50.0, "k": 0.6,
            "P": 0.5, "R": 0.0,
        })
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any("R = 0" in a for a in out["assumptions"]))

    def test_negative_density_rejected(self):
        out = mf_t05.solve({
            "rho": -1.0, "L": 334000.0, "d": 0.01,
            "T_f": 0.0, "T_inf": -20.0, "h": 50.0, "k": 0.6,
        })
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_t05.solve({
            "rho": 1000.0, "L": math.nan, "d": 0.01,
            "T_f": 0.0, "T_inf": -20.0, "h": math.inf, "k": 0.6,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_medium_not_colder_than_freezing_point_rejected(self):
        out = mf_t05.solve({
            "rho": 1000.0, "L": 334000.0, "d": 0.01,
            "T_f": -5.0, "T_inf": -1.0, "h": 50.0, "k": 0.6,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("T_f - T_inf" in i for i in out["validity"]["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
