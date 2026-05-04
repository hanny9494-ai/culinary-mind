"""Tests for MF-M05 Henry_Law_Aroma."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_m05


class TestMFM05(unittest.TestCase):

    def test_co2_in_water_25c_one_atm_reference(self):
        out = mf_m05.solve({"substance": "CO2", "H": 3.35e-4, "p_gas": 101325.0, "T_C": 25.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 33.946, places=2)

    def test_pressure_form_uses_inverse_constant(self):
        out = mf_m05.solve({"H": 2.0e6, "p_gas": 1.0e5, "H_form": "pressure"})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 0.05)

    def test_zero_pressure_returns_zero(self):
        out = mf_m05.solve({"H": 3.35e-4, "p_gas": 0.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 0.0)
        self.assertTrue(any("zero gas" in a for a in out["assumptions"]))

    def test_negative_H_rejected(self):
        out = mf_m05.solve({"H": -1.0, "p_gas": 101325.0})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_m05.solve({"H": math.nan, "p_gas": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_dimensionless_ideal_gas_assumption(self):
        out = mf_m05.solve({"H": 0.1, "p_gas": 101325.0, "T_C": 25.0, "H_form": "dimensionless"})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any("ideal gas" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
