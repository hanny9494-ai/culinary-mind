"""Load all distilled atoms from the Gemini partial and Codex per-atom files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
GEMINI_PARTIAL = Path("/tmp/round3_v3_main_distill.json")
CODEX_DIR = ROOT / "output" / "l2a" / "etl_codex" / "distilled"

_MISPLACED_TOP_LEVEL_KEYS = {
    "edge_candidates",
    "confidence_overall",
    "issue_codes",
    "evidence_split_candidates",
    "needs_human_review",
}


def _atom_id_from_gemini_record(rec: dict[str, Any], index: int) -> str | None:
    atom_id = rec.get("atom_id")
    if atom_id:
        return str(atom_id)

    file_value = rec.get("file")
    if file_value:
        return Path(str(file_value)).stem
    return f"gemini_missing_atom_id_{index}"


def _normalize_repaired_codex_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Lift fields accidentally emitted inside target_node back to record root."""
    node = rec.get("target_node")
    if not isinstance(node, dict):
        return rec

    for key in list(_MISPLACED_TOP_LEVEL_KEYS):
        if key in node and key not in rec:
            rec[key] = node.pop(key)
    return rec


def _read_codex_record(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return _normalize_repaired_codex_record(json.loads(text))
    except json.JSONDecodeError:
        # Two known round-3 Codex files are valid objects except for a missing
        # final brace and top-level fields nested under target_node.
        return _normalize_repaired_codex_record(json.loads(text + "}"))


def _parse_error_record(path: Path, error: Exception) -> dict[str, Any]:
    atom_id = path.stem
    return {
        "atom_id": atom_id,
        "_source": "codex",
        "_parse_error": str(error),
        "target_node": {
            "canonical_id": atom_id,
            "display_name_zh": None,
            "display_name_en": atom_id.replace("_", " "),
            "aliases": [],
            "scientific_name": None,
            "form_type": "ambiguous",
            "value_kind": "representative_average",
            "tree_status": "excluded",
            "exclusion_reason": "parse_error",
            "peak_season_codes": [],
            "peak_months": [],
            "seasonality_records": [],
            "dietary_flags": [],
            "allergens": [],
        },
        "edge_candidates": {
            "is_a": [],
            "part_of": [],
            "derived_from": [],
            "has_culinary_role": [],
        },
        "confidence_overall": 0.0,
        "issue_codes": ["parse_error"],
        "evidence_split_candidates": [],
        "needs_human_review": True,
    }


def load_all_distilled() -> list[dict[str, Any]]:
    """Return unified records keyed by atom_id; Codex wins duplicate IDs."""
    records: dict[str, dict[str, Any]] = {}

    if GEMINI_PARTIAL.exists():
        gemini_data = json.loads(GEMINI_PARTIAL.read_text(encoding="utf-8"))
        for index, rec in enumerate(gemini_data.get("results", [])):
            atom_id = _atom_id_from_gemini_record(rec, index)
            if not atom_id:
                continue
            rec["atom_id"] = atom_id
            rec["_source"] = "gemini"
            records[atom_id] = rec

    if CODEX_DIR.exists():
        for path in sorted(CODEX_DIR.glob("*.json")):
            try:
                rec = _read_codex_record(path)
            except Exception as exc:  # pragma: no cover - defensive fallback
                rec = _parse_error_record(path, exc)
            atom_id = path.stem
            rec["atom_id"] = atom_id
            rec["_source"] = "codex"
            records[atom_id] = rec

    return list(records.values())
