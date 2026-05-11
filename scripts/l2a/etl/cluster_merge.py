"""Step 5: cluster atoms by scientific_name, then merge/split/quarantine."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.l2a.etl.utils.checkpointing import atomic_write_json


def group_by_scientific_name(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group records by target_node.scientific_name after lowercase stripping."""
    clusters: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        node = rec.get("target_node") or {}
        sci = node.get("scientific_name")
        if not isinstance(sci, str):
            continue
        key = sci.strip().lower()
        if key:
            clusters.setdefault(key, []).append(rec)
    return clusters


def _node(rec: dict[str, Any]) -> dict[str, Any]:
    return rec.setdefault("target_node", {})


def _safe_form_type(rec: dict[str, Any]) -> str:
    return _node(rec).get("form_type") or "unknown"


def _tree_status(rec: dict[str, Any]) -> str:
    return _node(rec).get("tree_status") or "unknown"


def _completeness_score(rec: dict[str, Any]) -> int:
    """Higher means the record is a better canonical representative."""
    node = rec.get("target_node") or {}
    score = 0
    for field in (
        "display_name_zh",
        "display_name_en",
        "scientific_name",
        "form_type",
        "value_kind",
        "tree_status",
    ):
        if node.get(field):
            score += 1
    score += len(node.get("aliases") or [])
    score += len(node.get("dietary_flags") or [])
    score += len(node.get("seasonality_records") or [])
    for values in (rec.get("edge_candidates") or {}).values():
        if isinstance(values, list):
            score += len(values)
    return score


def check_cluster_consistency(atoms: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a deterministic merge/split/conflict decision for one sci cluster."""
    if len(atoms) <= 1:
        return {"decision": "noop", "rationale": "single atom"}

    conflict_atoms = [
        atom for atom in atoms if _tree_status(atom) == "identity_conflict"
    ]
    if conflict_atoms:
        return {
            "decision": "identity_conflict",
            "rationale": f"{len(conflict_atoms)}/{len(atoms)} atoms flagged identity_conflict",
            "outlier_atom_ids": [
                atom.get("atom_id") for atom in conflict_atoms if atom.get("atom_id")
            ],
        }

    forms = Counter(_safe_form_type(atom) for atom in atoms)
    active_atoms = [
        atom
        for atom in atoms
        if _tree_status(atom) not in {"excluded", "alias_redirect", "identity_conflict"}
    ]
    if len(active_atoms) <= 1:
        return {"decision": "noop", "rationale": "cluster has <=1 active atom"}

    if forms.get("species", 0) == len(atoms):
        canonical = max(active_atoms, key=_completeness_score)
        return {
            "decision": "merge",
            "rationale": "all records are species form_type",
            "canonical_atom_id": canonical.get("atom_id"),
        }

    if forms.get("variety", 0) >= 1 and forms.get("species", 0) >= 1:
        species = [atom for atom in active_atoms if _safe_form_type(atom) == "species"]
        canonical = max(species, key=_completeness_score) if species else None
        return {
            "decision": "split",
            "rationale": f"variety+species mix ({dict(forms)})",
            "canonical_atom_id": canonical.get("atom_id") if canonical else None,
        }

    return {"decision": "noop", "rationale": f"heterogeneous forms ({dict(forms)})"}


def apply_merge(
    atoms: list[dict[str, Any]], canonical_atom_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Mark non-canonical same-species records as alias redirects."""
    canonical = next(atom for atom in atoms if atom.get("atom_id") == canonical_atom_id)
    canonical_node = _node(canonical)
    canonical_id = canonical_node.get("canonical_id")
    aliases = list(canonical_node.get("aliases") or [])
    source_atom_ids = set(canonical_node.get("source_atom_ids") or [])
    if canonical.get("atom_id"):
        source_atom_ids.add(canonical["atom_id"])

    redirects: list[dict[str, Any]] = []
    for other in atoms:
        if other.get("atom_id") == canonical_atom_id:
            continue
        other_node = _node(other)
        if other_node.get("tree_status") == "excluded":
            continue
        other_node["tree_status"] = "alias_redirect"
        other_node["preferred_canonical_id"] = canonical_id
        other_node["_cluster_merged_into_atom_id"] = canonical_atom_id
        for name in (other_node.get("display_name_zh"), other_node.get("display_name_en")):
            if name and name not in aliases:
                aliases.append(name)
        if other.get("atom_id"):
            source_atom_ids.add(other["atom_id"])
        redirects.append(other)

    canonical_node["aliases"] = aliases
    canonical_node["source_atom_ids"] = sorted(source_atom_ids)
    return canonical, redirects


def _quarantine_identity_conflict(rec: dict[str, Any], reason: str) -> None:
    node = _node(rec)
    node["_previous_tree_status"] = node.get("tree_status")
    node["tree_status"] = "excluded"
    node["exclusion_reason"] = reason
    rec.setdefault("issue_codes", [])
    if "identity_conflict_quarantined" not in rec["issue_codes"]:
        rec["issue_codes"].append("identity_conflict_quarantined")


def _load_records(input_path: Path | None) -> list[dict[str, Any]]:
    if input_path and input_path.exists():
        data = json.loads(input_path.read_text(encoding="utf-8"))
        return data.get("results", data if isinstance(data, list) else [])

    from scripts.l2a.etl._load_distilled import load_all_distilled

    return load_all_distilled()


def run_cluster_merge(
    *,
    output_path: Path,
    input_path: Path | None = None,
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run Step 5 and write results plus cluster summary."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = records if records is not None else _load_records(input_path)

    clusters = group_by_scientific_name(records)
    decisions: Counter[str] = Counter()
    redirect_count = 0

    for atoms in clusters.values():
        if len(atoms) <= 1:
            decisions["singleton"] += 1
            continue
        decision = check_cluster_consistency(atoms)
        decisions[decision["decision"]] += 1
        if decision["decision"] == "merge" and decision.get("canonical_atom_id"):
            _, redirects = apply_merge(atoms, decision["canonical_atom_id"])
            redirect_count += len(redirects)
        elif decision["decision"] == "identity_conflict":
            for atom_id in decision.get("outlier_atom_ids", []):
                rec = next((atom for atom in atoms if atom.get("atom_id") == atom_id), None)
                if rec:
                    _quarantine_identity_conflict(rec, "identity_conflict_cluster_outlier")

    singleton_conflicts = 0
    for rec in records:
        if _tree_status(rec) == "identity_conflict":
            singleton_conflicts += 1
            _quarantine_identity_conflict(rec, "identity_conflict_unresolved")
    if singleton_conflicts:
        decisions["identity_conflict_singleton"] += singleton_conflicts

    payload = {
        "results": records,
        "cluster_summary": dict(decisions),
        "n_records": len(records),
        "n_clusters": len(clusters),
        "n_alias_redirects_created": redirect_count,
    }
    atomic_write_json(output_path, payload)
    return {
        "step": 5,
        "n_records": len(records),
        "n_clusters": len(clusters),
        "decisions": dict(decisions),
        "n_alias_redirects_created": redirect_count,
        "output": str(output_path),
    }
