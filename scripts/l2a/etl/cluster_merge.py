"""Step 5 cluster merge/split skeleton.

Day 4 will implement same scientific_name clustering, alias redirects, variant
splits, and pomfret-style identity conflict handling.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.l2a.etl.utils.checkpointing import atomic_write_json


def group_by_scientific_name(nodes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    clusters: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        sci = (node.get("target_node") or node).get("scientific_name")
        if sci:
            clusters.setdefault(str(sci), []).append(node)
    return clusters


def run_cluster_merge(*, input_path: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not input_path.exists():
        atomic_write_json(output_path, {"results": [], "note": "input missing; Day 1 skeleton"})
        return {"step": 5, "count": 0, "output": str(output_path), "skeleton": True}

    data = json.loads(input_path.read_text(encoding="utf-8"))
    records = data.get("results", data if isinstance(data, list) else [])
    clusters = group_by_scientific_name(records)
    atomic_write_json(
        output_path,
        {
            "results": records,
            "cluster_count": len(clusters),
            "note": "Day 1 skeleton: no merge/split mutations applied",
        },
    )
    return {"step": 5, "count": len(records), "clusters": len(clusters), "output": str(output_path), "skeleton": True}
