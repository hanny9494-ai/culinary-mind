"""P1-17.1: Schema validation for MF-T02 parent + 3 children split.

Ensures mother_formulas.yaml + mf_fingerprints.json are aligned with the
solver-level split (mf_t02_k.py / mf_t02_cp.py / mf_t02_rho.py).

Invariants:
    - MF-T02 marked `parent_only: true` in both files
    - MF-T02 has children list = [MF-T02-K, MF-T02-CP, MF-T02-RHO]
    - Each child has `parent: MF-T02`
    - Each child references a real solver module (engine.solver.mf_t02_{k,cp,rho})
    - Total routable MF count is 30 (28 originals - MF-T02 + 3 new children;
      MF-T02 itself is parent_only and not routable)
    - Child canonical_name matches the 3 split solver canonical_names
      (Choi_Okos_thermal_conductivity / specific_heat / density)
"""
from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
MF_YAML = REPO_ROOT / "config" / "mother_formulas.yaml"
MF_JSON = REPO_ROOT / "config" / "mf_fingerprints.json"

EXPECTED_CHILD_IDS = ["MF-T02-K", "MF-T02-CP", "MF-T02-RHO"]
EXPECTED_CANONICAL = {
    "MF-T02-K":   "Choi_Okos_thermal_conductivity",
    "MF-T02-CP":  "Choi_Okos_specific_heat",
    "MF-T02-RHO": "Choi_Okos_density",
}
EXPECTED_SOLVER_MODULE = {
    "MF-T02-K":   "engine.solver.mf_t02_k",
    "MF-T02-CP":  "engine.solver.mf_t02_cp",
    "MF-T02-RHO": "engine.solver.mf_t02_rho",
}


def _load_yaml() -> list[dict]:
    """mother_formulas.yaml is a top-level list of MF entries."""
    raw = yaml.safe_load(MF_YAML.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "mother_formulas" in raw:
        return raw["mother_formulas"]
    return raw


def _yaml_by_id(entries: list[dict]) -> dict[str, dict]:
    return {e["id"]: e for e in entries if isinstance(e, dict) and "id" in e}


def _load_fingerprints() -> dict[str, dict]:
    return json.loads(MF_JSON.read_text(encoding="utf-8"))


class TestMFT02SplitConsistency(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.yaml_entries = _load_yaml()
        cls.yaml_by_id = _yaml_by_id(cls.yaml_entries)
        cls.fingerprints = _load_fingerprints()

    # ── YAML side ─────────────────────────────────────────────────────────

    def test_yaml_has_mf_t02_parent(self):
        self.assertIn("MF-T02", self.yaml_by_id)

    def test_yaml_mf_t02_marked_parent_only(self):
        self.assertTrue(self.yaml_by_id["MF-T02"].get("parent_only"),
                        "MF-T02 must have parent_only: true")

    def test_yaml_mf_t02_lists_3_children(self):
        children = self.yaml_by_id["MF-T02"].get("children", [])
        self.assertEqual(sorted(children), sorted(EXPECTED_CHILD_IDS))

    def test_yaml_3_children_present(self):
        for cid in EXPECTED_CHILD_IDS:
            self.assertIn(cid, self.yaml_by_id, f"missing yaml entry {cid}")

    def test_yaml_each_child_references_parent(self):
        for cid in EXPECTED_CHILD_IDS:
            self.assertEqual(self.yaml_by_id[cid].get("parent"), "MF-T02",
                            f"{cid} parent != MF-T02")

    def test_yaml_each_child_canonical_name(self):
        for cid, expected in EXPECTED_CANONICAL.items():
            self.assertEqual(self.yaml_by_id[cid].get("canonical_name"), expected)

    def test_yaml_each_child_solver_module_importable(self):
        for cid in EXPECTED_CHILD_IDS:
            module_path = self.yaml_by_id[cid].get("solver_module")
            self.assertEqual(module_path, EXPECTED_SOLVER_MODULE[cid])
            mod = importlib.import_module(module_path)
            self.assertTrue(hasattr(mod, "solve"),
                           f"{module_path}.solve missing")

    # ── JSON fingerprints side ────────────────────────────────────────────

    def test_json_has_mf_t02_parent(self):
        self.assertIn("MF-T02", self.fingerprints)

    def test_json_mf_t02_marked_parent_only(self):
        self.assertTrue(self.fingerprints["MF-T02"].get("parent_only"),
                        "MF-T02 must have parent_only: true in fingerprints.json")

    def test_json_3_children_present(self):
        for cid in EXPECTED_CHILD_IDS:
            self.assertIn(cid, self.fingerprints, f"missing fingerprint {cid}")

    def test_json_each_child_references_parent(self):
        for cid in EXPECTED_CHILD_IDS:
            self.assertEqual(self.fingerprints[cid].get("parent"), "MF-T02")

    def test_json_each_child_canonical_name(self):
        for cid, expected in EXPECTED_CANONICAL.items():
            self.assertEqual(self.fingerprints[cid].get("canonical_name"), expected)

    def test_json_each_child_solver_module(self):
        for cid in EXPECTED_CHILD_IDS:
            self.assertEqual(self.fingerprints[cid].get("solver_module"),
                            EXPECTED_SOLVER_MODULE[cid])

    # ── Cross-file consistency ────────────────────────────────────────────

    def test_yaml_json_canonical_names_match(self):
        for cid in ["MF-T02"] + EXPECTED_CHILD_IDS:
            yaml_canon = self.yaml_by_id[cid].get("canonical_name")
            json_canon = self.fingerprints[cid].get("canonical_name")
            self.assertEqual(yaml_canon, json_canon,
                            f"{cid}: yaml canonical_name {yaml_canon!r} != json {json_canon!r}")

    def test_routable_mf_count_is_30(self):
        """parent_only entries are not routable.
        Before P1-17.1: 28 routable (MF-T02 was a single routable entry).
        After  P1-17.1: 30 routable = 27 unchanged originals + 3 new children
                       (MF-T02 is now parent_only, replaced by 3 children).
        """
        routable_yaml = [e for e in self.yaml_entries
                         if isinstance(e, dict) and not e.get("parent_only")]
        routable_json = [k for k, v in self.fingerprints.items()
                         if not v.get("parent_only")]
        self.assertEqual(len(routable_yaml), 30,
                        f"Expected 30 routable yaml entries, got {len(routable_yaml)}")
        self.assertEqual(len(routable_json), 30,
                        f"Expected 30 routable json entries, got {len(routable_json)}")

    def test_total_entries_31_in_both_files(self):
        """27 unchanged routable + 1 parent_only (MF-T02) + 3 children = 31 total."""
        self.assertEqual(len(self.yaml_entries), 31)
        self.assertEqual(len(self.fingerprints), 31)


if __name__ == "__main__":
    unittest.main(verbosity=2)
