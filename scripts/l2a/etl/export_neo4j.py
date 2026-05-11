"""Step 7: strict validation gates and Neo4j CSV export."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from scripts.l2a.etl.relationship_build import EDGE_TYPES, VALID_PROCESS_TYPES
from scripts.l2a.etl.utils.checkpointing import atomic_write_json


# P1-16 (D80 namespace isolation): label prefix to isolate L2a tree from
# P1-33 prototype data on the same Neo4j Community single-database instance.
# Default 'CKG_L2A_' separates 24,338 L2a-tree nodes from the 15-node P1-33 demo.
# Set env L2A_NEO4J_LABEL_PREFIX="" to revert to plain CKG_Ingredient labels.
import os as _os
LABEL_PREFIX = _os.environ.get("L2A_NEO4J_LABEL_PREFIX", "CKG_L2A_")
LABEL_INGREDIENT = f"{LABEL_PREFIX}Ingredient" if LABEL_PREFIX else "CKG_Ingredient"
LABEL_CUISINE = f"{LABEL_PREFIX}Cuisine" if LABEL_PREFIX else "CKG_Cuisine"
CONSTRAINT_INGREDIENT = LABEL_INGREDIENT.lower() + "_canonical_id_unique"
CONSTRAINT_CUISINE = LABEL_CUISINE.lower() + "_cuisine_id_unique"


HARD_FAIL_CHECKS = [
    "canonical_id_missing",
    "display_name_both_empty",
    "derived_from_process_type_invalid",
    "edge_target_missing",
    "identity_conflict_active",
    "cross_kingdom_isa",
    "isa_dag_cycle",
    "derived_from_dag_cycle",
]

HARD_FAIL_RULES = {
    "canonical_id_missing": lambda node: not node.get("canonical_id"),
    "display_name_both_empty": (
        lambda node: not node.get("display_name_zh")
        and not node.get("display_name_en")
        and node.get("tree_status") != "excluded"
    ),
    "identity_conflict_active": lambda node: node.get("tree_status") == "identity_conflict",
}

CUISINE_SEED_ROWS = [
    {"cuisine_id": "cantonese", "name_zh": "粤菜", "name_en": "Cantonese", "region": "southern_china"},
    {"cuisine_id": "sichuan", "name_zh": "川菜", "name_en": "Sichuan", "region": "western_china"},
    {"cuisine_id": "jiangnan", "name_zh": "苏浙菜", "name_en": "Jiangnan", "region": "eastern_china"},
    {"cuisine_id": "hainan", "name_zh": "海南菜", "name_en": "Hainanese", "region": "southern_china"},
    {"cuisine_id": "french", "name_zh": "法餐", "name_en": "French", "region": "france"},
    {"cuisine_id": "japanese", "name_zh": "日料", "name_en": "Japanese", "region": "japan"},
]

NODE_FIELDS = [
    "canonical_id",
    "display_name_zh",
    "display_name_en",
    "aliases",
    "scientific_name",
    "form_type",
    "value_kind",
    "tree_status",
    "exclusion_reason",
    "peak_season_codes",
    "peak_months",
    "seasonality_records",
    "dietary_flags",
    "allergens",
    "atom_id",
    "confidence_overall",
]
EDGE_FIELDS = {
    "IS_A": ["source", "target", "kind"],
    "PART_OF": ["source", "target", "part_role"],
    "DERIVED_FROM": ["source", "target", "process_type"],
    "HAS_CULINARY_ROLE": ["source", "target", "applications", "tips"],
}


def _node(record: dict[str, Any]) -> dict[str, Any]:
    return record.get("target_node") or record


def _status(record: dict[str, Any]) -> str:
    return _node(record).get("tree_status") or "unknown"


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _ingredient_node_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in payload.get("nodes", []):
        if _status(record) in {"excluded", "alias_redirect", "identity_conflict"}:
            continue
        node = _node(record)
        row = {field: _csv_value(node.get(field)) for field in NODE_FIELDS}
        row["atom_id"] = _csv_value(record.get("atom_id") or node.get("atom_id"))
        row["confidence_overall"] = _csv_value(record.get("confidence_overall"))
        rows.append(row)

    for stub in payload.get("stubs", []):
        row = {field: _csv_value(stub.get(field)) for field in NODE_FIELDS}
        row["atom_id"] = ""
        row["confidence_overall"] = ""
        rows.append(row)

    rows.sort(key=lambda row: row["canonical_id"])
    return rows


def validate_export_inputs_strict(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Return structured hard-fail rows. Empty means export can proceed."""
    failures: list[dict[str, str]] = []
    exported_node_ids = {
        row["canonical_id"] for row in _ingredient_node_rows(payload) if row.get("canonical_id")
    }
    cuisine_ids = {row["cuisine_id"] for row in CUISINE_SEED_ROWS}

    for record in payload.get("nodes", []):
        node = _node(record)
        if node.get("tree_status") in {"excluded", "alias_redirect", "stub"}:
            continue
        for rule_name, fn in HARD_FAIL_RULES.items():
            if fn(node):
                failures.append(
                    {
                        "rule": rule_name,
                        "atom_id": str(record.get("atom_id") or ""),
                        "details": str(node.get("canonical_id") or ""),
                    }
                )

    for edge in payload.get("edges", {}).get("DERIVED_FROM", []):
        if edge.get("process_type") not in VALID_PROCESS_TYPES:
            failures.append(
                {
                    "rule": "derived_from_process_type_invalid",
                    "atom_id": str(edge.get("source") or ""),
                    "details": str(edge.get("process_type") or ""),
                }
            )

    for edge_type in ("IS_A", "PART_OF", "DERIVED_FROM"):
        for edge in payload.get("edges", {}).get(edge_type, []):
            if edge.get("source") not in exported_node_ids or edge.get("target") not in exported_node_ids:
                failures.append(
                    {
                        "rule": "edge_target_missing",
                        "atom_id": str(edge.get("source") or ""),
                        "details": f"{edge_type}:{edge.get('source')}->{edge.get('target')}",
                    }
                )

    for edge in payload.get("edges", {}).get("HAS_CULINARY_ROLE", []):
        if edge.get("source") not in exported_node_ids or edge.get("target") not in cuisine_ids:
            failures.append(
                {
                    "rule": "edge_target_missing",
                    "atom_id": str(edge.get("source") or ""),
                    "details": f"HAS_CULINARY_ROLE:{edge.get('source')}->{edge.get('target')}",
                }
            )

    validation = payload.get("validation") or {}
    for cycle in validation.get("isa_cycles") or []:
        failures.append({"rule": "isa_dag_cycle", "atom_id": "", "details": " -> ".join(cycle)})
    for cycle in validation.get("derived_from_cycles") or []:
        failures.append({"rule": "derived_from_dag_cycle", "atom_id": "", "details": " -> ".join(cycle)})

    return failures


def validate_export_inputs(payload: dict[str, Any]) -> list[str]:
    """Backward-compatible summary of strict validation failures."""
    return sorted({failure["rule"] for failure in validate_export_inputs_strict(payload)})


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = fieldnames or sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_cypher_script(out_dir: Path) -> None:
    """Generate seed_ingredient_tree.cypher. Uses LABEL_INGREDIENT / LABEL_CUISINE
    constants so the script can target a namespaced label (CKG_L2A_Ingredient
    by default) and avoid colliding with P1-33 prototype's CKG_Ingredient nodes
    on the same Neo4j Community single-database instance.
    """
    cypher = f"""// Neo4j LOAD CSV seed script for L2a ingredient tree
// P1-16: namespace-isolated labels ({LABEL_INGREDIENT}, {LABEL_CUISINE})
// 与 P1-33 prototype 的 CKG_Ingredient/CKG_Cuisine 物理隔离（同 db，不同 label）

CREATE CONSTRAINT {CONSTRAINT_INGREDIENT} IF NOT EXISTS FOR (i:{LABEL_INGREDIENT}) REQUIRE i.canonical_id IS UNIQUE;
CREATE CONSTRAINT {CONSTRAINT_CUISINE} IF NOT EXISTS FOR (c:{LABEL_CUISINE}) REQUIRE c.cuisine_id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
CREATE (:{LABEL_INGREDIENT} {{
  canonical_id: row.canonical_id,
  display_name_zh: row.display_name_zh,
  display_name_en: row.display_name_en,
  aliases_json: row.aliases,
  scientific_name: row.scientific_name,
  form_type: row.form_type,
  value_kind: row.value_kind,
  tree_status: row.tree_status,
  exclusion_reason: row.exclusion_reason,
  peak_season_codes_json: row.peak_season_codes,
  peak_months_json: row.peak_months,
  seasonality_records_json: row.seasonality_records,
  dietary_flags_json: row.dietary_flags,
  allergens_json: row.allergens,
  atom_id: row.atom_id,
  confidence_overall: row.confidence_overall
}});

LOAD CSV WITH HEADERS FROM 'file:///is_a_edges.csv' AS row
MATCH (s:{LABEL_INGREDIENT} {{canonical_id: row.source}})
MATCH (t:{LABEL_INGREDIENT} {{canonical_id: row.target}})
CREATE (s)-[:IS_A {{kind: row.kind}}]->(t);

LOAD CSV WITH HEADERS FROM 'file:///part_of_edges.csv' AS row
MATCH (s:{LABEL_INGREDIENT} {{canonical_id: row.source}})
MATCH (t:{LABEL_INGREDIENT} {{canonical_id: row.target}})
CREATE (s)-[:PART_OF {{part_role: row.part_role}}]->(t);

LOAD CSV WITH HEADERS FROM 'file:///derived_from_edges.csv' AS row
MATCH (s:{LABEL_INGREDIENT} {{canonical_id: row.source}})
MATCH (t:{LABEL_INGREDIENT} {{canonical_id: row.target}})
CREATE (s)-[:DERIVED_FROM {{process_type: row.process_type}}]->(t);

LOAD CSV WITH HEADERS FROM 'file:///cuisines_seed.csv' AS row
CREATE (:{LABEL_CUISINE} {{
  cuisine_id: row.cuisine_id,
  name_zh: row.name_zh,
  name_en: row.name_en,
  region: row.region
}});

LOAD CSV WITH HEADERS FROM 'file:///has_culinary_role_edges.csv' AS row
MATCH (i:{LABEL_INGREDIENT} {{canonical_id: row.source}})
MATCH (c:{LABEL_CUISINE} {{cuisine_id: row.target}})
CREATE (i)-[:HAS_CULINARY_ROLE {{
  applications: row.applications,
  tips: row.tips
}}]->(c);
"""
    (out_dir / "seed_ingredient_tree.cypher").write_text(cypher, encoding="utf-8")


def write_qc_report(
    out_path: Path, payload: dict[str, Any], hard_failures: list[dict[str, str]]
) -> dict[str, Any]:
    nodes = payload.get("nodes", [])
    counts = Counter(_status(record) for record in nodes)
    edges = payload.get("edges", {})
    validation = payload.get("validation") or {}
    qc = {
        "atoms_total": len(nodes),
        "tree_status_counts": dict(counts),
        "stubs": len(payload.get("stubs", [])),
        "nodes_exported": len(_ingredient_node_rows(payload)),
        "edge_counts": {edge_type: len(edges.get(edge_type, [])) for edge_type in EDGE_TYPES},
        "orphan_stubs": validation.get("n_orphan_stubs", 0),
        "isa_cycles": len(validation.get("isa_cycles") or []),
        "derived_from_cycles": len(validation.get("derived_from_cycles") or []),
        "hard_fail_checks": HARD_FAIL_CHECKS,
        "hard_failures": hard_failures,
        "export_status": "ok" if not hard_failures else "failed",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump(qc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return qc


def run_export(*, input_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(input_path.read_text(encoding="utf-8")) if input_path.exists() else {
        "nodes": [],
        "edges": {edge_type: [] for edge_type in EDGE_TYPES},
        "stubs": [],
        "validation": {},
    }

    hard_failures = validate_export_inputs_strict(payload)
    qc_path = output_dir.parent / "qc_report.yaml"
    write_qc_report(qc_path, payload, hard_failures)
    if hard_failures:
        atomic_write_json(output_dir / "hard_failures.json", hard_failures)
        raise RuntimeError(f"Neo4j export blocked by {len(hard_failures)} hard failures")
    stale_failures = output_dir / "hard_failures.json"
    if stale_failures.exists():
        stale_failures.unlink()

    write_csv(output_dir / "nodes.csv", _ingredient_node_rows(payload), NODE_FIELDS)
    write_csv(output_dir / "cuisines_seed.csv", CUISINE_SEED_ROWS, ["cuisine_id", "name_zh", "name_en", "region"])
    for edge_type in EDGE_TYPES:
        filename = f"{edge_type.lower()}_edges.csv"
        write_csv(output_dir / filename, payload.get("edges", {}).get(edge_type, []), EDGE_FIELDS[edge_type])
    write_cypher_script(output_dir)

    return {
        "step": 7,
        "output_dir": str(output_dir),
        "qc_report": str(qc_path),
        "hard_failures": 0,
        "csv_files": [
            "nodes.csv",
            "is_a_edges.csv",
            "part_of_edges.csv",
            "derived_from_edges.csv",
            "has_culinary_role_edges.csv",
            "cuisines_seed.csv",
        ],
    }
