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
        self.assertTrue(any("using slab default geometry factors" in a for a in out["assumptions"]))

    def test_cylinder_geometry_uses_correct_factors(self):
        """P1-2: geometry='cylinder' uses cylinder Plank factors instead of slab defaults."""
        base = {
            "rho": 1000.0, "L": 334000.0, "d": 0.05,
            "T_f": -5.0, "T_inf": -30.0, "h": 50.0, "k": 0.5,
        }
        cylinder = mf_t05.solve({**base, "geometry": "cylinder"})
        slab = mf_t05.solve({**base, "geometry": "slab"})
        self.assertTrue(cylinder["validity"]["passed"], msg=cylinder["validity"]["issues"])
        self.assertTrue(slab["validity"]["passed"], msg=slab["validity"]["issues"])
        self.assertNotAlmostEqual(cylinder["result"]["value"], slab["result"]["value"])
        self.assertLess(cylinder["result"]["value"], slab["result"]["value"])

    def test_invalid_geometry_rejected(self):
        """P1-2: invalid geometry reports a validity issue."""
        out = mf_t05.solve({
            "rho": 1000.0, "L": 334000.0, "d": 0.05,
            "T_f": -5.0, "T_inf": -30.0, "h": 50.0, "k": 0.5,
            "geometry": "torus",
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("geometry must be one of" in i for i in out["validity"]["issues"]))

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

    def test_nan_geometry_factor_rejected(self):
        """P1-7: geometry factors are finite-guarded before use."""
        out = mf_t05.solve({
            "rho": 1000.0, "L": 334000.0, "d": 0.01,
            "T_f": 0.0, "T_inf": -20.0, "h": 50.0, "k": 0.6,
            "P": math.nan,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("P must be finite" in i for i in out["validity"]["issues"]))

    def test_medium_not_colder_than_freezing_point_rejected(self):
        out = mf_t05.solve({
            "rho": 1000.0, "L": 334000.0, "d": 0.01,
            "T_f": -5.0, "T_inf": -1.0, "h": 50.0, "k": 0.6,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("T_f - T_inf" in i for i in out["validity"]["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
