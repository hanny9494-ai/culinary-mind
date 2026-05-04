"""Tests for MF-C01 Stokes_Sedimentation."""
from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from engine.solver import mf_c01


class TestMFC01(unittest.TestCase):

    def test_milk_fat_one_micron_in_water_creams_upward(self):
        out = mf_c01.solve({"r": 1.0e-6, "rho_p": 930.0, "rho_f": 1000.0, "eta": 0.001})
        expected = 2.0 * (1.0e-6 ** 2) * (930.0 - 1000.0) * 9.81 / (9.0 * 0.001)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], expected)
        self.assertLess(out["result"]["value"], 0.0)

    def test_downward_settling_uses_fluids_when_available(self):
        out = mf_c01.solve({"r": 1.0e-6, "rho_p": 1050.0, "rho_f": 1000.0, "eta": 0.001})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertGreater(out["result"]["value"], 0.0)
        self.assertTrue(any("fluids.v_terminal" in a or "Stokes" in a for a in out["assumptions"]))

    def test_downward_settling_requests_stokes_method(self):
        """P1-6: fluids.v_terminal is called with Method='Stokes'."""
        with patch("engine.solver.mf_c01._fluids_v_terminal", return_value=1.0e-6) as mocked:
            out = mf_c01.solve({"r": 1.0e-6, "rho_p": 1050.0, "rho_f": 1000.0, "eta": 0.001})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertEqual(mocked.call_args.kwargs["Method"], "Stokes")
        self.assertTrue(any("Method='Stokes'" in a for a in out["assumptions"]))

    def test_negative_radius_rejected(self):
        out = mf_c01.solve({"r": -1.0e-6, "rho_p": 930.0, "rho_f": 1000.0, "eta": 0.001})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_c01.solve({"r": math.nan, "rho_p": 930.0, "rho_f": math.inf, "eta": 0.001})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_neutral_buoyancy_returns_zero(self):
        out = mf_c01.solve({"r": 1.0e-6, "rho_p": 1000.0, "rho_f": 1000.0, "eta": 0.001})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 0.0)
        self.assertTrue(any("neutral buoyancy" in a for a in out["assumptions"]))

    def test_high_reynolds_number_flagged(self):
        out = mf_c01.solve({"r": 0.01, "rho_p": 2500.0, "rho_f": 1.2, "eta": 1.0e-5})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("Stokes regime violated" in i for i in out["validity"]["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
