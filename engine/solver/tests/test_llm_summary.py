"""P1-22: llm_summary field semantic and format checks."""
from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from engine.solver import mf_m06
from engine.solver.tests.test_provenance_consistency import ALL_SOLVERS, SAMPLE_PARAMS


def _out(tool_key: str, solve):
    return solve(SAMPLE_PARAMS[tool_key])


class TestLlmSummary(unittest.TestCase):

    def test_all_30_solvers_emit_llm_summary(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                self.assertIn("llm_summary", out)
                self.assertIsInstance(out["llm_summary"], dict)

    def test_llm_summary_has_required_fields(self):
        required = {"summary_zh", "summary_en", "key_outputs", "confidence"}
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                self.assertTrue(required <= set(out["llm_summary"].keys()))

    def test_llm_summary_zh_non_empty(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                summary = out["llm_summary"]["summary_zh"]
                self.assertTrue(summary)
                self.assertGreater(len(summary), 5)

    def test_llm_summary_en_non_empty(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                summary = out["llm_summary"]["summary_en"]
                self.assertTrue(summary)
                self.assertGreater(len(summary), 5)

    def test_llm_summary_contains_canonical_name_or_value(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                cn = out["provenance"]["tool_canonical_name"]
                summary_en = out["llm_summary"]["summary_en"]
                has_cn = cn.lower() in summary_en.lower()
                value = out["result"]["value"]
                value_str = (
                    f"{value:.4g}"
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                    else ""
                )
                has_val = value_str and value_str in summary_en
                self.assertTrue(has_cn or has_val)

    def test_llm_summary_key_outputs_match_result(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                ko = out["llm_summary"]["key_outputs"]
                value = out["result"]["value"]
                if not (isinstance(value, float) and math.isnan(value)):
                    self.assertEqual(ko.get("value"), value)
                    self.assertEqual(ko.get("unit"), out["result"]["unit"])
                    self.assertEqual(ko.get("symbol"), out["result"]["symbol"])

    def test_llm_summary_handles_nan_value(self):
        with patch("engine.solver.mf_m06.PropsSI", None):
            out = mf_m06.solve({"substance": "ethanol", "T_C": 25.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertIn("llm_summary", out)
        self.assertTrue(out["llm_summary"]["summary_zh"])
        self.assertTrue(out["llm_summary"]["summary_en"])
        self.assertIn("NaN", out["llm_summary"]["summary_en"])

    def test_llm_summary_confidence_type(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                conf = out["llm_summary"]["confidence"]
                self.assertTrue(
                    conf is None
                    or (isinstance(conf, (int, float)) and not isinstance(conf, bool) and 0.0 <= conf <= 1.0)
                )

    def test_llm_summary_format_compact(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                self.assertLess(len(out["llm_summary"]["summary_zh"]), 200)
                self.assertLess(len(out["llm_summary"]["summary_en"]), 200)

    def test_llm_summary_no_prov_leak_into_summary(self):
        for tool_key, solve in ALL_SOLVERS[:5]:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                citations = out["provenance"]["citations"]
                for citation in citations:
                    self.assertNotIn(citation, out["llm_summary"]["summary_en"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
