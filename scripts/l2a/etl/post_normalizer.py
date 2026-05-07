"""P1-13~16 Option D Hybrid: post-normalize LLM output to canonical schema.

Per architect 047 + GPT 5.5 review: enum vocabulary control belongs in
Python post-processing, not in the LLM prompt (STEP 12 over-engineering
caused regression — LLM emitted novel synonyms like 'noise_excluded').

Runs AFTER each LLM call, BEFORE the staging write. Idempotent: calling
twice on the same input returns the same result.

Usage:
    normalized = post_normalizer.normalize(llm_output)

Or with debug repair log:
    normalized, repairs = post_normalizer.validate_and_repair(llm_output)
"""
from __future__ import annotations

from typing import Any

from .enums import (
    ISSUE_CODE_SYNONYMS,
    FormType,
    TreeStatus,
    ExclusionReason,
    IssueCode,
)


_VALID_FORM_TYPES = frozenset(e.value for e in FormType)
_VALID_TREE_STATUSES = frozenset(e.value for e in TreeStatus)
_VALID_EXCLUSION_REASONS = frozenset(e.value for e in ExclusionReason)


def normalize(llm_output: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM output to canonical schema.

    Idempotent: ``normalize(normalize(x)) == normalize(x)``.
    """
    normalized, _ = validate_and_repair(llm_output)
    return normalized


def validate_and_repair(
    llm_output: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Like :func:`normalize` but also returns the list of repair actions
    applied. Useful for debugging and audit logs.
    """
    out: dict[str, Any] = {**llm_output}
    repairs: list[str] = []

    # ── 1. issue_codes synonym mapping + dedup, preserve order ──
    raw_issues = out.get("issue_codes") or []
    canonical_issues: list[str] = []
    seen: set[str] = set()
    for code in raw_issues:
        if not isinstance(code, str):
            continue
        canonical = ISSUE_CODE_SYNONYMS.get(code, code)
        if canonical != code:
            repairs.append(f"normalized_issue_code: {code!r} -> {canonical!r}")
        if canonical not in seen:
            canonical_issues.append(canonical)
            seen.add(canonical)
    out["issue_codes"] = canonical_issues

    # ── 2. validate target_node enums ──
    target = dict(out.get("target_node") or {})

    ft = target.get("form_type")
    if ft is not None and ft not in _VALID_FORM_TYPES:
        repairs.append(f"invalid_form_type: {ft!r} -> 'ambiguous'")
        target["form_type"] = FormType.AMBIGUOUS.value
        if IssueCode.CANONICAL_ID_AMBIGUITY.value not in canonical_issues:
            canonical_issues.append(IssueCode.CANONICAL_ID_AMBIGUITY.value)

    ts = target.get("tree_status")
    if ts is not None and ts not in _VALID_TREE_STATUSES:
        repairs.append(f"invalid_tree_status: {ts!r} -> 'needs_review'")
        target["tree_status"] = TreeStatus.NEEDS_REVIEW.value

    er = target.get("exclusion_reason")
    if er is not None and er not in _VALID_EXCLUSION_REASONS:
        # Map common verbose forms back to short canonical
        verbose_map = {
            "chemical_monomer": ExclusionReason.CHEMICAL.value,
            "data_incomplete_required_fields_missing": ExclusionReason.DATA_INCOMPLETE.value,
            "noise_time_period": ExclusionReason.NOISE.value,
            "abstract_token": ExclusionReason.ABSTRACT.value,
        }
        if er in verbose_map:
            repairs.append(f"verbose_exclusion_reason: {er!r} -> {verbose_map[er]!r}")
            target["exclusion_reason"] = verbose_map[er]
        else:
            repairs.append(f"invalid_exclusion_reason: {er!r} -> None")
            target["exclusion_reason"] = None

    out["target_node"] = target
    out["issue_codes"] = canonical_issues  # rewrite if any repair appended

    return out, repairs
