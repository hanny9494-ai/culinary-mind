from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return default
    return json.loads(text)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
    return records


def _extract_chunks(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        chunks = payload.get("chunks") or []
        if isinstance(chunks, list):
            return [item for item in chunks if isinstance(item, dict)]
    return []


def _extract_matches(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        matches = payload.get("matches")
        if isinstance(matches, list):
            return [item for item in matches if isinstance(item, dict)]
        return [item for item in payload.values() if isinstance(item, dict)]
    return []


def check_stage1(output_dir: Path) -> dict[str, Any]:
    output_path = output_dir / "chunks_smart.json"
    chunks = _extract_chunks(_load_json(output_path, []))
    book_ids = sorted(
        {
            str(chunk.get("source_book") or chunk.get("book_id") or "").strip()
            for chunk in chunks
            if str(chunk.get("source_book") or chunk.get("book_id") or "").strip()
        }
    )
    return {
        "output_path": str(output_path),
        "exists": output_path.exists(),
        "chunks": len(chunks),
        "book_ids": book_ids,
        "valid": len(chunks) > 0,
    }


def check_stage2(output_path: Path) -> dict[str, Any]:
    matches = _extract_matches(_load_json(output_path, []))
    matched = 0
    for item in matches:
        candidates = item.get("top_chunks") or item.get("matches") or item.get("chunks") or []
        if isinstance(candidates, list) and candidates:
            matched += 1

    total_questions = len(matches)
    match_rate = round(matched / total_questions, 3) if total_questions else 0.0

    report_path = output_path.with_name("match_report.json")
    report_payload = _load_json(report_path, {})
    if isinstance(report_payload, dict):
        total_questions = int(
            report_payload.get("total_questions")
            or report_payload.get("questions_total")
            or total_questions
            or 0
        )
        matched = int(
            report_payload.get("matched")
            or report_payload.get("matched_questions")
            or report_payload.get("questions_matched")
            or matched
            or 0
        )
        if total_questions:
            match_rate = round(
                float(report_payload.get("match_rate") or (matched / total_questions)),
                3,
            )

    warnings = []
    if total_questions == 0:
        warnings.append("no_match_rows")
    if total_questions and match_rate <= 0.8:
        warnings.append("match_rate_below_threshold")

    return {
        "output_path": str(output_path),
        "report_path": str(report_path),
        "exists": output_path.exists(),
        "matched": matched,
        "total_questions": total_questions,
        "match_rate": match_rate,
        "warnings": warnings,
        "valid": total_questions > 0,
    }


def check_stage3(output_dir: Path) -> dict[str, Any]:
    output_path = output_dir / "l0_principles.jsonl"
    quality_path = output_dir / "quality_issues.json"
    cost_path = output_dir / "cost_report.json"

    records = _load_jsonl(output_path)
    quality_issues = _load_json(quality_path, [])
    cost_report = _load_json(cost_path, {})

    return {
        "output_path": str(output_path),
        "exists": output_path.exists(),
        "principles": len(records),
        "quality_issues": len(quality_issues) if isinstance(quality_issues, list) else 0,
        "cost_usd": float(cost_report.get("estimated_cost_usd") or 0.0)
        if isinstance(cost_report, dict)
        else 0.0,
        "model": str(cost_report.get("model") or "").strip() if isinstance(cost_report, dict) else "",
        "valid": len(records) > 0,
    }


def check_stage3b(output_path: Path) -> dict[str, Any]:
    records = _load_jsonl(output_path)
    type_counts = Counter(str(record.get("proposition_type") or "unknown") for record in records)
    split_count = sum(1 for record in records if record.get("split_from"))

    return {
        "output_path": str(output_path),
        "exists": output_path.exists(),
        "records": len(records),
        "splits": split_count,
        "type_distribution": dict(sorted(type_counts.items())),
        "valid": len(records) > 0,
    }
