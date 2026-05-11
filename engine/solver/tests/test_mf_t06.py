"""Tests for MF-T06 Protein_Denaturation."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_t06


class TestMFT06(unittest.TestCase):

    def test_at_midpoint_temperature_half_native(self):
        """At T_C = T_d, f_native should be 0.5."""
        out = mf_t06.solve({"T_d": 70.0, "dH_d": 300.0, "T_C": 70.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], 0.5, places=4)

    def test_far_below_T_d_almost_fully_native(self):
        out = mf_t06.solve({"T_d": 80.0, "dH_d": 400.0, "T_C": 25.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertGreater(out["result"]["value"], 0.99)

    def test_far_above_T_d_almost_fully_denatured(self):
        out = mf_t06.solve({"T_d": 60.0, "dH_d": 400.0, "T_C": 100.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertLess(out["result"]["value"], 0.01)

    def test_sigma_override(self):
        out = mf_t06.solve({"T_d": 70.0, "dH_d": 200.0, "T_C": 75.0, "sigma_override": 5.0})
        self.assertTrue(out["validity"]["passed"])
        expected = 1.0 / (1.0 + math.exp((75.0 - 70.0) / 5.0))
        self.assertAlmostEqual(out["result"]["value"], expected, places=6)
        self.assertTrue(any("sigma_override" in a or "sigma supplied" in a for a in out["assumptions"]))

    def test_negative_dH_rejected(self):
        out = mf_t06.solve({"T_d": 70.0, "dH_d": -100.0, "T_C": 70.0})
        self.assertFalse(out["validity"]["passed"])

    def test_below_absolute_zero_rejected(self):
        out = mf_t06.solve({"T_d": 70.0, "dH_d": 300.0, "T_C": -300.0})
        self.assertFalse(out["validity"]["passed"])

    def test_output_in_unit_interval(self):
        for tc in [-20, 0, 30, 60, 70, 80, 100, 150]:
            out = mf_t06.solve({"T_d": 70.0, "dH_d": 300.0, "T_C": float(tc)})
            self.assertTrue(out["validity"]["passed"])
            v = out["result"]["value"]
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestMFT06SigmaOverrideAlone(unittest.TestCase):
    def test_sigma_override_without_dH_d(self):
        """P1 fix from cross-review: sigma_override alone should be sufficient."""
        out = mf_t06.solve({"T_d": 70.0, "T_C": 75.0, "sigma_override": 5.0})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        expected = 1.0 / (1.0 + math.exp((75.0 - 70.0) / 5.0))
        self.assertAlmostEqual(out["result"]["value"], expected, places=6)
