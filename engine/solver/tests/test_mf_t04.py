"""Tests for MF-T04 Nusselt correlation solver."""
from __future__ import annotations

import math
import unittest

from engine.solver import mf_t04


class TestMFT04(unittest.TestCase):

    def test_basic_dittus_boelter(self):
        # Classic Dittus-Boelter correlation: Nu = 0.023 · Re^0.8 · Pr^0.4
        out = mf_t04.solve({"Re": 10000, "Pr": 0.7,
                            "C": 0.023, "m": 0.8, "n": 0.4})
        self.assertTrue(out["validity"]["passed"])
        expected = 0.023 * (10000 ** 0.8) * (0.7 ** 0.4)
        self.assertAlmostEqual(out["result"]["value"], expected, places=4)
        self.assertEqual(out["result"]["symbol"], "Nu")

    def test_h_extra_when_kfluid_and_lchar_given(self):
        out = mf_t04.solve({
            "Re": 10000, "Pr": 0.7,
            "C": 0.023, "m": 0.8, "n": 0.4,
            "k_fluid": 0.6, "L_characteristic": 0.025,
        })
        self.assertIn("extras", out["result"])
        self.assertIn("h", out["result"]["extras"])
        nu = out["result"]["value"]
        expected_h = nu * 0.6 / 0.025
        self.assertAlmostEqual(out["result"]["extras"]["h"], expected_h, places=4)

    def test_negative_re_flagged(self):
        out = mf_t04.solve({"Re": -1.0, "Pr": 0.7,
                            "C": 0.023, "m": 0.8, "n": 0.4})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("Re" in i for i in out["validity"]["issues"]))

    def test_missing_C_flagged(self):
        out = mf_t04.solve({"Re": 10000, "Pr": 0.7, "m": 0.8, "n": 0.4})
        self.assertFalse(out["validity"]["passed"])

    def test_zero_C_flagged(self):
        out = mf_t04.solve({"Re": 10000, "Pr": 0.7,
                            "C": 0.0, "m": 0.8, "n": 0.4})
        self.assertFalse(out["validity"]["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
