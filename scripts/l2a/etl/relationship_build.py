"""Step 6: derive normalized edge rows and validate directed acyclic graphs."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.l2a.etl.utils.checkpointing import atomic_write_json


VALID_PROCESS_TYPES = {
    "dried",
    "fermented",
    "cured",
    "smoked",
    "cooked",
    "roasted",
    "frozen",
    "milled",
    "pressed",
    "extracted",
    "mixed",
    "pickled",
    "aged",
}

PROCESS_TYPE_SYNONYMS = {
    "drying": "dried",
    "dehydrated": "dried",
    "dehydration": "dried",
    "fermentation": "fermented",
    "curing": "cured",
    "smoking": "smoked",
    "frying": "cooked",
    "boiled": "cooked",
    "boiling": "cooked",
    "steamed": "cooked",
    "steaming": "cooked",
    "baked": "roasted",
    "baking": "roasted",
    "toasted": "roasted",
    "roasting": "roasted",
    "freezing": "frozen",
    "milling": "milled",
    "ground": "milled",
    "grinding": "milled",
    "pressing": "pressed",
    "extraction": "extracted",
    "pickling": "pickled",
    "aging": "aged",
}

EDGE_TYPES = ("IS_A", "PART_OF", "DERIVED_FROM", "HAS_CULINARY_ROLE")
CUISINE_IDS = {"cantonese", "sichuan", "jiangnan", "hainan", "french", "japanese"}


def _node(rec: dict[str, Any]) -> dict[str, Any]:
    return rec.get("target_node") or {}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item is not None)
    return str(value)


def _normalize_process_type(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "mixed"
    raw = value.strip().lower().replace("-", "_").replace(" ", "_")
    if raw in VALID_PROCESS_TYPES:
        return raw
    return PROCESS_TYPE_SYNONYMS.get(raw, "mixed")


def _candidate_target(candidate: Any, *keys: str) -> str | None:
    if isinstance(candidate, str):
        return candidate
    if not isinstance(candidate, dict):
        return None
    for key in keys:
        value = candidate.get(key)
        if value:
            return str(value)
    return None


def normalize_edges_from_record(
    rec: dict[str, Any], canonical_ids: set[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Extract deterministic edge rows from one record's edge_candidates."""
    del canonical_ids  # Kept for backwards-compatible tests/callers.
    edges: dict[str, list[dict[str, Any]]] = {edge_type: [] for edge_type in EDGE_TYPES}
    source_id = _node(rec).get("canonical_id")
    if not source_id:
        return edges

    candidates = rec.get("edge_candidates") or {}

    for candidate in candidates.get("is_a") or []:
        target = _candidate_target(candidate, "target_canonical_id", "target")
        if target and target != source_id:
            edges["IS_A"].append(
                {
                    "source": source_id,
                    "target": target,
                    "kind": candidate.get("kind") if isinstance(candidate, dict) else "",
                }
            )

    for candidate in candidates.get("part_of") or []:
        target = _candidate_target(candidate, "target_canonical_id", "parent_canonical_id", "target")
        if target and target != source_id:
            edges["PART_OF"].append(
                {
                    "source": source_id,
                    "target": target,
                    "part_role": candidate.get("part_role") if isinstance(candidate, dict) else "",
                }
            )

    for candidate in candidates.get("derived_from") or []:
        target = _candidate_target(
            candidate,
            "target_canonical_id",
            "source_canonical_id",
            "parent_canonical_id",
            "target",
            "source",
        )
        if target and target != source_id:
            process_type = candidate.get("process_type") if isinstance(candidate, dict) else None
            edges["DERIVED_FROM"].append(
                {
                    "source": source_id,
                    "target": target,
                    "process_type": _normalize_process_type(process_type),
                }
            )

    for candidate in candidates.get("has_culinary_role") or []:
        if isinstance(candidate, str):
            cuisine_id = candidate if candidate in CUISINE_IDS else None
            applications = ""
            tips = ""
        elif isinstance(candidate, dict):
            cuisine_id = candidate.get("cuisine_id") or candidate.get("target_cuisine_id")
            target = candidate.get("target_canonical_id")
            if not cuisine_id and target in CUISINE_IDS:
                cuisine_id = target
            applications = _as_text(candidate.get("applications") or candidate.get("role") or candidate.get("kind"))
            tips = _as_text(candidate.get("tips"))
        else:
            continue
        if cuisine_id:
            edges["HAS_CULINARY_ROLE"].append(
                {
                    "source": source_id,
                    "target": str(cuisine_id),
                    "applications": applications,
                    "tips": tips,
                }
            )

    return edges


def dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[tuple[str, str], ...]] = set()
    unique: list[dict[str, Any]] = []
    for edge in edges:
        key = tuple(sorted((str(k), str(v)) for k, v in edge.items()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(edge)
    return unique


def detect_dag_cycles(edges: list[dict[str, Any]]) -> list[list[str]]:
    """Return unique cycle paths in a directed graph."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source and target:
            adjacency[str(source)].add(str(target))

    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []
    cycles: list[list[str]] = []

    def dfs(node: str) -> None:
        if node in visiting:
            index = path.index(node)
            cycles.append(path[index:] + [node])
            return
        if node in visited:
            return
        visiting.add(node)
        path.append(node)
        for next_node in sorted(adjacency.get(node, ())):
            dfs(next_node)
        path.pop()
        visiting.remove(node)
        visited.add(node)

    for start in sorted(adjacency):
        if start not in visited:
            dfs(start)

    unique_cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for cycle in cycles:
        cycle_key = tuple(sorted(set(cycle)))
        if cycle_key not in seen:
            seen.add(cycle_key)
            unique_cycles.append(cycle)
    return unique_cycles


def _cycle_edge_to_remove(cycle: list[str]) -> tuple[str, str]:
    pairs = list(zip(cycle[:-1], cycle[1:]))
    for source, target in pairs:
        if len(target) > len(source):
            return source, target
    return pairs[-1]


def break_dag_cycles(edges: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[list[str]]]:
    """Remove the closing edge from each detected cycle until the graph is a DAG."""
    remaining = list(edges)
    removed: list[dict[str, Any]] = []
    initial_cycles = detect_dag_cycles(remaining)

    while True:
        cycles = detect_dag_cycles(remaining)
        if not cycles:
            return remaining, removed, initial_cycles
        changed = False
        for cycle in cycles:
            if len(cycle) < 2:
                continue
            source, target = _cycle_edge_to_remove(cycle)
            for index, edge in enumerate(remaining):
                if edge.get("source") == source and edge.get("target") == target:
                    removed.append(remaining.pop(index))
                    changed = True
                    break
        if not changed:
            return remaining, removed, initial_cycles


def build_orphan_stubs(
    edges_by_type: dict[str, list[dict[str, Any]]], canonical_ids: set[str]
) -> list[dict[str, Any]]:
    """Create ingredient stubs for missing ingredient-edge targets."""
    missing_targets: set[str] = set()
    for edge_type in ("IS_A", "PART_OF", "DERIVED_FROM"):
        for edge in edges_by_type.get(edge_type, []):
            target = edge.get("target")
            if target and target not in canonical_ids:
                missing_targets.add(str(target))

    return [
        {
            "canonical_id": target,
            "display_name_zh": None,
            "display_name_en": target.replace("_", " "),
            "aliases": [],
            "scientific_name": None,
            "form_type": "species",
            "value_kind": "representative_average",
            "tree_status": "stub",
            "exclusion_reason": None,
            "peak_season_codes": [],
            "peak_months": [],
            "seasonality_records": [],
            "dietary_flags": [],
            "allergens": [],
            "_is_orphan_stub": True,
        }
        for target in sorted(missing_targets)
    ]


def build_relationships(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    canonical_ids = {
        _node(record).get("canonical_id")
        for record in records
        if _node(record).get("canonical_id")
    }
    edges_by_type: dict[str, list[dict[str, Any]]] = {edge_type: [] for edge_type in EDGE_TYPES}
    for record in records:
        if _node(record).get("tree_status") in {"excluded", "alias_redirect", "identity_conflict"}:
            continue
        record_edges = normalize_edges_from_record(record, canonical_ids)
        for edge_type, edges in record_edges.items():
            edges_by_type[edge_type].extend(edges)
    return {edge_type: dedupe_edges(edges) for edge_type, edges in edges_by_type.items()}


def run_relationship_build(*, input_path: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not input_path.exists():
        payload = {
            "nodes": [],
            "edges": {edge_type: [] for edge_type in EDGE_TYPES},
            "stubs": [],
            "validation": {"isa_cycles": [], "derived_from_cycles": [], "n_orphan_stubs": 0},
        }
        atomic_write_json(output_path, payload)
        return {"step": 6, "n_nodes": 0, "edge_counts": {}, "output": str(output_path)}

    data = json.loads(input_path.read_text(encoding="utf-8"))
    records = data.get("results", data if isinstance(data, list) else [])
    canonical_ids = {
        _node(record).get("canonical_id")
        for record in records
        if _node(record).get("canonical_id")
    }
    exportable_canonical_ids = {
        _node(record).get("canonical_id")
        for record in records
        if _node(record).get("canonical_id")
        and _node(record).get("tree_status") not in {"excluded", "alias_redirect", "identity_conflict"}
    }

    edges_by_type = build_relationships(records)
    edges_by_type["IS_A"], removed_isa_cycle_edges, initial_isa_cycles = break_dag_cycles(edges_by_type["IS_A"])
    edges_by_type["DERIVED_FROM"], removed_df_cycle_edges, initial_df_cycles = break_dag_cycles(edges_by_type["DERIVED_FROM"])
    stubs = build_orphan_stubs(edges_by_type, exportable_canonical_ids)
    validation = {
        "isa_cycles": detect_dag_cycles(edges_by_type["IS_A"]),
        "derived_from_cycles": detect_dag_cycles(edges_by_type["DERIVED_FROM"]),
        "initial_isa_cycles": initial_isa_cycles,
        "initial_derived_from_cycles": initial_df_cycles,
        "removed_isa_cycle_edges": removed_isa_cycle_edges,
        "removed_derived_from_cycle_edges": removed_df_cycle_edges,
        "n_orphan_stubs": len(stubs),
        "edge_type_counts": dict(Counter({k: len(v) for k, v in edges_by_type.items()})),
    }

    atomic_write_json(
        output_path,
        {
            "nodes": records,
            "edges": edges_by_type,
            "stubs": stubs,
            "validation": validation,
        },
    )
    return {
        "step": 6,
        "n_nodes": len(records),
        "edge_counts": {edge_type: len(edges) for edge_type, edges in edges_by_type.items()},
        "isa_cycles": len(validation["isa_cycles"]),
        "derived_from_cycles": len(validation["derived_from_cycles"]),
        "orphan_stubs": len(stubs),
        "output": str(output_path),
    }
