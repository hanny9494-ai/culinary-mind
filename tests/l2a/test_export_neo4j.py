from __future__ import annotations

import csv

from scripts.l2a.etl.export_neo4j import (
    validate_export_inputs_strict,
    write_csv,
    write_cypher_script,
)


def test_validate_export_inputs_strict_flags_active_identity_conflict():
    payload = {
        "nodes": [
            {
                "atom_id": "bad",
                "target_node": {
                    "canonical_id": "bad",
                    "display_name_en": "bad",
                    "tree_status": "identity_conflict",
                },
            }
        ],
        "edges": {"IS_A": [], "PART_OF": [], "DERIVED_FROM": [], "HAS_CULINARY_ROLE": []},
        "validation": {},
    }

    failures = validate_export_inputs_strict(payload)

    assert failures == [{"rule": "identity_conflict_active", "atom_id": "bad", "details": "bad"}]


def test_validate_export_inputs_strict_flags_bad_process_type_and_cycles():
    payload = {
        "nodes": [
            {"atom_id": "a", "target_node": {"canonical_id": "a", "display_name_en": "a", "tree_status": "active"}},
            {"atom_id": "b", "target_node": {"canonical_id": "b", "display_name_en": "b", "tree_status": "active"}},
        ],
        "edges": {
            "IS_A": [],
            "PART_OF": [],
            "DERIVED_FROM": [{"source": "a", "target": "b", "process_type": "fried"}],
            "HAS_CULINARY_ROLE": [],
        },
        "validation": {"isa_cycles": [["a", "b", "a"]], "derived_from_cycles": []},
    }

    rules = {failure["rule"] for failure in validate_export_inputs_strict(payload)}

    assert rules == {"derived_from_process_type_invalid", "isa_dag_cycle"}


def test_write_csv_writes_header_for_empty_rows(tmp_path):
    out = tmp_path / "empty.csv"

    write_csv(out, [], ["source", "target"])

    assert out.read_text(encoding="utf-8").splitlines() == ["source,target"]


def test_write_csv_round_trips_rows(tmp_path):
    out = tmp_path / "rows.csv"

    write_csv(out, [{"source": "a", "target": "b"}], ["source", "target"])

    with out.open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle)) == [{"source": "a", "target": "b"}]


def test_write_cypher_script_contains_load_csv(tmp_path):
    write_cypher_script(tmp_path)

    text = (tmp_path / "seed_ingredient_tree.cypher").read_text(encoding="utf-8")
    assert "LOAD CSV WITH HEADERS FROM 'file:///nodes.csv'" in text
    assert "HAS_CULINARY_ROLE" in text
