"""P1-13~16 Option D Hybrid: Python pre-filter for deterministic hard-prune.

Per architect 047 + GPT 5.5 review:
- amino acid lookup / null check / brand pattern matching are deterministic
  Python tasks, not LLM tasks (`STRICT MUST` failures in prompt-only path
  proved this empirically).
- Pre-filter runs BEFORE the LLM call. If atom matches a hard-prune
  category, returns an excluded stub node directly without LLM round-trip.
- Conservative bias: false positives are worse than false negatives
  (a missed exclusion just costs one extra LLM call; a wrong exclusion
  silently drops a valid food atom). Slug-pattern matches use exact
  canonical_id substrings only.

Used by `main_distill.py`:

    result = prefilter.check(raw_atom)
    if result is not None:
        # Hard-prune hit, skip LLM
        return result
    # else fall through to LLM call
"""
from __future__ import annotations

import re
from typing import Any

from .enums import (
    KNOWN_AMINO_ACIDS,
    KNOWN_PURE_CHEMICALS,
    KNOWN_BRAND_PATTERNS,
    KNOWN_TIME_PERIOD_PATTERNS,
    KNOWN_BABYFOOD_PATTERNS,
    KNOWN_CULTIVAR_EXCEPTIONS,
    TreeStatus,
    FormType,
    ExclusionReason,
    IssueCode,
)


# Compile regex patterns once
_BRAND_RE = [re.compile(p) for p in KNOWN_BRAND_PATTERNS]
_TIME_RE = [re.compile(p) for p in KNOWN_TIME_PERIOD_PATTERNS]
_BABYFOOD_RE = [re.compile(p) for p in KNOWN_BABYFOOD_PATTERNS]
_IUPAC_STEREO_RE = re.compile(r"^\(([SR])\)-")

# Latin binomial slug pattern (genus_species, lowercase). Matches:
#   abralia_multihamata, panthera_tigris
# Will also match English compounds like chicken_skin / pork_belly, but those
# are real foods that should pass through to the LLM anyway. Conservative.
_BINOMIAL_RE = re.compile(r"^[a-z][a-z]+_[a-z][a-z]+(_(var|spp|subsp|f))?$")

# Brand false-positive guard. Any of these substrings means "not a brand":
#   _percent_   (descriptive, e.g. 100_percent_unsweetened_chocolate)
_BRAND_FALSE_POS_SUBSTRINGS = ("_percent_",)
_BRAND_FALSE_POS_EXACT = frozenset({
    "00_flour", "0_flour", "0_grade_flour", "tipo_00_flour",
})


def check(raw_atom: dict[str, Any]) -> dict[str, Any] | None:
    """Apply hard-prune rules in priority order.

    Returns:
        None  → atom should go through the LLM (default).
        dict  → excluded stub node ready for staging write.
    """
    canonical_id = (raw_atom.get("canonical_id") or "").strip()
    canonical_lower = canonical_id.lower()

    # Cultivar exceptions short-circuit: never hard-prune these even if
    # their canonical_id pattern would otherwise match.
    if canonical_lower in KNOWN_CULTIVAR_EXCEPTIONS:
        return None

    sci = (raw_atom.get("scientific_name") or "").strip()

    # display_name may be either nested dict {zh, en} (Shape B atoms, ~80%)
    # OR flat fields display_name_zh / display_name_en (legacy Shape).
    # Read both paths.
    display_zh = (raw_atom.get("display_name_zh") or "").strip()
    display_en = (raw_atom.get("display_name_en") or "").strip()
    display_dn = raw_atom.get("display_name")
    if isinstance(display_dn, dict):
        display_zh = display_zh or (display_dn.get("zh") or "").strip()
        display_en = display_en or (display_dn.get("en") or "").strip()

    # `ingredient` field — Shape A atoms (Latin binomial seafood, ~16%)
    # have ingredient = canonical_id (Latin name) but no scientific_name field.
    ingredient = (raw_atom.get("ingredient") or "").strip()
    ingredient_is_canonical_label = ingredient.lower().replace(" ", "_") == canonical_lower

    # Rule 1a: known amino acid / pure chemical canonical_id (exact match)
    if canonical_lower in KNOWN_AMINO_ACIDS or canonical_lower in KNOWN_PURE_CHEMICALS:
        return _make_excluded_node(
            raw_atom, ExclusionReason.CHEMICAL, [IssueCode.CHEMICAL]
        )

    # Rule 1b: IUPAC stereo prefix in scientific_name (e.g. "(S)-Pyrrolidine-...")
    if sci and _IUPAC_STEREO_RE.match(sci):
        return _make_excluded_node(
            raw_atom, ExclusionReason.CHEMICAL, [IssueCode.CHEMICAL]
        )

    # Rule 2 (architect 048 fix): data_incomplete — atom has NO identity signal
    # in any commonly-used field.
    # An atom is identifiable if ANY of:
    #   - scientific_name has text
    #   - display_name (zh|en, dict or flat) has text
    #   - ingredient has text beyond a restatement of canonical_id
    has_identity_signal = bool(
        sci or display_zh or display_en or (ingredient and not ingredient_is_canonical_label)
    )
    if not has_identity_signal:
        return _make_excluded_node(
            raw_atom, ExclusionReason.DATA_INCOMPLETE, [IssueCode.DATA_INCOMPLETE]
        )

    # Rule 3: time_period (mapped to NOISE per cc-lead decision 4)
    # Checked BEFORE brand because `17th_century` starts with a digit and would
    # otherwise be wrongly tagged brand by the broad `^\d` pattern.
    for pat in _TIME_RE:
        if pat.search(canonical_lower):
            return _make_excluded_node(
                raw_atom, ExclusionReason.NOISE, [IssueCode.NOISE]
            )

    # Rule 4: brand (with false-positive guards per architect 048)
    if (
        canonical_lower not in _BRAND_FALSE_POS_EXACT
        and not any(s in canonical_lower for s in _BRAND_FALSE_POS_SUBSTRINGS)
    ):
        for pat in _BRAND_RE:
            if pat.search(canonical_lower):
                return _make_excluded_node(
                    raw_atom, ExclusionReason.BRAND, [IssueCode.BRAND]
                )

    # Rule 5: babyfood
    for pat in _BABYFOOD_RE:
        if pat.search(canonical_lower):
            return _make_excluded_node(
                raw_atom, ExclusionReason.BABYFOOD, [IssueCode.BABYFOOD]
            )

    return None  # let LLM handle


def _make_excluded_node(
    raw_atom: dict[str, Any],
    reason: ExclusionReason,
    issue_codes: list[IssueCode],
) -> dict[str, Any]:
    """Build excluded stub node directly (no LLM round-trip)."""
    canonical_id = raw_atom.get("canonical_id", "")
    return {
        "atom_id": canonical_id,
        "target_node": {
            "canonical_id": canonical_id,
            "display_name_zh": raw_atom.get("display_name_zh"),
            "display_name_en": raw_atom.get("display_name_en"),
            "aliases": [],
            "scientific_name": None,
            "form_type": FormType.COMPOSITE.value,
            "value_kind": "representative_average",
            "tree_status": TreeStatus.EXCLUDED.value,
            "exclusion_reason": reason.value,
            "peak_season_codes": [],
            "peak_months": [],
            "seasonality_records": [],
            "dietary_flags": [],
            "allergens": [],
        },
        "edge_candidates": {
            "is_a": [],
            "part_of": [],
            "derived_from": [],
            "has_culinary_role": [],
        },
        "confidence_overall": 1.0,
        "issue_codes": [c.value for c in issue_codes],
        "evidence_split_candidates": [],
        "needs_human_review": False,
        "_prefilter_applied": True,
        "_prefilter_rule": reason.value,
    }
