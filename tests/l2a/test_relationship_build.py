from __future__ import annotations

from scripts.l2a.etl.relationship_build import (
    break_dag_cycles,
    build_orphan_stubs,
    detect_dag_cycles,
    normalize_edges_from_record,
)


def test_normalize_edges_extracts_all_ingredient_edge_types():
    rec = {
        "target_node": {"canonical_id": "toasted_wheat", "tree_status": "active"},
        "edge_candidates": {
            "is_a": [{"target_canonical_id": "grain", "kind": "category"}],
            "part_of": [{"target_canonical_id": "wheat", "part_role": "seed"}],
            "derived_from": [{"target_canonical_id": "wheat", "process_type": "baking"}],
            "has_culinary_role": [{"target_cuisine_id": "french", "applications": ["bread"], "tips": ["toast"]}],
        },
    }

    edges = normalize_edges_from_record(rec, {"toasted_wheat", "grain", "wheat"})

    assert edges["IS_A"] == [{"source": "toasted_wheat", "target": "grain", "kind": "category"}]
    assert edges["PART_OF"] == [{"source": "toasted_wheat", "target": "wheat", "part_role": "seed"}]
    assert edges["DERIVED_FROM"] == [{"source": "toasted_wheat", "target": "wheat", "process_type": "roasted"}]
    assert edges["HAS_CULINARY_ROLE"][0]["target"] == "french"


def test_unknown_process_type_defaults_to_mixed():
    rec = {
        "target_node": {"canonical_id": "snack", "tree_status": "active"},
        "edge_candidates": {"derived_from": [{"source_canonical_id": "almond", "process_type": "inclusion"}]},
    }

    edges = normalize_edges_from_record(rec, {"snack", "almond"})

    assert edges["DERIVED_FROM"][0]["process_type"] == "mixed"


def test_detect_dag_cycles_returns_cycle_path():
    cycles = detect_dag_cycles([
        {"source": "a", "target": "b"},
        {"source": "b", "target": "c"},
        {"source": "c", "target": "a"},
    ])

    assert cycles == [["a", "b", "c", "a"]]


def test_break_dag_cycles_removes_closing_edge():
    remaining, removed, initial = break_dag_cycles([
        {"source": "canola_oil", "target": "canola"},
        {"source": "canola", "target": "canola_oil"},
    ])

    assert initial == [["canola", "canola_oil", "canola"]]
    assert removed == [{"source": "canola", "target": "canola_oil"}]
    assert detect_dag_cycles(remaining) == []


def test_build_orphan_stubs_only_for_ingredient_edges():
    stubs = build_orphan_stubs(
        {
            "IS_A": [{"source": "child", "target": "parent"}],
            "PART_OF": [],
            "DERIVED_FROM": [],
            "HAS_CULINARY_ROLE": [{"source": "child", "target": "french"}],
        },
        {"child"},
    )

    assert [stub["canonical_id"] for stub in stubs] == ["parent"]
    assert stubs[0]["tree_status"] == "stub"
