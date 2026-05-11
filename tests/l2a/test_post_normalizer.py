"""P1-13.1 Option D Hybrid: post_normalizer unit tests."""
from __future__ import annotations

import unittest

from scripts.l2a.etl.post_normalizer import normalize, validate_and_repair
from scripts.l2a.etl.enums import (
    FormType,
    TreeStatus,
    ExclusionReason,
    IssueCode,
)


class TestPostNormalizer(unittest.TestCase):

    # ── Synonym mapping ──────────────────────────────────────────────────

    def test_noise_excluded_mapped_to_noise(self):
        out = normalize({"target_node": {}, "issue_codes": ["noise_excluded"]})
        self.assertEqual(out["issue_codes"], ["noise"])

    def test_chemical_monomer_excluded_mapped_to_chemical(self):
        out = normalize({"target_node": {}, "issue_codes": ["chemical_monomer_excluded"]})
        self.assertEqual(out["issue_codes"], ["chemical"])

    def test_ambiguous_canonical_id_mapped(self):
        out = normalize({"target_node": {}, "issue_codes": ["ambiguous_canonical_id"]})
        self.assertEqual(out["issue_codes"], ["canonical_id_ambiguity"])

    def test_structural_nesting_resolved_mapped(self):
        out = normalize({"target_node": {}, "issue_codes": ["structural_nesting_resolved"]})
        self.assertEqual(out["issue_codes"], ["malformed_cuisine_deep_nesting_corrected"])

    def test_synonym_mapping_dedup_preserves_order(self):
        out = normalize({"target_node": {}, "issue_codes": [
            "noise_excluded", "noise_excluded", "noise", "chemical_monomer_excluded"
        ]})
        self.assertEqual(out["issue_codes"], ["noise", "chemical"])

    def test_canonical_codes_passed_through(self):
        out = normalize({"target_node": {}, "issue_codes": ["zh_sci_mismatch", "chimera_node"]})
        self.assertEqual(out["issue_codes"], ["zh_sci_mismatch", "chimera_node"])

    # ── Enum validation / repair ─────────────────────────────────────────

    def test_invalid_form_type_default_ambiguous(self):
        out = normalize({"target_node": {"form_type": "category"}, "issue_codes": []})
        self.assertEqual(out["target_node"]["form_type"], FormType.AMBIGUOUS.value)
        self.assertIn(IssueCode.CANONICAL_ID_AMBIGUITY.value, out["issue_codes"])

    def test_valid_form_type_unchanged(self):
        out = normalize({"target_node": {"form_type": "species"}, "issue_codes": []})
        self.assertEqual(out["target_node"]["form_type"], "species")
        self.assertEqual(out["issue_codes"], [])

    def test_invalid_tree_status_default_needs_review(self):
        out = normalize({"target_node": {"tree_status": "invalid_status"}, "issue_codes": []})
        self.assertEqual(out["target_node"]["tree_status"], TreeStatus.NEEDS_REVIEW.value)

    def test_valid_tree_status_unchanged(self):
        for val in ("active", "excluded", "needs_review", "identity_conflict"):
            out = normalize({"target_node": {"tree_status": val}, "issue_codes": []})
            self.assertEqual(out["target_node"]["tree_status"], val)

    def test_verbose_exclusion_reason_mapped(self):
        out = normalize({
            "target_node": {"exclusion_reason": "chemical_monomer"},
            "issue_codes": [],
        })
        self.assertEqual(out["target_node"]["exclusion_reason"], ExclusionReason.CHEMICAL.value)

    def test_invalid_exclusion_reason_nullified(self):
        out = normalize({
            "target_node": {"exclusion_reason": "totally_made_up_reason"},
            "issue_codes": [],
        })
        self.assertIsNone(out["target_node"]["exclusion_reason"])

    # ── Idempotency ──────────────────────────────────────────────────────

    def test_idempotent_simple(self):
        x = {"target_node": {"form_type": "species"}, "issue_codes": ["zh_sci_mismatch"]}
        once = normalize(x)
        twice = normalize(once)
        self.assertEqual(once, twice)

    def test_idempotent_with_synonym_repair(self):
        x = {"target_node": {"form_type": "species"}, "issue_codes": ["noise_excluded"]}
        once = normalize(x)
        twice = normalize(once)
        self.assertEqual(once, twice)
        self.assertEqual(once["issue_codes"], ["noise"])

    def test_idempotent_with_invalid_form_type(self):
        x = {"target_node": {"form_type": "garbage"}, "issue_codes": []}
        once = normalize(x)
        twice = normalize(once)
        self.assertEqual(once, twice)

    # ── validate_and_repair returns repair log ───────────────────────────

    def test_validate_and_repair_returns_actions(self):
        _, repairs = validate_and_repair({
            "target_node": {"form_type": "category", "tree_status": "bad"},
            "issue_codes": ["noise_excluded"],
        })
        self.assertTrue(any("noise_excluded" in r for r in repairs))
        self.assertTrue(any("category" in r for r in repairs))
        self.assertTrue(any("bad" in r for r in repairs))

    def test_validate_and_repair_empty_when_clean(self):
        _, repairs = validate_and_repair({
            "target_node": {"form_type": "species", "tree_status": "active"},
            "issue_codes": [],
        })
        self.assertEqual(repairs, [])

    # ── Edge cases ───────────────────────────────────────────────────────

    def test_missing_target_node_handled(self):
        out = normalize({"issue_codes": ["noise_excluded"]})
        self.assertEqual(out["issue_codes"], ["noise"])
        self.assertEqual(out["target_node"], {})

    def test_non_string_issue_codes_filtered(self):
        out = normalize({"target_node": {}, "issue_codes": ["noise", None, 42, "chemical"]})
        self.assertEqual(out["issue_codes"], ["noise", "chemical"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestExcludedFallback(unittest.TestCase):
    """Round 1 follow-up: fallback for excluded without exclusion_reason."""

    def test_excluded_without_reason_filled(self):
        out, repairs = validate_and_repair({
            "target_node": {"tree_status": "excluded", "exclusion_reason": None},
            "issue_codes": [],
        })
        self.assertEqual(out["target_node"]["exclusion_reason"], "other")
        self.assertIn("auto_assigned_other_reason", out["issue_codes"])
        self.assertTrue(any("excluded_without_reason" in r for r in repairs))

    def test_excluded_with_reason_unchanged(self):
        out, repairs = validate_and_repair({
            "target_node": {"tree_status": "excluded", "exclusion_reason": "chemical"},
            "issue_codes": [],
        })
        self.assertEqual(out["target_node"]["exclusion_reason"], "chemical")
        self.assertNotIn("auto_assigned_other_reason", out["issue_codes"])

    def test_active_without_reason_unchanged(self):
        # tree_status='active' should NOT trigger fallback even if reason is None
        out, _ = validate_and_repair({
            "target_node": {"tree_status": "active", "exclusion_reason": None},
            "issue_codes": [],
        })
        self.assertIsNone(out["target_node"]["exclusion_reason"])
        self.assertNotIn("auto_assigned_other_reason", out["issue_codes"])
