"""P1-22: ensure legacy solver response keys remain stable."""
from __future__ import annotations

import unittest

from engine.solver import mf_t01


class TestBackwardCompat(unittest.TestCase):

    def test_mf_t01_legacy_keys_still_present(self):
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0, "time": 60.0,
            "x_position": 0.005, "alpha": 1.4e-7,
        })
        self.assertIn("result", out)
        self.assertIn("value", out["result"])
        self.assertIn("unit", out["result"])
        self.assertIn("symbol", out["result"])
        self.assertIn("assumptions", out)
        self.assertIn("validity", out)
        self.assertIn("passed", out["validity"])
        self.assertIn("issues", out["validity"])
        self.assertIn("inputs_used", out)

    def test_mf_t01_value_still_float(self):
        out = mf_t01.solve({
            "T_init": 20.0, "T_boundary": 100.0, "time": 60.0,
            "x_position": 0.005, "alpha": 1.4e-7,
        })
        self.assertIsInstance(out["result"]["value"], (int, float))
        self.assertNotIsInstance(out["result"]["value"], bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
