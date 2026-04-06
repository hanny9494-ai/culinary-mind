#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from utils.claude_client import build_runtime_config, call_claude, load_api_config


SCAN_PROMPT = """你是食品科学知识工程师。

以下是一段烹饪科学书籍的文字片段（来自Modernist Cuisine）。
请判断这段文字是否包含值得提炼为"L0科学原理"的核心知识。

L0科学原理的标准：
1. 有明确的科学机制（不只是操作步骤或历史背景）
2. 有可量化的参数（温度/时间/浓度/比例等）或清晰的因果关系
3. 对烹饪决策有直接指导意义
4. 在我们现有306道题中没有被直接覆盖

排除：
- 纯历史介绍、名厨轶事
- 纯操作步骤（没有解释为什么）
- 已经非常通用的常识（水100°C沸腾等）

请判断并输出严格JSON：
{{
  "has_principle": true/false,
  "reason": "一句话说明为什么有/没有",
  "question_text": "如果有，该用什么问题来提取这个原理？（中文）",
  "domain": "对应哪个domain（从列表选择）",
  "key_parameters": ["关键数值或参数"],
  "priority": "high/medium/low",
  "novelty_note": "这个知识点在哪里是新的/独特的？"
}}

domain列表：{domains}

待分析文字：
{chunk_text}"""


class ScanLowHitError(RuntimeError):
    """Raised for predictable scan failures."""


def load_json(path: Path, default: Any, *, tolerate_empty: bool = False) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        if tolerate_empty:
            return default
        raise ScanLowHitError(f"JSON file is empty: {path}")
    return json.loads(text)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_domains(path: Path) -> list[str]:
    payload = load_json(path, {}, tolerate_empty=False)
    domains = []
    for item in payload.get("domains") or []:
        domain_id = str(item.get("id") or "").strip()
        if domain_id:
            domains.append(domain_id)
    if not domains:
        raise ScanLowHitError(f"No domains found in {path}")
    return domains


def load_mc_chunks(pattern: str) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for raw_path in sorted(glob.glob(pattern)):
        path = Path(raw_path)
        payload = load_json(path, [], tolerate_empty=False)
        items = payload.get("chunks") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            continue
        source_book = path.parts[-3] if len(path.parts) >= 3 else path.stem
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            chunk = dict(item)
            chunk_id = str(chunk.get("chunk_id") or "").strip()
            chunk_idx = chunk.get("chunk_idx")
            if not chunk_id:
                if isinstance(chunk_idx, int):
                    chunk_id = f"{source_book}:chunk_{chunk_idx}"
                else:
                    chunk_id = f"{source_book}:chunk_{index}"
            chunk["_chunk_id"] = chunk_id
            chunk["_chunk_aliases"] = {
                chunk_id,
                chunk_id.split(":", 1)[1] if ":" in chunk_id else chunk_id,
            }
            chunk["_source_book"] = source_book
            chunk["_source_file"] = str(path)
            chunks.append(chunk)
    return chunks


def build_hit_map(path: Path, *, tolerate_empty: bool) -> dict[str, float]:
    payload = load_json(path, [], tolerate_empty=tolerate_empty)
    if not isinstance(payload, list):
        return {}
    hit_map: dict[str, float] = defaultdict(float)
    for item in payload:
        if not isinstance(item, dict):
            continue
        for chunk in (item.get("top_chunks") or []):
            if not isinstance(chunk, dict):
                continue
            chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or "").strip()
            if not chunk_id:
                continue
            score = float(chunk.get("cosine") or chunk.get("score") or 0.0)
            hit_map[chunk_id] = max(hit_map[chunk_id], score)
            if ":" in chunk_id:
                hit_map[chunk_id.split(":", 1)[1]] = max(hit_map[chunk_id.split(":", 1)[1]], score)
    return dict(hit_map)


def get_chunk_text(chunk: dict[str, Any]) -> str:
    for key in ("full_text", "summary", "text", "content"):
        value = str(chunk.get(key) or "").strip()
        if value:
            return value
    return ""


def is_noise_chunk(chunk: dict[str, Any]) -> bool:
    text = get_chunk_text(chunk).lower()
    if len(text) < 100:
        return True
    signals = [
        "references",
        "bibliography",
        "index",
        "copyright",
        "contents",
        "acknowledgment",
        "preface",
        "foreword",
        "figure ",
        "table ",
        "recipe for",
        "serves ",
        "makes about",
    ]
    return any(signal in text for signal in signals)


def parse_response(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    payload = cleaned[start : end + 1] if start >= 0 and end >= start else cleaned
    parsed = json.loads(payload)
    return parsed if isinstance(parsed, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan low-hit MC chunks for candidate questions")
    parser.add_argument("--mc-chunks", required=True, help="Glob for MC chunks_smart.json files")
    parser.add_argument("--matches", required=True, help="Stage 2 match JSON path")
    parser.add_argument("--output", required=True, help="Candidate question JSON path")
    parser.add_argument("--config", required=True, help="API config YAML path")
    parser.add_argument("--domains", required=True, help="Domain config JSON path")
    parser.add_argument("--threshold", type=float, default=0.55, help="Low-hit cosine threshold")
    parser.add_argument("--max-chunks", type=int, default=200, help="Maximum low-hit chunks to inspect")
    parser.add_argument("--dry-run", action="store_true", help="Inspect low-hit stats without calling Claude")
    args = parser.parse_args()

    domains = load_domains(Path(args.domains))
    chunks = load_mc_chunks(args.mc_chunks)
    hit_map = build_hit_map(Path(args.matches), tolerate_empty=args.dry_run)

    low_hit = []
    for chunk in chunks:
        if is_noise_chunk(chunk):
            continue
        score = max(hit_map.get(alias, 0.0) for alias in chunk["_chunk_aliases"])
        if score < args.threshold:
            chunk["_hit_score"] = score
            low_hit.append(chunk)
    low_hit.sort(key=lambda item: item["_hit_score"])
    to_scan = low_hit[: max(0, args.max_chunks)]

    if args.dry_run:
        print(f"loaded_chunks={len(chunks)}")
        print(f"low_hit_chunks={len(low_hit)}")
        for chunk in to_scan[:10]:
            print(f"{chunk['_chunk_id']} score={chunk['_hit_score']:.3f}")
            print(get_chunk_text(chunk)[:200])
            print("=" * 60)
        return

    config = load_api_config(Path(args.config))
    runtime_config = build_runtime_config(config, model_key="scan", max_tokens=600)
    candidates: list[dict[str, Any]] = []
    seen_questions = set()

    for index, chunk in enumerate(to_scan, start=1):
        chunk_text = get_chunk_text(chunk)
        if not chunk_text:
            continue
        prompt = SCAN_PROMPT.format(domains=", ".join(domains), chunk_text=chunk_text[:3000])
        print(f"[{index}/{len(to_scan)}] {chunk['_chunk_id']}")
        try:
            result = parse_response(call_claude(prompt, runtime_config)["content"])
        except Exception as exc:
            print(f"  failed: {exc}")
            continue
        question_text = str(result.get("question_text") or "").strip()
        if not result.get("has_principle") or not question_text or question_text in seen_questions:
            continue
        domain = str(result.get("domain") or "").strip()
        candidate = {
            "source_chunk_id": chunk["_chunk_id"],
            "source_book": chunk["_source_book"],
            "source_file": chunk["_source_file"],
            "hit_score": round(float(chunk["_hit_score"]), 4),
            "question_text": question_text,
            "domain": domain if domain in domains else "",
            "reason": str(result.get("reason") or "").strip(),
            "key_parameters": result.get("key_parameters") if isinstance(result.get("key_parameters"), list) else [],
            "priority": str(result.get("priority") or "").strip(),
            "novelty_note": str(result.get("novelty_note") or "").strip(),
        }
        candidates.append(candidate)
        seen_questions.add(question_text)

    save_json(Path(args.output), candidates)


if __name__ == "__main__":
    main()
