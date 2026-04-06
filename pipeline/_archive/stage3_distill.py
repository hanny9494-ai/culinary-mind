#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from utils.claude_client import build_runtime_config, call_claude, load_api_config


PROMPT_TEMPLATE = """分析后抽取原理。

问题: {question_text}

参考文本:
{reference_text}

格式:
<thinking>分析三段文本，找出最相关的科学机制，确认数值</thinking>
<principle>
{{"principle_name": "中文名", "mechanism": "physics/chemistry/biology/sensory",
 "scientific_statement": "含数值的可证伪陈述",
 "boundary_conditions": ["条件:数值"],
 "citation_quote": "原文<30词"}}
</principle>
"""

MODEL_COSTS = {
    "claude-opus-4.6": {"input_per_million": 15.0, "output_per_million": 75.0},
}


class Stage3Error(RuntimeError):
    """Raised for predictable Stage 3 errors."""


def load_json(path: Path, default: Any, *, tolerate_empty: bool = False) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        if tolerate_empty:
            return default
        raise Stage3Error(f"JSON file is empty: {path}")
    return json.loads(text)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


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


def load_domains(path: Path) -> tuple[list[str], dict[str, str]]:
    payload = load_json(path, {}, tolerate_empty=False)
    domains: list[str] = []
    labels: dict[str, str] = {}
    for item in payload.get("domains") or []:
        domain_id = str(item.get("id") or "").strip()
        if not domain_id:
            continue
        domains.append(domain_id)
        labels[domain_id] = str(item.get("label_zh") or "").strip()
    if not domains:
        raise Stage3Error(f"No domains found in {path}")
    return domains, labels


def normalize_domain_code(domain: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(domain or "").strip())
    return cleaned.upper() or "UNKNOWN"


def make_chunk_aliases(index: int, chunk: dict[str, Any]) -> set[str]:
    aliases = {f"chunk_{index}"}
    explicit = str(chunk.get("chunk_id") or chunk.get("id") or "").strip()
    if explicit:
        aliases.add(explicit)
        if ":" in explicit:
            aliases.add(explicit.split(":", 1)[1])
    chunk_idx = chunk.get("chunk_idx")
    if isinstance(chunk_idx, int):
        aliases.add(f"chunk_{chunk_idx}")
        source_book = str(chunk.get("source_book") or chunk.get("book_id") or "").strip()
        if source_book:
            aliases.add(f"{source_book}:chunk_{chunk_idx}")
    return {alias for alias in aliases if alias}


def load_chunk_map(path: Path, *, tolerate_empty: bool) -> dict[str, dict[str, Any]]:
    raw = load_json(path, {}, tolerate_empty=tolerate_empty)
    if isinstance(raw, dict):
        chunks = raw.get("chunks") or []
    elif isinstance(raw, list):
        chunks = raw
    else:
        chunks = []
    chunk_map: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(chunks):
        if not isinstance(item, dict):
            continue
        for alias in make_chunk_aliases(index, item):
            chunk_map.setdefault(alias, item)
    return chunk_map


def load_matches(path: Path, *, tolerate_empty: bool) -> list[dict[str, Any]]:
    raw = load_json(path, [], tolerate_empty=tolerate_empty)
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [item for item in raw.values() if isinstance(item, dict)]
    return []


def get_question_id(match: dict[str, Any], index: int) -> str:
    return str(match.get("question_id") or match.get("id") or f"Q-{index + 1:04d}")


def get_question_text(match: dict[str, Any]) -> str:
    return str(match.get("question_text") or match.get("question") or match.get("text") or "").strip()


def get_top_chunk_refs(match: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = match.get("top_chunks") or match.get("matches") or match.get("chunks") or []
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates[:3] if isinstance(item, dict)]


def resolve_chunks(match: dict[str, Any], chunk_map: dict[str, dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    ids: list[str] = []
    chunks: list[dict[str, Any]] = []
    for item in get_top_chunk_refs(match):
        raw_id = str(item.get("chunk_id") or item.get("id") or "").strip()
        chunk = chunk_map.get(raw_id)
        if chunk is None and raw_id.startswith("chunk_"):
            chunk = chunk_map.get(raw_id.split(":", 1)[-1])
        if chunk is None and ":" in raw_id:
            chunk = chunk_map.get(raw_id.split(":", 1)[1])
        if chunk is None:
            continue
        ids.append(raw_id or f"chunk_{len(ids)}")
        chunks.append(chunk)
    return ids, chunks


def chunk_text(chunk: dict[str, Any]) -> str:
    for key in ("full_text", "text", "content", "summary"):
        value = str(chunk.get(key) or "").strip()
        if value:
            return value
    return ""


def build_prompt(question_text: str, chunks: list[dict[str, Any]]) -> str:
    parts = []
    for index, chunk in enumerate(chunks[:3], start=1):
        parts.append(f"[文本{index}] {chunk_text(chunk)[:2000]}")
    return PROMPT_TEMPLATE.format(question_text=question_text, reference_text="\n\n".join(parts))


def extract_tag(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


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


def loose_parse_principle(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    extracted = extract_first_json_object(cleaned)
    if extracted:
        try:
            parsed = json.loads(extracted)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass

    principle: dict[str, Any] = {}
    for key in ("principle_name", "mechanism", "scientific_statement", "citation_quote"):
        match = re.search(rf'"{key}"\s*:\s*"([^"]*)"', cleaned, re.DOTALL)
        if match:
            principle[key] = match.group(1).strip()
    boundary_match = re.search(r'"boundary_conditions"\s*:\s*\[(.*?)\]', cleaned, re.DOTALL)
    if boundary_match:
        principle["boundary_conditions"] = re.findall(r'"([^"]+)"', boundary_match.group(1))
    return principle


def parse_response(content: str) -> tuple[str, dict[str, Any]]:
    thinking = extract_tag(content, "thinking")
    principle_block = extract_tag(content, "principle") or content
    return thinking, loose_parse_principle(principle_block)


def infer_domain(
    match: dict[str, Any],
    domains: list[str],
    domain_labels: dict[str, str],
    chunks: list[dict[str, Any]],
) -> str:
    valid_domains = set(domains)
    direct = str(match.get("domain") or match.get("topic") or "").strip()
    if direct in valid_domains:
        return direct

    topic_counts: Counter[str] = Counter()
    for chunk in chunks:
        topics = chunk.get("topics")
        if isinstance(topics, list):
            for topic in topics:
                topic_name = str(topic or "").strip()
                if topic_name in valid_domains:
                    topic_counts[topic_name] += 1
    if topic_counts:
        return topic_counts.most_common(1)[0][0]

    search_text = " ".join(
        [
            direct,
            str(match.get("question_id") or ""),
            str(match.get("question_text") or match.get("question") or ""),
        ]
    ).lower()
    for domain in domains:
        if domain.lower() in search_text:
            return domain
        label = domain_labels.get(domain, "").lower()
        if label and label in search_text:
            return domain

    return direct if direct else "unknown"


def load_progress(path: Path) -> dict[str, Any]:
    return load_json(
        path,
        {
            "completed": [],
            "total_in_tokens": 0,
            "total_out_tokens": 0,
        },
        tolerate_empty=True,
    )


def save_progress(path: Path, completed: set[str], total_in: int, total_out: int) -> None:
    save_json(
        path,
        {
            "completed": sorted(completed),
            "total_in_tokens": total_in,
            "total_out_tokens": total_out,
        },
    )


def initialize_seq_counters(records: list[dict[str, Any]]) -> Counter[str]:
    counters: Counter[str] = Counter()
    for record in records:
        principle_id = str(record.get("principle_id") or "").strip()
        match = re.match(r"^L0-(.+)-(\d+)$", principle_id)
        if not match:
            continue
        domain_code = match.group(1)
        counters[domain_code] = max(counters[domain_code], int(match.group(2)))
    return counters


def next_principle_id(domain: str, counters: Counter[str]) -> str:
    domain_code = normalize_domain_code(domain)
    counters[domain_code] += 1
    return f"L0-{domain_code}-{counters[domain_code]:03d}"


def count_words(text: str) -> int:
    return len(re.findall(r"\S+", str(text or "").strip()))


def collect_quality_issues(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for record in records:
        principle_id = str(record.get("principle_id") or "")
        citation_quote = str(record.get("citation_quote") or "")
        scientific_statement = str(record.get("scientific_statement") or "")
        missing_fields = [
            field
            for field in ("principle_name", "mechanism", "scientific_statement")
            if not str(record.get(field) or "").strip()
        ]
        if count_words(citation_quote) > 30:
            issues.append(
                {
                    "principle_id": principle_id,
                    "issue": "citation_quote_too_long",
                    "details": citation_quote,
                }
            )
        if scientific_statement and not re.search(r"\d", scientific_statement):
            issues.append(
                {
                    "principle_id": principle_id,
                    "issue": "scientific_statement_missing_number",
                    "details": scientific_statement,
                }
            )
        if missing_fields:
            issues.append(
                {
                    "principle_id": principle_id,
                    "issue": "missing_principle_fields",
                    "details": missing_fields,
                }
            )
    return issues


def build_cost_report(
    *,
    model_name: str,
    total_in_tokens: int,
    total_out_tokens: int,
    completed_count: int,
    failed_count: int,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "model": model_name,
        "input_tokens": total_in_tokens,
        "output_tokens": total_out_tokens,
        "total_tokens": total_in_tokens + total_out_tokens,
        "completed_questions": completed_count,
        "failed_questions": failed_count,
    }
    rates = MODEL_COSTS.get(model_name)
    if rates:
        report["estimated_cost_usd"] = round(
            (total_in_tokens / 1_000_000.0) * rates["input_per_million"]
            + (total_out_tokens / 1_000_000.0) * rates["output_per_million"],
            4,
        )
    return report


def remove_outputs(paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            path.unlink()


def run_dry_preview(matches: list[dict[str, Any]], chunk_map: dict[str, dict[str, Any]], preview: int) -> None:
    shown = 0
    for index, match in enumerate(matches):
        question_text = get_question_text(match)
        chunk_ids, chunks = resolve_chunks(match, chunk_map)
        prompt = build_prompt(question_text, chunks) if chunks else build_prompt(question_text, [])
        print(f"[{shown + 1}] {get_question_id(match, index)}")
        print(f"question: {question_text[:120]}")
        print(f"chunks: {chunk_ids}")
        print(prompt[:700])
        print("=" * 60)
        shown += 1
        if shown >= preview:
            break
    if shown == 0:
        print("No matches available for preview.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 3 distillation for L0 principles")
    parser.add_argument("--matches", required=True, help="Stage 2 match JSON path")
    parser.add_argument("--chunks", required=True, help="Stage 1 chunks_smart.json path")
    parser.add_argument("--output-dir", required=True, help="Output directory for Stage 3 artifacts")
    parser.add_argument("--config", required=True, help="API config YAML path")
    parser.add_argument("--domains", required=True, help="Domain config JSON path")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N pending questions")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts without calling Claude")
    parser.add_argument("--reset", action="store_true", help="Clear Stage 3 outputs before running")
    parser.add_argument("--preview", type=int, default=3, help="Dry-run prompt preview count")
    parser.add_argument("--append", action="store_true", help="Append to existing JSONL instead of treating it as a single-run corpus")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_jsonl = output_dir / "l0_principles.jsonl"
    progress_path = output_dir / "progress.json"
    failed_path = output_dir / "failed.json"
    quality_path = output_dir / "quality_issues.json"
    cost_path = output_dir / "cost_report.json"

    if args.reset:
        remove_outputs([output_jsonl, progress_path, failed_path, quality_path, cost_path])

    output_dir.mkdir(parents=True, exist_ok=True)

    domains, domain_labels = load_domains(Path(args.domains))
    config = load_api_config(Path(args.config))
    runtime_config = build_runtime_config(config, model_key="distill", max_tokens=1000)
    model_name = str((runtime_config.get("claude") or {}).get("model") or "")
    save_every = int((runtime_config.get("claude") or {}).get("save_every") or 20)

    tolerate_empty = args.dry_run
    matches = load_matches(Path(args.matches), tolerate_empty=tolerate_empty)
    chunk_map = load_chunk_map(Path(args.chunks), tolerate_empty=tolerate_empty)

    if args.dry_run:
        run_dry_preview(matches, chunk_map, max(1, args.preview))
        save_json(quality_path, [])
        save_json(
            cost_path,
            build_cost_report(
                model_name=model_name,
                total_in_tokens=0,
                total_out_tokens=0,
                completed_count=0,
                failed_count=0,
            ),
        )
        return

    existing_records = load_jsonl(output_jsonl)
    progress = load_progress(progress_path)
    failed_entries = load_json(failed_path, [], tolerate_empty=True)
    if not isinstance(failed_entries, list):
        failed_entries = []

    completed = set(str(item) for item in progress.get("completed") or [])
    completed.update(str(record.get("question_id") or "") for record in existing_records if record.get("question_id"))
    failed_ids = {str(item.get("question_id") or "") for item in failed_entries if isinstance(item, dict)}

    total_in_tokens = int(progress.get("total_in_tokens") or 0)
    total_out_tokens = int(progress.get("total_out_tokens") or 0)
    seq_counters = initialize_seq_counters(existing_records)

    pending = []
    for index, match in enumerate(matches):
        question_id = get_question_id(match, index)
        if question_id in completed:
            continue
        if question_id in failed_ids and not args.append:
            continue
        pending.append((index, match))

    if args.limit > 0:
        pending = pending[: args.limit]

    new_records: list[dict[str, Any]] = []
    batch_since_save = 0

    for list_index, (match_index, match) in enumerate(pending, start=1):
        question_id = get_question_id(match, match_index)
        question_text = get_question_text(match)
        chunk_ids, chunks = resolve_chunks(match, chunk_map)
        if not chunks:
            failed_entries.append({"question_id": question_id, "reason": "no_chunks_found"})
            save_json(failed_path, failed_entries)
            continue

        domain = infer_domain(match, domains, domain_labels, chunks)
        principle_id = next_principle_id(domain, seq_counters)
        prompt = build_prompt(question_text, chunks)

        print(f"[{list_index}/{len(pending)}] {question_id} -> {principle_id}")
        try:
            result = call_claude(prompt, runtime_config)
            thinking, principle = parse_response(result["content"])
        except Exception as exc:
            failed_entries.append({"question_id": question_id, "reason": str(exc)[:500]})
            save_json(failed_path, failed_entries)
            seq_counters[normalize_domain_code(domain)] -= 1
            print(f"  failed: {exc}")
            continue

        record = {
            "principle_id": principle_id,
            "question_id": question_id,
            "domain": domain,
            "principle_name": str(principle.get("principle_name") or "").strip(),
            "mechanism": str(principle.get("mechanism") or "").strip(),
            "scientific_statement": str(principle.get("scientific_statement") or "").strip(),
            "boundary_conditions": principle.get("boundary_conditions")
            if isinstance(principle.get("boundary_conditions"), list)
            else [],
            "citation_quote": str(principle.get("citation_quote") or "").strip(),
            "_thinking": thinking,
            "_chunks_used": chunk_ids[:3],
            "_tokens": {
                "in": int(result["in_tokens"]),
                "out": int(result["out_tokens"]),
            },
        }
        append_jsonl(output_jsonl, record)
        new_records.append(record)
        completed.add(question_id)
        total_in_tokens += int(result["in_tokens"])
        total_out_tokens += int(result["out_tokens"])
        batch_since_save += 1

        if batch_since_save >= save_every:
            save_progress(progress_path, completed, total_in_tokens, total_out_tokens)
            batch_since_save = 0

    all_records = existing_records + new_records
    save_progress(progress_path, completed, total_in_tokens, total_out_tokens)
    save_json(failed_path, failed_entries)
    save_json(quality_path, collect_quality_issues(all_records))
    save_json(
        cost_path,
        build_cost_report(
            model_name=model_name,
            total_in_tokens=total_in_tokens,
            total_out_tokens=total_out_tokens,
            completed_count=len(completed),
            failed_count=len(failed_entries),
        ),
    )


if __name__ == "__main__":
    main()
