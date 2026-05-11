"""P1-21a: solver_bounds.yaml schema completeness checks."""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml


BOUNDS_PATH = Path(__file__).resolve().parents[3] / "config" / "solver_bounds.yaml"


class TestSolverBoundsYaml(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = yaml.safe_load(BOUNDS_PATH.read_text(encoding="utf-8"))

    def test_yaml_loads(self):
        self.assertIn("solvers", self.data)
        self.assertIn("version", self.data)

    def test_28_mf_ids_covered(self):
        expected = {
            "MF-T01", "MF-T02", "MF-T03", "MF-T04", "MF-T05",
            "MF-K01", "MF-K02", "MF-K03", "MF-K04", "MF-K05",
            "MF-M01", "MF-M02", "MF-M03", "MF-M04", "MF-M05", "MF-M06",
            "MF-R01", "MF-R02", "MF-R03", "MF-R04", "MF-R05", "MF-R06", "MF-R07",
            "MF-C01", "MF-C02", "MF-C03", "MF-C04", "MF-C05",
            "MF-T06", "MF-T07", "MF-T10", "MF-K06",  # P3 Tier 1 (2026-05-11)
        }
        self.assertEqual(set(self.data["solvers"].keys()), expected)

    def test_each_solver_has_canonical_name(self):
        for mf_id, spec in self.data["solvers"].items():
            with self.subTest(mf_id=mf_id):
                self.assertIn("canonical_name", spec)

    def test_each_solver_has_inputs_or_outputs(self):
        for mf_id, spec in self.data["solvers"].items():
            with self.subTest(mf_id=mf_id):
                self.assertTrue(
                    "inputs" in spec or "output" in spec or "outputs_by_variant" in spec
                )

    def test_input_bounds_min_le_max(self):
        for mf_id, spec in self.data["solvers"].items():
            for inp in spec.get("inputs", []) or []:
                if (
                    "min" in inp and "max" in inp
                    and inp["min"] is not None and inp["max"] is not None
                ):
                    with self.subTest(mf_id=mf_id, name=inp["name"]):
                        self.assertLessEqual(inp["min"], inp["max"])

    def test_numeric_bounds_are_numeric(self):
        for mf_id, spec in self.data["solvers"].items():
            for inp in spec.get("inputs", []) or []:
                for key in ("min", "max"):
                    if key in inp and inp[key] is not None:
                        with self.subTest(mf_id=mf_id, name=inp["name"], key=key):
                            self.assertIsInstance(inp[key], (int, float))

    def test_output_bounds_min_le_max(self):
        for mf_id, spec in self.data["solvers"].items():
            outputs = []
            if "output" in spec:
                outputs.append(spec["output"])
            outputs.extend((spec.get("outputs_by_variant") or {}).values())
            for out in outputs:
                if out.get("min") is not None and out.get("max") is not None:
                    with self.subTest(mf_id=mf_id, symbol=out["symbol"]):
                        self.assertLessEqual(out["min"], out["max"])

    def test_t02_has_outputs_by_variant(self):
        spec = self.data["solvers"]["MF-T02"]
        self.assertIn("outputs_by_variant", spec)
        for variant in ["mf_t02_k", "mf_t02_cp", "mf_t02_rho"]:
            self.assertIn(variant, spec["outputs_by_variant"])

    def test_wlf_has_soft_t_minus_tg_bound(self):
        inputs = self.data["solvers"]["MF-R05"]["inputs"]
        soft = [inp for inp in inputs if inp["name"] == "T_minus_Tg"]
        self.assertEqual(len(soft), 1)
        self.assertTrue(soft[0]["soft"])

    def test_normal_config_does_not_set_disabled_flag(self):
        self.assertNotIn("_disabled", self.data["solvers"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
