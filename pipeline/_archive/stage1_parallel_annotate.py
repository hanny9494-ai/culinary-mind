#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests


def load_stage1_module(repo_root: Path):
    module_path = repo_root / "scripts" / "stage1_pipeline.py"
    spec = importlib.util.spec_from_file_location("stage1_pipeline_dynamic", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(repo_root / "scripts"))
    sys.path.insert(0, str(repo_root))
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ollama_generate(base_url: str, model: str, prompt: str, timeout: int) -> str:
    response = requests.post(
        f"{base_url.rstrip('/')}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"think": False},
        },
        timeout=timeout,
        proxies={"http": None, "https": None},
    )
    response.raise_for_status()
    body = response.json()
    text = str(body.get("response") or "").strip()
    if text:
        return text
    thinking = str(body.get("thinking") or "").strip()
    if thinking:
        return thinking
    raise RuntimeError(f"Missing response text: {json.dumps(body, ensure_ascii=False)[:500]}")


def fallback_topic(chunk: dict[str, Any]) -> str:
    text = str(chunk.get("full_text") or "").lower()
    chapter = str(chunk.get("chapter_title") or "").lower()
    rules = [
        ("emulsion", ("emulsion", "mayo", "mayonnaise", "vinaigrette", "butter sauce", "mornay", "hollandaise")),
        ("mass_transfer", ("brine", "marinade", "diffusion", "osmos", "cure", "salt crust")),
        ("protein_science", ("protein", "egg", "meat", "fish", "chicken", "beef", "pork", "lamb", "collagen")),
        ("texture_rheology", ("texture", "gel", "firm", "tender", "tough", "jelly", "viscos", "mouthfeel")),
        ("salinity_minerality", ("salt", "saline", "sodium")),
        ("thermal_dynamics", ("temperature", "heat", "cook", "cooking", "water bath", "°c", "°f", "sous vide")),
    ]
    for topic, keywords in rules:
        if any(keyword in text or keyword in chapter for keyword in keywords):
            return topic
    return "thermal_dynamics"


def strict_retry(module: Any, base_url: str, model: str, valid_topics: list[str], chunk: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""你要为一个食品科学 chunk 生成检索用摘要和高精度 topics。
只输出 JSON，格式必须是：
{{
  "summary": "50字以内中文摘要",
  "topics": ["allowed_topic_1"],
  "chunk_type": "science|recipe|mixed|narrative"
}}

Allowed topics:
{", ".join(valid_topics)}

严格要求：
- 必须且只能返回 1 个 topics。
- topics 必须严格从 Allowed topics 里选。
- 如果不确定，也必须选最核心的 1 个 topic。
- summary 必须是中文且不超过 50 字。
- chunk_type 必须是 science|recipe|mixed|narrative 之一。

Chapter title: {chunk.get("chapter_title", "")}
Section range: {chunk.get("chapter_start", "")} -> {chunk.get("chapter_end", "")}

Chunk:
{chunk.get("full_text", "")}
"""
    raw = ollama_generate(base_url, model, prompt, timeout=240)
    parsed = module.extract_json_object(raw)
    summary = str(parsed.get("summary") or "").strip()[:50]
    topic = str((parsed.get("topics") or [""])[0]).strip()
    chunk_type = module.normalize_chunk_type(parsed.get("chunk_type")) or "science"
    if not summary:
        summary = str(chunk.get("full_text") or "").strip().replace("\n", " ")[:50]
    if topic not in valid_topics:
        topic = fallback_topic(chunk)
    return {"summary": summary, "topics": [topic], "chunk_type": chunk_type}


def annotate_one(module: Any, base_url: str, model: str, valid_topics: list[str], chunk: dict[str, Any], retries: int) -> dict[str, Any]:
    last_error: str | None = None
    for _ in range(retries):
        try:
            merged = dict(chunk)
            merged.update(module.annotate_chunk(chunk, model, valid_topics, False))
            return {"status": "ok", "chunk_idx": int(chunk["chunk_idx"]), "payload": merged}
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            time.sleep(1)
    try:
        merged = dict(chunk)
        merged.update(strict_retry(module, base_url, model, valid_topics, chunk))
        return {"status": "ok", "chunk_idx": int(chunk["chunk_idx"]), "payload": merged, "fallback": True}
    except Exception as exc:  # noqa: BLE001
        last_error = f"{last_error}; fallback={exc}"
    return {
        "status": "error",
        "chunk_idx": int(chunk["chunk_idx"]),
        "payload": {
            "chunk_idx": int(chunk["chunk_idx"]),
            "chapter_num": chunk.get("chapter_num"),
            "chapter_title": chunk.get("chapter_title"),
            "error": last_error or "unknown error",
            "updated_at": module.now_iso(),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parallel helper for Stage1 step5 annotations.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    os.environ["no_proxy"] = "localhost,127.0.0.1"
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"
    for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
        os.environ[key] = ""

    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    module = load_stage1_module(repo_root)
    output_dir = Path(args.output_dir).expanduser()
    stage1_dir = output_dir / "stage1"

    api_config = module.load_yaml(Path(args.config).expanduser())
    module.configure_ollama((api_config.get("ollama") or {}))
    valid_topics = module.load_topics(repo_root / "config" / "domains_v2.json")
    base_url = str(((api_config.get("ollama") or {}).get("url") or "http://localhost:11434")).rstrip("/")
    model = str((((api_config.get("ollama") or {}).get("models") or {}).get("annotate") or "qwen3.5:9b"))

    chunks = module.load_json_list(output_dir / "chunks_raw.json")
    annotated = module.load_json_list(stage1_dir / "chunks_smart.json")
    failures = module.load_json_list(stage1_dir / "annotation_failures.json")
    annotated_by_id = {int(item["chunk_idx"]): item for item in annotated if "chunk_idx" in item}
    failure_ids = {int(item["chunk_idx"]) for item in failures if "chunk_idx" in item}

    pending = [chunk for chunk in chunks if int(chunk["chunk_idx"]) not in annotated_by_id or int(chunk["chunk_idx"]) in failure_ids]
    print(f"chunks={len(chunks)} annotated={len(annotated_by_id)} failures={len(failure_ids)} pending={len(pending)}", flush=True)
    if not pending:
        module.save_json(stage1_dir / "annotation_failures.json", [])
        return 0

    new_failures: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {
            executor.submit(annotate_one, module, base_url, model, valid_topics, chunk, args.retries): int(chunk["chunk_idx"])
            for chunk in pending
        }
        for future in as_completed(future_map):
            result = future.result()
            chunk_idx = int(result["chunk_idx"])
            if result["status"] == "ok":
                annotated_by_id[chunk_idx] = result["payload"]
                new_failures.pop(chunk_idx, None)
                tag = " fallback" if result.get("fallback") else ""
                print(f"chunk {chunk_idx} ok{tag}", flush=True)
            else:
                new_failures[chunk_idx] = result["payload"]
                print(f"chunk {chunk_idx} error", flush=True)
            module.save_json(stage1_dir / "chunks_smart.json", [annotated_by_id[idx] for idx in sorted(annotated_by_id)])
            module.save_json(stage1_dir / "annotation_failures.json", [new_failures[idx] for idx in sorted(new_failures)])

    if len(annotated_by_id) == len(chunks) and not new_failures:
        module.save_json(
            output_dir / "stage1_progress.json",
            {
                "book_id": "sous_vide_keller",
                "status": "completed",
                "updated_at": module.now_iso(),
                "inferred_from_outputs": False,
            },
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
