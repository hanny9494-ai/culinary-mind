"""P1-13.1 Option D Hybrid: prefilter unit tests."""
from __future__ import annotations

import unittest

from scripts.l2a.etl.prefilter import check
from scripts.l2a.etl.enums import (
    TreeStatus,
    FormType,
    ExclusionReason,
    IssueCode,
)


class TestPrefilter(unittest.TestCase):

    # ── Rule 1a: amino acid / pure chemical ──────────────────────────────

    def test_proline_excluded_chemical(self):
        atom = {"canonical_id": "proline", "scientific_name": "(S)-Pyrrolidine-2-carboxylic acid",
                "display_name_en": "Proline"}
        out = check(atom)
        self.assertIsNotNone(out)
        self.assertEqual(out["target_node"]["tree_status"], TreeStatus.EXCLUDED.value)
        self.assertEqual(out["target_node"]["exclusion_reason"], ExclusionReason.CHEMICAL.value)
        self.assertIn(IssueCode.CHEMICAL.value, out["issue_codes"])
        self.assertTrue(out["_prefilter_applied"])

    def test_ascorbic_acid_excluded_chemical(self):
        atom = {"canonical_id": "ascorbic_acid", "scientific_name": "L-ascorbic acid",
                "display_name_en": "Ascorbic acid"}
        out = check(atom)
        self.assertIsNotNone(out)
        self.assertEqual(out["target_node"]["exclusion_reason"], ExclusionReason.CHEMICAL.value)

    def test_iupac_stereo_excluded_chemical(self):
        atom = {"canonical_id": "some_chemical_compound", "scientific_name": "(R)-Pyrrolidine-2-carboxylic acid",
                "display_name_en": "stereo isomer"}
        out = check(atom)
        self.assertIsNotNone(out)
        self.assertEqual(out["target_node"]["exclusion_reason"], ExclusionReason.CHEMICAL.value)

    # ── Rule 2: data_incomplete ──────────────────────────────────────────

    def test_data_incomplete_excluded(self):
        atom = {"canonical_id": "green_mussel", "ingredient": "green mussel"}
        # No display_name_zh / display_name_en / scientific_name
        out = check(atom)
        self.assertIsNotNone(out)
        self.assertEqual(out["target_node"]["exclusion_reason"], ExclusionReason.DATA_INCOMPLETE.value)
        self.assertIn(IssueCode.DATA_INCOMPLETE.value, out["issue_codes"])

    def test_data_incomplete_falsy_strings_treated_as_missing(self):
        atom = {"canonical_id": "x", "display_name_zh": "", "display_name_en": "", "scientific_name": ""}
        out = check(atom)
        self.assertIsNotNone(out)
        self.assertEqual(out["target_node"]["exclusion_reason"], ExclusionReason.DATA_INCOMPLETE.value)

    # ── Rule 3: brand ────────────────────────────────────────────────────

    def test_100_grand_bar_excluded_brand(self):
        atom = {"canonical_id": "100_grand_bar", "display_name_en": "100 Grand Bar"}
        out = check(atom)
        self.assertIsNotNone(out)
        self.assertEqual(out["target_node"]["exclusion_reason"], ExclusionReason.BRAND.value)

    def test_after_eight_excluded_brand(self):
        atom = {"canonical_id": "after_eight", "display_name_en": "After Eight Mints"}
        out = check(atom)
        self.assertIsNotNone(out)
        self.assertEqual(out["target_node"]["exclusion_reason"], ExclusionReason.BRAND.value)

    # ── Rule 4: time_period (mapped to NOISE) ────────────────────────────

    def test_17th_century_excluded_noise(self):
        atom = {"canonical_id": "17th_century", "display_name_en": "17th Century cuisine"}
        out = check(atom)
        self.assertIsNotNone(out)
        self.assertEqual(out["target_node"]["exclusion_reason"], ExclusionReason.NOISE.value)
        self.assertIn(IssueCode.NOISE.value, out["issue_codes"])

    # ── Rule 5: babyfood ─────────────────────────────────────────────────

    def test_babyfood_excluded(self):
        atom = {"canonical_id": "babyfood_apple_puree", "display_name_en": "Apple puree (babyfood)"}
        out = check(atom)
        self.assertIsNotNone(out)
        self.assertEqual(out["target_node"]["exclusion_reason"], ExclusionReason.BABYFOOD.value)

    # ── Pass-through (None) cases ────────────────────────────────────────

    def test_chicken_returns_None(self):
        """Real food ingredients should pass through to LLM."""
        atom = {
            "canonical_id": "chicken",
            "display_name_zh": "鸡",
            "display_name_en": "chicken",
            "scientific_name": "Gallus gallus domesticus",
        }
        self.assertIsNone(check(atom))

    def test_bresse_chicken_returns_None_cultivar_exception(self):
        """Cultivar variety must pass through (cultivar exception)."""
        atom = {
            "canonical_id": "bresse_chicken",
            "display_name_zh": "布雷斯鸡",
            "display_name_en": "Bresse chicken",
            "scientific_name": "Gallus gallus domesticus (Bresse Gauloise)",
        }
        self.assertIsNone(check(atom))

    def test_russet_potato_returns_None_cultivar_exception(self):
        atom = {
            "canonical_id": "russet_potato",
            "display_name_zh": "褐皮土豆",
            "display_name_en": "russet potato",
            "scientific_name": "Solanum tuberosum",
        }
        self.assertIsNone(check(atom))

    def test_oyster_sauce_returns_None(self):
        """Processed sauce passes through; LLM applies STEP 3 rules."""
        atom = {
            "canonical_id": "oyster_sauce",
            "display_name_zh": "蚝油",
            "display_name_en": "oyster sauce",
            "scientific_name": "Crassostrea spp.",
        }
        self.assertIsNone(check(atom))

    # ── Stability / shape checks ─────────────────────────────────────────

    def test_excluded_node_has_required_schema_fields(self):
        atom = {"canonical_id": "proline", "scientific_name": "(S)-Pyrrolidine-2-carboxylic acid"}
        out = check(atom)
        self.assertIn("target_node", out)
        self.assertIn("edge_candidates", out)
        self.assertIn("confidence_overall", out)
        self.assertIn("issue_codes", out)
        self.assertIn("needs_human_review", out)
        # All edge_candidates lists empty
        for k in ("is_a", "part_of", "derived_from", "has_culinary_role"):
            self.assertEqual(out["edge_candidates"][k], [])

    def test_canonical_id_case_insensitive(self):
        atom_lower = {"canonical_id": "proline"}
        atom_upper = {"canonical_id": "PROLINE"}
        self.assertEqual(check(atom_lower)["target_node"]["exclusion_reason"],
                         check(atom_upper)["target_node"]["exclusion_reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
