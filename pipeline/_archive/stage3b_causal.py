#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from utils.claude_client import build_runtime_config, call_claude, load_api_config


SYSTEM_PROMPT = """你是食品科学知识工程师，专门负责结构化烹饪科学原理。

给你一条已提取的烹饪科学原理（scientific_statement）和对应的原始书本片段。
完成以下四个分析任务，输出严格的JSON，不要输出任何其他内容。

━━━ TASK 1: 命题类型 ━━━
判断 proposition_type（四选一）：
- fact_atom          → 最小不可分事实，单一数值或关系（无因果序列）
- causal_chain       → 完整因果序列 A→B→C（有触发、过程、结果）
- compound_condition → 多个条件必须同时满足才产生结果（n≥2个前提）
- mathematical_law   → 定量数学关系（含公式、比例、对数、平方律等）

注意：一条原理只能属于一种类型。如果同时有因果链和数学关系，
优先标记为 mathematical_law；compound_condition 优先级最高。

━━━ TASK 2: 因果链步骤 ━━━
提取 causal_chain_steps（3-6步），每步前缀：
- "触发：" → 触发条件（输入/外部变量）
- "过程：" → 中间机制（分子/物理/化学过程）
- "结果：" → 最终结果（可观察的烹饪效果）

如果是 fact_atom，只写 ["事实：<陈述内容>"]
如果是 compound_condition，写 ["条件1：...", "条件2：...", "条件N：...", "结果：..."]
如果是 mathematical_law，写 ["变量：...", "关系：<公式>", "含义：...", "烹饪应用：..."]

━━━ TASK 3: 复合命题检测 ━━━
如果 scientific_statement 实际上包含 2 个或以上独立的原子事实：
- needs_split = true
- sub_principles 列出每个子命题（1-2句话）

判断标准：子命题之间用"；另外"/"同时"/"此外"分隔，
或者涉及完全不同的机制（例如美拉德和花青素变色是两种机制）。
如果只是同一机制的补充说明，不要拆分。

━━━ TASK 4: 边界区间 ━━━
如果存在多个临界值，每个临界值对应不同的效果：
- boundary_zones 列出每个区间

只有真正的"分段效果"才填，连续变化不要强行分段。

━━━ 输出格式（严格JSON） ━━━
{
  "proposition_type": "causal_chain",
  "causal_chain_steps": [
    "触发：加热温度超过50°C",
    "过程：肌球蛋白氢键开始断裂",
    "过程：蛋白质空间构象展开",
    "结果：持水力下降约30%",
    "结果：肉质纤维收紧变硬"
  ],
  "causal_chain_text": "温度↑ → 氢键断裂 → 构象展开 → 持水↓ → 变硬",
  "reasoning_type": "single_hop",
  "needs_split": false,
  "sub_principles": [],
  "boundary_zones": [
    {"range": "50-55°C", "effect": "肌球蛋白开始变性"},
    {"range": "65-80°C", "effect": "肌动蛋白变性，收缩显著"}
  ],
  "parallel_chains": [],
  "confidence": 0.92
}"""

USER_TEMPLATE = """原理内容：
{scientific_statement}

领域：{domain}

原始书本来源片段（供参考）：
{chunks_preview}"""

MAX_SPLIT_DEPTH = 3


class Stage3BCausalError(RuntimeError):
    """Raised for predictable Stage 3B failures."""


def load_json(path: Path, default: Any, *, tolerate_empty: bool = False) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        if tolerate_empty:
            return default
        raise Stage3BCausalError(f"JSON file is empty: {path}")
    return json.loads(text)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_report(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def load_matches_preview(path: Path, *, tolerate_empty: bool) -> dict[str, str]:
    matches = load_json(path, [], tolerate_empty=tolerate_empty)
    if not isinstance(matches, list):
        return {}
    preview_map: dict[str, str] = {}
    for item in matches:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id") or item.get("id") or "").strip()
        if not question_id:
            continue
        parts = []
        for chunk in (item.get("top_chunks") or [])[:3]:
            if not isinstance(chunk, dict):
                continue
            preview = str(chunk.get("preview") or chunk.get("full_text") or "").strip()
            if preview:
                parts.append(preview[:2400])
        preview_map[question_id] = "\n---\n".join(parts)
    return preview_map


def build_prompt(principle: dict[str, Any], preview: str) -> str:
    return USER_TEMPLATE.format(
        scientific_statement=str(principle.get("scientific_statement") or "").strip(),
        domain=str(principle.get("domain") or "").strip(),
        chunks_preview=(preview or "无可用片段")[:2400],
    )


def extract_first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def parse_response(content: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```json\s*", "", content.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    extracted = extract_first_json_object(cleaned) or cleaned
    parsed = json.loads(extracted)
    return parsed if isinstance(parsed, dict) else {}


def normalize_sub_principles(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for item in values:
        if isinstance(item, str) and item.strip():
            normalized.append(item.strip())
        elif isinstance(item, dict):
            candidate = str(item.get("statement") or item.get("scientific_statement") or item.get("text") or "").strip()
            if candidate:
                normalized.append(candidate)
    return normalized


def fallback_result(statement: str) -> dict[str, Any]:
    return {
        "proposition_type": "fact_atom",
        "causal_chain_steps": [f"事实：{statement}"],
        "causal_chain_text": statement,
        "reasoning_type": "single_hop",
        "needs_split": False,
        "sub_principles": [],
        "boundary_zones": [],
        "parallel_chains": [],
        "confidence": 0.5,
    }


def merge_result(base: dict[str, Any], result: dict[str, Any], *, split_from: str | None = None, parent_id: str | None = None) -> dict[str, Any]:
    merged = dict(base)
    merged.update(
        {
            "proposition_type": result.get("proposition_type"),
            "causal_chain_steps": result.get("causal_chain_steps") if isinstance(result.get("causal_chain_steps"), list) else [],
            "causal_chain_text": result.get("causal_chain_text"),
            "reasoning_type": result.get("reasoning_type"),
            "needs_split": bool(result.get("needs_split")),
            "boundary_zones": result.get("boundary_zones") if isinstance(result.get("boundary_zones"), list) else [],
            "parallel_chains": result.get("parallel_chains") if isinstance(result.get("parallel_chains"), list) else [],
            "confidence": result.get("confidence"),
        }
    )
    if split_from:
        merged["split_from"] = split_from
    if parent_id and parent_id != split_from:
        merged["parent_principle_id"] = parent_id
    return merged


def enrich_recursive(
    principle: dict[str, Any],
    *,
    preview_map: dict[str, str],
    runtime_config: dict[str, Any],
    source_principle_id: str,
    depth: int = 0,
) -> list[dict[str, Any]]:
    prompt = build_prompt(principle, preview_map.get(str(principle.get("question_id") or ""), ""))
    try:
        result = parse_response(call_claude(prompt, runtime_config, system=SYSTEM_PROMPT)["content"])
    except Exception:
        result = fallback_result(str(principle.get("scientific_statement") or ""))
    if not str(result.get("proposition_type") or "").strip():
        result = fallback_result(str(principle.get("scientific_statement") or ""))

    needs_split = bool(result.get("needs_split"))
    sub_principles = normalize_sub_principles(result.get("sub_principles"))
    if not needs_split or not sub_principles or depth >= MAX_SPLIT_DEPTH:
        return [
            merge_result(
                principle,
                result,
                split_from=source_principle_id if depth > 0 else None,
                parent_id=str(principle.get("parent_principle_id") or "") or None,
            )
        ]

    records: list[dict[str, Any]] = []
    for index, statement in enumerate(sub_principles):
        child_id = f"{source_principle_id}-{chr(65 + index)}"
        child = dict(principle)
        child["principle_id"] = child_id
        child["scientific_statement"] = statement
        child["parent_principle_id"] = principle.get("principle_id")
        records.extend(
            enrich_recursive(
                child,
                preview_map=preview_map,
                runtime_config=runtime_config,
                source_principle_id=source_principle_id,
                depth=depth + 1,
            )
        )
    for record in records:
        record.setdefault("split_from", source_principle_id)
        record.setdefault("parent_principle_id", principle.get("principle_id"))
    return records


def build_report(records: list[dict[str, Any]]) -> list[str]:
    lines = ["Stage 3B Report", "================", ""]
    if not records:
        lines.append("No records found.")
        return lines

    type_counts = Counter(str(record.get("proposition_type") or "unknown") for record in records)
    split_count = sum(1 for record in records if record.get("split_from"))
    low_confidence = [record for record in records if float(record.get("confidence") or 0.0) < 0.7]
    missing_boundaries = [
        record
        for record in records
        if str(record.get("proposition_type") or "") in {"causal_chain", "compound_condition", "mathematical_law"}
        and not record.get("boundary_zones")
    ]

    lines.append(f"Total records: {len(records)}")
    lines.append(f"Split-derived records: {split_count}")
    lines.append("")
    lines.append("Proposition types:")
    for proposition_type, count in sorted(type_counts.items()):
        lines.append(f"- {proposition_type}: {count}")
    lines.append("")
    lines.append(f"Low confidence (<0.7): {len(low_confidence)}")
    for record in low_confidence[:10]:
        lines.append(f"- {record.get('principle_id')}: {record.get('confidence')}")
    lines.append("")
    lines.append(f"Missing boundary zones on structured propositions: {len(missing_boundaries)}")
    for record in missing_boundaries[:10]:
        lines.append(f"- {record.get('principle_id')}: {record.get('proposition_type')}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 3B causal enrichment for L0 principles")
    parser.add_argument("--input", required=True, help="Input Stage 3 JSONL path")
    parser.add_argument("--matches", required=True, help="Stage 2 match JSON path")
    parser.add_argument("--output", required=True, help="Output JSONL path")
    parser.add_argument("--report", required=True, help="Text report path")
    parser.add_argument("--config", required=True, help="API config YAML path")
    parser.add_argument("--dry-run", action="store_true", help="Print prompt previews without calling Claude")
    parser.add_argument("--report-only", action="store_true", help="Only regenerate the report from existing output")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    report_path = Path(args.report)
    tolerate_empty = args.dry_run or args.report_only

    if args.report_only:
        save_report(report_path, build_report(load_jsonl(output_path)))
        return

    config = load_api_config(Path(args.config))
    runtime_config = build_runtime_config(config, model_key="causal", max_tokens=1800)
    preview_map = load_matches_preview(Path(args.matches), tolerate_empty=tolerate_empty)
    input_records = load_jsonl(input_path)

    if args.dry_run:
        for record in input_records[:3]:
            prompt = build_prompt(record, preview_map.get(str(record.get("question_id") or ""), ""))
            print(record.get("principle_id"))
            print(prompt[:800])
            print("=" * 60)
        if not input_records:
            print("No input records available for preview.")
        return

    done_ids = set()
    existing_records = load_jsonl(output_path)
    for record in existing_records:
        done_ids.add(str(record.get("split_from") or record.get("principle_id") or ""))

    new_records: list[dict[str, Any]] = []
    for index, principle in enumerate(input_records, start=1):
        principle_id = str(principle.get("principle_id") or "")
        if not principle_id or principle_id in done_ids:
            continue
        print(f"[{index}/{len(input_records)}] {principle_id}")
        enriched_records = enrich_recursive(
            principle,
            preview_map=preview_map,
            runtime_config=runtime_config,
            source_principle_id=principle_id,
        )
        for record in enriched_records:
            append_jsonl(output_path, record)
            new_records.append(record)
        done_ids.add(principle_id)

    save_report(report_path, build_report(existing_records + new_records))


if __name__ == "__main__":
    main()
