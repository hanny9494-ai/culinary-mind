"""P1-Px1: Prompt registry consistency + regression tests."""
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config/prompts/registry.yaml"


class TestPromptRegistry(unittest.TestCase):
    def setUp(self):
        if yaml is None:
            self.skipTest("PyYAML not installed")
        self.registry = yaml.safe_load(open(REGISTRY))

    def test_registry_loadable(self):
        self.assertIn("prompts", self.registry)
        self.assertGreater(len(self.registry["prompts"]), 0)

    def test_every_prompt_has_required_fields(self):
        required = ["id", "version", "status", "model", "template_file"]
        for p in self.registry["prompts"]:
            for field in required:
                self.assertIn(field, p, f"Prompt {p.get('id')} missing {field}")

    def test_unique_ids(self):
        ids = [p["id"] for p in self.registry["prompts"]]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate prompt IDs")

    def test_production_has_test_coverage(self):
        """production prompts MUST have non-none test_coverage."""
        for p in self.registry["prompts"]:
            if p["status"] == "production":
                self.assertNotEqual(
                    p.get("test_coverage", "none"), "none",
                    f"Production prompt {p['id']} has no test coverage"
                )

    def test_semver_format(self):
        import re
        for p in self.registry["prompts"]:
            self.assertRegex(p["version"], r"^\d+\.\d+\.\d+$",
                            f"Prompt {p['id']} version not semver")


if __name__ == "__main__":
    unittest.main(verbosity=2)
