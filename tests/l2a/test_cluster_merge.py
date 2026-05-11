from __future__ import annotations

from scripts.l2a.etl.cluster_merge import (
    apply_merge,
    check_cluster_consistency,
    group_by_scientific_name,
    run_cluster_merge,
)


def _rec(atom_id: str, sci: str, form: str = "species", status: str = "active") -> dict:
    return {
        "atom_id": atom_id,
        "target_node": {
            "canonical_id": atom_id,
            "display_name_zh": atom_id,
            "display_name_en": atom_id.replace("_", " "),
            "aliases": [],
            "scientific_name": sci,
            "form_type": form,
            "value_kind": "representative_average",
            "tree_status": status,
        },
        "edge_candidates": {"is_a": [], "part_of": [], "derived_from": [], "has_culinary_role": []},
    }


def test_group_by_scientific_name_normalizes_case_and_space():
    records = [_rec("a", " Gallus gallus "), _rec("b", "gallus gallus"), _rec("c", "Bos taurus")]

    grouped = group_by_scientific_name(records)

    assert set(grouped) == {"gallus gallus", "bos taurus"}
    assert [record["atom_id"] for record in grouped["gallus gallus"]] == ["a", "b"]


def test_species_cluster_merges_to_most_complete_record():
    records = [_rec("a", "Bos taurus"), _rec("b", "Bos taurus")]
    records[1]["target_node"]["aliases"] = ["cow"]

    decision = check_cluster_consistency(records)

    assert decision["decision"] == "merge"
    assert decision["canonical_atom_id"] == "b"


def test_apply_merge_marks_redirect_and_preserves_aliases():
    records = [_rec("beef_a", "Bos taurus"), _rec("beef_b", "Bos taurus")]

    canonical, redirects = apply_merge(records, "beef_a")

    assert canonical["target_node"]["source_atom_ids"] == ["beef_a", "beef_b"]
    assert redirects[0]["target_node"]["tree_status"] == "alias_redirect"
    assert redirects[0]["target_node"]["preferred_canonical_id"] == "beef_a"


def test_variety_species_cluster_splits():
    records = [_rec("chicken", "Gallus gallus", "species"), _rec("bresse_chicken", "Gallus gallus", "variety")]

    decision = check_cluster_consistency(records)

    assert decision["decision"] == "split"
    assert decision["canonical_atom_id"] == "chicken"


def test_identity_conflict_cluster_is_quarantined_by_run(tmp_path):
    records = [_rec("a", "Foo bar", status="identity_conflict"), _rec("b", "Foo bar")]
    out = tmp_path / "step5.json"

    run_cluster_merge(records=records, output_path=out)

    assert records[0]["target_node"]["tree_status"] == "excluded"
    assert records[0]["target_node"]["exclusion_reason"] == "identity_conflict_cluster_outlier"
