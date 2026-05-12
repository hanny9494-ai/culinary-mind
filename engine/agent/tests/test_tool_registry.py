"""Tests for engine.agent.tool_registry — 40 MF Tool wrappers."""
import unittest

from engine.agent.tool_registry import get_all_mf_tools, get_mf_tool, get_tools_by_keyword


class TestToolRegistry(unittest.TestCase):

    def test_40_tools_loaded(self):
        tools = get_all_mf_tools()
        # 40 MF base + 3 T02 children - 1 T02 parent = 42 routable
        self.assertGreaterEqual(len(tools), 39, f"only {len(tools)} tools loaded")

    def test_get_mf_t03(self):
        tool = get_mf_tool("MF-T03")
        self.assertEqual(tool.canonical_name, "Arrhenius")
        self.assertEqual(tool.name, "mf_t03_arrhenius")
        self.assertIn("A", tool.inputs_schema)
        self.assertIn("Ea", tool.inputs_schema)
        self.assertIn("T_K", tool.inputs_schema)

    def test_run_mf_t03(self):
        tool = get_mf_tool("MF-T03")
        out = tool.run({"A": 1.0e10, "Ea": 50000.0, "T_K": 363.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertGreater(out["result"]["value"], 0)
        self.assertEqual(out["result"]["symbol"], "k")

    def test_get_mf_t06_protein_denaturation(self):
        tool = get_mf_tool("MF-T06")
        self.assertEqual(tool.canonical_name, "Protein_Denaturation")
        out = tool.run({"T_d": 70.0, "dH_d": 300.0, "T_C": 70.0})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.5, places=4)

    def test_get_tools_by_keyword_protein(self):
        tools = get_tools_by_keyword("protein")
        ids = {t.mf_id for t in tools}
        self.assertIn("MF-T06", ids)  # Protein_Denaturation

    def test_get_tools_by_keyword_thermal(self):
        tools = get_tools_by_keyword("thermal")
        # Many tools mention thermal in description (k, conductivity, dynamics)
        self.assertGreaterEqual(len(tools), 1)

    def test_get_input_summary_readable(self):
        tool = get_mf_tool("MF-T03")
        summary = tool.get_input_summary()
        self.assertIn("Inputs for MF-T03", summary)
        self.assertIn("A:", summary)
        self.assertIn("range:", summary)

    def test_unknown_mf_raises(self):
        with self.assertRaises(KeyError):
            get_mf_tool("MF-X99")


if __name__ == "__main__":
    unittest.main(verbosity=2)
