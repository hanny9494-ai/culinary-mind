"""Step 7 Neo4j CSV export skeleton with hard-fail gate names."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


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

CUISINE_SEED_ROWS = [
    {"cuisine_id": "cantonese", "name_zh": "粤菜", "name_en": "Cantonese", "region": "southern_china"},
    {"cuisine_id": "sichuan", "name_zh": "川菜", "name_en": "Sichuan", "region": "western_china"},
    {"cuisine_id": "jiangnan", "name_zh": "苏浙菜", "name_en": "Jiangnan", "region": "eastern_china"},
    {"cuisine_id": "hainan", "name_zh": "海南菜", "name_en": "Hainanese", "region": "southern_china"},
    {"cuisine_id": "french", "name_zh": "法餐", "name_en": "French", "region": "france"},
    {"cuisine_id": "japanese", "name_zh": "日料", "name_en": "Japanese", "region": "japan"},
]


def validate_export_inputs(payload: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for record in payload.get("nodes", []):
        node = record.get("target_node") or record
        if not node.get("canonical_id"):
            failures.append("canonical_id_missing")
        if not node.get("display_name_zh") and not node.get("display_name_en"):
            failures.append("display_name_both_empty")
        if node.get("tree_status") == "identity_conflict":
            failures.append("identity_conflict_active")
    return sorted(set(failures))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_export(*, input_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not input_path.exists():
        payload = {"nodes": [], "edges": {}}
    else:
        payload = json.loads(input_path.read_text(encoding="utf-8"))

    failures = validate_export_inputs(payload)
    write_csv(output_dir / "cuisines_seed.csv", CUISINE_SEED_ROWS)
    qc_report = {"hard_fail_checks": HARD_FAIL_CHECKS, "failures": failures, "skeleton": True}
    (output_dir.parent / "qc_report.yaml").write_text(json.dumps(qc_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"step": 7, "output_dir": str(output_dir), "hard_failures": failures, "skeleton": True}
