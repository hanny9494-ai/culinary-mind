"""Step 6 relationship derivation skeleton."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.l2a.etl.utils.checkpointing import atomic_write_json


EDGE_TYPES = ("IS_A", "PART_OF", "DERIVED_FROM", "SUBSTITUTES_FOR", "HAS_CULINARY_ROLE")


def build_relationships(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {edge_type: [] for edge_type in EDGE_TYPES}


def run_relationship_build(*, input_path: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not input_path.exists():
        atomic_write_json(output_path, {"nodes": [], "edges": build_relationships([]), "note": "input missing; Day 1 skeleton"})
        return {"step": 6, "node_count": 0, "edge_count": 0, "output": str(output_path), "skeleton": True}

    data = json.loads(input_path.read_text(encoding="utf-8"))
    records = data.get("results", data if isinstance(data, list) else [])
    edges = build_relationships(records)
    atomic_write_json(
        output_path,
        {
            "nodes": records,
            "edges": edges,
            "note": "Day 1 skeleton: relationship extraction pending Day 4",
        },
    )
    return {"step": 6, "node_count": len(records), "edge_count": 0, "output": str(output_path), "skeleton": True}
