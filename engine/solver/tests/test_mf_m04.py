"""Tests for MF-M04 Henderson_Hasselbalch."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_m04


class TestMFM04(unittest.TestCase):

    def test_equal_acid_base_returns_pka(self):
        out = mf_m04.solve({"pKa": 4.76, "A_minus_conc": 0.1, "HA_conc": 0.1})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 4.76)

    def test_ten_to_one_ratio_adds_one_ph_unit(self):
        out = mf_m04.solve({"pKa": 4.76, "A_minus_conc": 1.0, "HA_conc": 0.1})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 5.76)

    def test_negative_concentration_rejected(self):
        out = mf_m04.solve({"pKa": 4.76, "A_minus_conc": -0.1, "HA_conc": 0.1})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_m04.solve({"pKa": math.nan, "A_minus_conc": 0.1, "HA_conc": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_zero_acid_concentration_rejected(self):
        out = mf_m04.solve({"pKa": 4.76, "A_minus_conc": 0.1, "HA_conc": 0.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("HA_conc" in i for i in out["validity"]["issues"]))

    def test_assumption_for_equal_pair(self):
        out = mf_m04.solve({"pKa": 4.76, "A_minus_conc": 0.1, "HA_conc": 0.1})
        self.assertTrue(any("pH = pKa" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
