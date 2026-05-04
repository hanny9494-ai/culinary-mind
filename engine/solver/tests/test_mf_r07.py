"""Tests for MF-R07 Griffith_Fracture."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_r07


class TestMFR07(unittest.TestCase):

    def test_normal_case_returns_known_value(self):
        out = mf_r07.solve({"E": 1.0e11, "gamma_s": 1.0, "a": 1.0e-6})
        expected = math.sqrt(2.0 * 1.0e11 * 1.0 / (math.pi * 1.0e-6))
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertAlmostEqual(out["result"]["value"], expected)

    def test_larger_crack_lowers_fracture_stress(self):
        small = mf_r07.solve({"E": 1.0e11, "gamma_s": 1.0, "a": 1.0e-6})
        large = mf_r07.solve({"E": 1.0e11, "gamma_s": 1.0, "a": 1.0e-4})
        self.assertGreater(small["result"]["value"], large["result"]["value"])

    def test_negative_modulus_rejected(self):
        out = mf_r07.solve({"E": -1.0, "gamma_s": 1.0, "a": 1.0e-6})
        self.assertFalse(out["validity"]["passed"])

    def test_nan_inf_inputs_rejected(self):
        out = mf_r07.solve({"E": math.inf, "gamma_s": 1.0, "a": math.nan})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("finite" in i for i in out["validity"]["issues"]))

    def test_zero_crack_length_rejected(self):
        out = mf_r07.solve({"E": 1.0e11, "gamma_s": 1.0, "a": 0.0})
        self.assertFalse(out["validity"]["passed"])

    def test_small_crack_assumption(self):
        out = mf_r07.solve({"E": 1.0e11, "gamma_s": 1.0, "a": 1.0e-6})
        self.assertTrue(any("small crack" in a for a in out["assumptions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
