"""Tests for MF-T10 Starch_Gelatinization."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_t10


_R = 8.31446261815324


class TestMFT10(unittest.TestCase):

    def test_zero_time_alpha_zero(self):
        out = mf_t10.solve({
            "T_C": 80.0, "time": 0.0,
            "A": 1.0e10, "Ea": 80000.0, "n": 1.5,
        })
        self.assertTrue(out["validity"]["passed"])
        self.assertEqual(out["result"]["value"], 0.0)

    def test_long_time_alpha_approaches_1(self):
        out = mf_t10.solve({
            "T_C": 90.0, "time": 3600.0,
            "A": 1.0e10, "Ea": 50000.0, "n": 1.0,
        })
        self.assertTrue(out["validity"]["passed"])
        self.assertGreater(out["result"]["value"], 0.99)

    def test_low_temp_low_alpha(self):
        out = mf_t10.solve({
            "T_C": 30.0, "time": 60.0,
            "A": 1.0e10, "Ea": 100000.0, "n": 1.5,
        })
        self.assertTrue(out["validity"]["passed"])
        self.assertLess(out["result"]["value"], 0.5)

    def test_avrami_formula_at_known_point(self):
        T_C, time, A, Ea, n = 70.0, 600.0, 1.0e8, 80000.0, 1.2
        t_k = T_C + 273.15
        k = A * math.exp(-Ea / (_R * t_k))
        expected = 1.0 - math.exp(-k * time ** n)
        out = mf_t10.solve({"T_C": T_C, "time": time, "A": A, "Ea": Ea, "n": n})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], expected, places=6)

    def test_low_water_warning(self):
        out = mf_t10.solve({
            "T_C": 80.0, "time": 100.0,
            "A": 1.0e10, "Ea": 80000.0, "n": 1.5,
            "water_content": 0.20,
        })
        self.assertTrue(out["validity"]["passed"])
        self.assertTrue(any("water_content" in a or "incomplete" in a for a in out["assumptions"]))

    def test_negative_n_rejected(self):
        out = mf_t10.solve({
            "T_C": 80.0, "time": 100.0,
            "A": 1.0e10, "Ea": 80000.0, "n": -0.5,
        })
        self.assertFalse(out["validity"]["passed"])

    def test_alpha_in_unit_interval(self):
        for tt in [1, 10, 100, 1000, 10000]:
            out = mf_t10.solve({
                "T_C": 75.0, "time": float(tt),
                "A": 1.0e9, "Ea": 70000.0, "n": 1.2,
            })
            self.assertTrue(out["validity"]["passed"])
            v = out["result"]["value"]
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
