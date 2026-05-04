"""Tests for MF-C02 HLB_Griffin."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_c02


class TestMFC02(unittest.TestCase):

    def test_equal_masses_returns_10(self):
        out = mf_c02.solve({"M_h": 5.0, "M_l": 5.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 10.0)

    def test_total_mass_alias_computes_lipophilic_mass(self):
        out = mf_c02.solve({"M_h": 4.0, "M": 10.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 8.0)
        self.assertTrue(any("computed M_l" in a for a in out["assumptions"]))
        self.assertEqual(out["inputs_used"]["M"], 10.0)

    def test_negative_mass_rejected(self):
        out = mf_c02.solve({"M_h": -1.0, "M_l": 5.0})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_c02.solve({"M_h": math.nan, "M_l": math.inf})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_zero_total_mass_rejected(self):
        out = mf_c02.solve({"M_h": 0.0, "M_l": 0.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("M_h + M_l" in i for i in out["validity"]["issues"]))

    def test_assumption_for_equal_masses(self):
        out = mf_c02.solve({"M_h": 5.0, "M_l": 5.0})
        self.assertTrue(any("HLB = 10" in a for a in out["assumptions"]))

    def test_M_string_input_returns_validity_failure_not_typeerror(self):
        """P0-4: non-numeric M alias yields a validity issue, not TypeError."""
        out = mf_c02.solve({"M_h": 4.0, "M": "10"})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("M must be finite numeric" in i for i in out["validity"]["issues"]))

    def test_M_None_or_NaN_handled(self):
        """P0-4: None/NaN M aliases report validity failures without raising."""
        out_none = mf_c02.solve({"M_h": 4.0, "M": None})
        self.assertFalse(out_none["validity"]["passed"])
        self.assertTrue(any("M must be finite numeric" in i for i in out_none["validity"]["issues"]))
        out_nan = mf_c02.solve({"M_h": 4.0, "M": float("nan")})
        self.assertFalse(out_nan["validity"]["passed"])
        self.assertTrue(any("M must be finite numeric" in i for i in out_nan["validity"]["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
