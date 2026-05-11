"""Tests for MF-T07 Dielectric_Properties."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_t07


_EPS0 = 8.8541878128e-12


class TestMFT07(unittest.TestCase):

    def test_microwave_oven_known_power(self):
        """2.45 GHz, ε''=15, E=2000 V/m → P_abs ≈ 8.18 MW/m³ (typical microwave)."""
        out = mf_t07.solve({
            "epsilon_double_prime": 15.0,
            "frequency": 2.45e9,
            "E_field": 2000.0,
        })
        expected = 2.0 * math.pi * 2.45e9 * _EPS0 * 15.0 * 2000.0 ** 2
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], expected, places=0)

    def test_zero_loss_factor_no_absorption(self):
        out = mf_t07.solve({
            "epsilon_double_prime": 0.0,
            "frequency": 2.45e9,
            "E_field": 1000.0,
        })
        self.assertTrue(out["validity"]["passed"])
        self.assertEqual(out["result"]["value"], 0.0)

    def test_zero_field_no_absorption(self):
        out = mf_t07.solve({
            "epsilon_double_prime": 10.0,
            "frequency": 2.45e9,
            "E_field": 0.0,
        })
        self.assertTrue(out["validity"]["passed"])
        self.assertEqual(out["result"]["value"], 0.0)

    def test_negative_frequency_rejected(self):
        out = mf_t07.solve({
            "epsilon_double_prime": 10.0,
            "frequency": -1e9,
            "E_field": 1000.0,
        })
        self.assertFalse(out["validity"]["passed"])

    def test_aliases_work(self):
        out = mf_t07.solve({"epsilon_pp": 10.0, "f": 915e6, "E": 500.0})
        self.assertTrue(out["validity"]["passed"])
        expected = 2.0 * math.pi * 915e6 * _EPS0 * 10.0 * 500.0 ** 2
        self.assertAlmostEqual(out["result"]["value"], expected, places=4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
