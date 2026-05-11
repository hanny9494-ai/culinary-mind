"""Tests for MF-K06 Growth_Limit."""
from __future__ import annotations

import unittest

from engine.solver import mf_k06


class TestMFK06(unittest.TestCase):

    def test_pH_above_min_growth_permitted(self):
        out = mf_k06.solve({"pH_min": 4.0, "pH": 6.5})
        self.assertTrue(out["validity"]["passed"])
        self.assertEqual(out["result"]["value"], 0.0)  # not inhibited

    def test_pH_below_min_growth_inhibited(self):
        out = mf_k06.solve({"pH_min": 4.6, "pH": 3.5})
        self.assertTrue(out["validity"]["passed"])
        self.assertEqual(out["result"]["value"], 1.0)  # inhibited

    def test_aw_low_inhibits(self):
        out = mf_k06.solve({"a_w_min": 0.92, "a_w": 0.85})
        self.assertTrue(out["validity"]["passed"])
        self.assertEqual(out["result"]["value"], 1.0)

    def test_T_low_inhibits(self):
        out = mf_k06.solve({"T_min": 5.0, "T_C": 2.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertEqual(out["result"]["value"], 1.0)

    def test_MIC_exceeded_inhibits(self):
        out = mf_k06.solve({"MIC": 100.0, "substance_conc": 200.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertEqual(out["result"]["value"], 1.0)

    def test_multiple_hurdles_one_violation_inhibits(self):
        out = mf_k06.solve({
            "pH_min": 4.6, "a_w_min": 0.92, "T_min": 5.0,
            "pH": 5.0, "a_w": 0.85, "T_C": 10.0,
        })
        self.assertTrue(out["validity"]["passed"])
        # a_w below min → inhibited
        self.assertEqual(out["result"]["value"], 1.0)

    def test_no_limits_rejected(self):
        out = mf_k06.solve({"pH": 6.5})
        self.assertFalse(out["validity"]["passed"])

    def test_pH_out_of_natural_range(self):
        out = mf_k06.solve({"pH_min": 4.0, "pH": 15.0})
        self.assertFalse(out["validity"]["passed"])

    def test_margins_in_summary(self):
        out = mf_k06.solve({"pH_min": 4.5, "pH": 5.5})
        self.assertTrue(out["validity"]["passed"])
        margins = out["llm_summary"]["key_outputs"]["margins"]
        self.assertIn("pH_minus_pH_min", margins)
        self.assertAlmostEqual(margins["pH_minus_pH_min"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
