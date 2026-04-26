#!/usr/bin/env python3
"""L0 open extraction pipeline.

Phase A: 27b filter -- classify chunks for extractable scientific propositions.
Phase B: Opus extract -- extract atomic scientific propositions via Claude.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Ollama session (proxy bypass) -- mirrors pipeline/utils/ollama_client.py
# ---------------------------------------------------------------------------

_OLLAMA_BASE = "http://localhost:11434"
_OLLAMA_SESSION: requests.Session | None = None


def _ollama_session() -> requests.Session:
    global _OLLAMA_SESSION
    if _OLLAMA_SESSION is None:
        _OLLAMA_SESSION = requests.Session()
        _OLLAMA_SESSION.trust_env = False  # bypass http_proxy / https_proxy
    return _OLLAMA_SESSION


def ollama_generate(model: str, prompt: str, timeout: int = 240) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"think": False},
    }
    session = _ollama_session()
    resp = session.post(f"{_OLLAMA_BASE}/api/generate", json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    text = str(body.get("response") or "").strip()
    if not text:
        text = str(body.get("thinking") or "").strip()
    if not text:
        raise RuntimeError(f"Empty Ollama response: {json.dumps(body, ensure_ascii=False)[:500]}")
    return text


# ---------------------------------------------------------------------------
# Claude API helpers
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> tuple[str, str, str]:
    """Return (endpoint, api_key, model) with env-var expansion."""
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    claude = cfg.get("claude", {})
    endpoint = claude.get("endpoint", "")
    api_key = claude.get("api_key", "")
    # Expand env vars
    for var in ("L0_API_ENDPOINT", "L0_API_KEY"):
        val = os.environ.get(var, "")
        endpoint = endpoint.replace(f"${{{var}}}", val)
    for var in ("L0_API_KEY",):
        val = os.environ.get(var, "")
        api_key = api_key.replace(f"${{{var}}}", val)
    model = claude.get("models", {}).get("distill", "claude-opus-4.6")
    return endpoint, api_key, model


_CLAUDE_SESSION: requests.Session | None = None


def _get_claude_session() -> requests.Session:
    global _CLAUDE_SESSION
    if _CLAUDE_SESSION is None:
        _CLAUDE_SESSION = requests.Session()
        _CLAUDE_SESSION.trust_env = False  # 绕过 http_proxy
    return _CLAUDE_SESSION


_token_usage = {"input_tokens": 0, "output_tokens": 0, "total_calls": 0}


def call_claude(
    endpoint: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4000,
    timeout: int = 90,
    max_retries: int = 3,
) -> Any:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    session = _get_claude_session()
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.post(endpoint, headers=headers, json=body, timeout=timeout)
            resp.raise_for_status()
            resp_json = resp.json()
            usage = resp_json.get("usage", {})
            _token_usage["input_tokens"] += usage.get("input_tokens", 0)
            _token_usage["output_tokens"] += usage.get("output_tokens", 0)
            _token_usage["total_calls"] += 1
            raw = resp_json["content"][0]["text"].strip()
            raw = re.sub(r"```json\s*", "", raw)
            raw = re.sub(r"```\s*", "", raw)
            raw = raw.strip()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
            if not raw.startswith("["):
                raw = "[" + raw + "]"
                raw = re.sub(r"\}\s*\{", "},{", raw)
                raw = re.sub(r"\]\s*\[", ",", raw)
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    pass
            results = []
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, list):
                        results.extend(obj)
                    else:
                        results.append(obj)
                except json.JSONDecodeError:
                    continue
            if results:
                return results
            raise json.JSONDecodeError("Cannot parse Claude response", raw[:200], 0)
        except Exception as exc:
            last_err = exc
            if attempt < max_retries:
                time.sleep(min(15, 2 * attempt))
    raise RuntimeError(f"Claude request failed after {max_retries} attempts: {last_err}")


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def load_chunks(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get("chunks", [])
    return []


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                records.append(obj)
    return records


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    # Server-side schema-version fallback — the L0 extraction prompt asks
    # the model for `_v: "1.1"` but don't trust the model to always emit
    # it. Stamp version programmatically before writing so every record
    # hitting l0_principles_open.jsonl / l0_raw.jsonl / l0_filter.jsonl
    # carries a schema version.
    record.setdefault("_v", "1.1")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_domains(path: Path) -> tuple[list[str], str]:
    """Return (domain_id_list, formatted_domains_string_for_prompt)."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    domains = raw.get("domains", [])
    ids: list[str] = []
    lines: list[str] = []
    for d in domains:
        did = d.get("id", "")
        label = d.get("label_zh", "")
        ids.append(did)
        lines.append(f"- {did} ({label})")
    return ids, "\n".join(lines)


def chunk_text(chunk: dict[str, Any]) -> str:
    for key in ("full_text", "text", "content", "summary"):
        val = str(chunk.get(key) or "").strip()
        if val:
            return val
    return ""


def chunk_id(chunk: dict[str, Any], index: int) -> str:
    cid = str(chunk.get("chunk_id") or chunk.get("id") or "").strip()
    if cid:
        return cid
    return f"chunk_{index}"


def normalize_chunk_type(chunk: dict[str, Any]) -> str | None:
    value = chunk.get("chunk_type")
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def resolve_chunks_path(chunks_arg: str | None, book_id: str | None) -> Path:
    if chunks_arg:
        return Path(chunks_arg)
    if not book_id:
        raise FileNotFoundError("Provide --chunks or --book-id.")

    candidates = [
        REPO_ROOT / "output" / book_id / "prep" / "chunks_smart.json",
        REPO_ROOT / "output" / book_id / "stage1" / "chunks_smart.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Could not find chunks_smart.json for book_id={book_id}")


def resolve_output_dir(output_dir_arg: str | None, book_id: str | None) -> Path:
    if output_dir_arg:
        return Path(output_dir_arg)
    if book_id:
        new_path = REPO_ROOT / "output" / book_id / "l0"
        old_path = REPO_ROOT / "output" / book_id / "stage4"
        return new_path if new_path.exists() else old_path if old_path.exists() else new_path
    return REPO_ROOT / "output" / "l0"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

FILTER_SYSTEM = """\
你是食品科学知识工程师。判断以下文本片段是否包含可提取的科学命题。

科学命题的标准：
- 包含因果关系（A导致B）
- 包含定量参数（温度、时间、浓度、比例）
- 包含物理/化学/生物机制的解释
- 包含材料性质的科学描述

不是科学命题的：
- 纯配方/食谱步骤（没有解释为什么）
- 历史叙事/人物故事
- 目录/索引/参考文献
- 纯主观评价（"味道很好"）

输出JSON：{"has_science": true/false, "reason": "一句话理由"}\
"""

EXTRACT_SYSTEM_TEMPLATE = """\
你是食品科学知识工程师。从以下文本中提取所有独立的原子科学命题。

每条命题必须：
1. 是独立的、最小不可分的科学事实或因果关系
2. 包含具体的科学机制或定量参数
3. citation_quote必须是原文的精确引用（逐字复制，不改写）

命题类型（四选一）：
- fact_atom: 单一数值事实
- causal_chain: 因果序列 A→B→C
- compound_condition: 多条件同时满足
- mathematical_law: 定量数学关系

Domain（17域，选最匹配的一个）：
{domains_list}

输出JSON数组（可以是0-N条）。每条记录必须包含字段 "_v": "1.1"（schema 版本）和 "evidence_type"：
[
  {{
    "_v": "1.1",
    "scientific_statement": "中文陈述",
    "proposition_type": "causal_chain",
    "causal_chain_steps": ["触发：...", "过程：...", "结果：..."],
    "causal_chain_text": "A→B→C",
    "boundary_conditions": ["条件1", "条件2"],
    "boundary_zones": [],
    "domain": "protein_science",
    "confidence": 0.85,
    "citation_quote": "exact quote from text",
    "domain_note": "",
    "evidence_type": "expert_opinion"
  }}
]

evidence_type 选其一（按证据强度）：
- empirical：来自实验研究/原始数据集（primary evidence）
- theoretical：从已知物理/化学定律推导（如 Arrhenius、Fick）
- expert_opinion：教科书/专著的权威总结陈述（从教科书蒸馏通常填这个）
- derived：由另一条记录或求解器二次推导得到

如果这条原理不属于以上17域中的任何一个，domain填"unclassified"，并在domain_note字段写明你认为它应该属于什么领域。

如果文本中没有可提取的科学命题，输出空数组：[]\
"""


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------

_watchdog_limit: int = 0
_watchdog_last: float = 0.0


def watchdog_reset() -> None:
    global _watchdog_last
    _watchdog_last = time.time()


def watchdog_check(label: str) -> None:
    if _watchdog_limit <= 0:
        return
    elapsed = time.time() - _watchdog_last
    if elapsed > _watchdog_limit * 60:
        print(f"[WATCHDOG] {label}: {elapsed:.0f}s since last progress, aborting", flush=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Phase A: 27b filter
# ---------------------------------------------------------------------------

def run_phase_a(
    chunks: list[dict[str, Any]],
    filter_model: str,
    output_path: Path,
    save_every: int,
    resume: bool,
    dry_run: bool,
) -> dict[str, int]:
    print(f"=== Phase A: 27b filter ({filter_model}) ===", flush=True)
    print(f"  Total chunks: {len(chunks)}", flush=True)

    # Load existing filter results for resume
    done_ids: set[str] = set()
    if resume:
        for rec in load_jsonl(output_path):
            cid = rec.get("chunk_id", "")
            if cid:
                done_ids.add(cid)
        if done_ids:
            print(f"  Resuming: {len(done_ids)} chunks already filtered", flush=True)

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    processed = 0
    skipped = 0
    errors = 0
    shortcut_passed = 0
    shortcut_skipped = 0
    prefilter_passed = 0
    prefilter_skipped = 0
    prefilter_pending = 0

    for idx, chunk in enumerate(chunks):
        cid = chunk_id(chunk, idx)
        if cid in done_ids:
            skipped += 1
            continue

        text = chunk_text(chunk)
        if not text.strip():
            record = {"chunk_id": cid, "has_science": False, "reason": "empty_chunk"}
            if not dry_run:
                append_jsonl(output_path, record)
            prefilter_skipped += 1
            processed += 1
            continue

        ctype = normalize_chunk_type(chunk)
        if ctype in {"science", "mixed"}:
            print(f"[chunk_type shortcut] {cid} → pass (type={ctype})", flush=True)
            record = {"chunk_id": cid, "has_science": True, "reason": f"chunk_type_shortcut:{ctype}"}
            if not dry_run:
                append_jsonl(output_path, record)
            shortcut_passed += 1
            processed += 1
            done_ids.add(cid)
            continue
        if ctype in {"recipe", "narrative"}:
            print(f"[chunk_type shortcut] {cid} → skip (type={ctype})", flush=True)
            record = {"chunk_id": cid, "has_science": False, "reason": f"chunk_type_shortcut:{ctype}"}
            if not dry_run:
                append_jsonl(output_path, record)
            shortcut_skipped += 1
            processed += 1
            done_ids.add(cid)
            continue

        if dry_run:
            prefilter_pending += 1
            processed += 1
            continue

        watchdog_reset()
        prompt = f"{FILTER_SYSTEM}\n\n---\n文本片段：\n{text[:3000]}"

        try:
            raw = ollama_generate(filter_model, prompt)
            result = json.loads(raw)
            has_science = bool(result.get("has_science", False))
            reason = str(result.get("reason", ""))
            if has_science:
                prefilter_passed += 1
            else:
                prefilter_skipped += 1
        except Exception as exc:
            print(f"  [ERROR] chunk {cid}: {exc}", flush=True)
            has_science = False
            reason = f"error: {str(exc)[:200]}"
            prefilter_skipped += 1
            errors += 1

        record = {"chunk_id": cid, "has_science": has_science, "reason": reason}
        append_jsonl(output_path, record)
        done_ids.add(cid)
        processed += 1

        if processed % save_every == 0:
            print(f"  Progress: {processed} filtered, {skipped} skipped, {errors} errors", flush=True)
            sys.stdout.flush()

        watchdog_check(f"Phase A chunk {cid}")

    print(f"  Phase A done: {processed} filtered, {skipped} skipped, {errors} errors", flush=True)
    if dry_run:
        print(
            f"[Phase A] chunk_type shortcut: {shortcut_passed} passed, {shortcut_skipped} skipped | "
            f"27b prefilter: {prefilter_passed} passed, {prefilter_skipped} skipped",
            flush=True,
        )
        if prefilter_pending:
            print(f"[Phase A dry-run] 27b prefilter deferred for {prefilter_pending} chunks", flush=True)
    else:
        print(
            f"[Phase A] chunk_type shortcut: {shortcut_passed} passed, {shortcut_skipped} skipped | "
            f"27b prefilter: {prefilter_passed} passed, {prefilter_skipped} skipped",
            flush=True,
        )
        print(f"  Output: {output_path}", flush=True)
    return {
        "processed": processed,
        "resume_skipped": skipped,
        "errors": errors,
        "shortcut_passed": shortcut_passed,
        "shortcut_skipped": shortcut_skipped,
        "prefilter_passed": prefilter_passed,
        "prefilter_skipped": prefilter_skipped,
        "prefilter_pending": prefilter_pending,
    }


# ---------------------------------------------------------------------------
# Phase B: Opus extract
# ---------------------------------------------------------------------------

def run_phase_b(
    chunks: list[dict[str, Any]],
    filter_path: Path,
    endpoint: str,
    api_key: str,
    model: str,
    domains_list: str,
    output_path: Path,
    save_every: int,
    resume: bool,
) -> None:
    print(f"=== Phase B: Opus extract ({model}) ===", flush=True)

    # Reset token counter for this book
    _token_usage["input_tokens"] = 0
    _token_usage["output_tokens"] = 0
    _token_usage["total_calls"] = 0

    # Build chunk lookup by id
    chunk_map: dict[str, dict[str, Any]] = {}
    for idx, chunk in enumerate(chunks):
        cid = chunk_id(chunk, idx)
        chunk_map[cid] = chunk

    # Load filter results -- keep only has_science=true
    filter_records = load_jsonl(filter_path)
    science_ids: list[str] = []
    for rec in filter_records:
        if rec.get("has_science"):
            cid = rec.get("chunk_id", "")
            if cid and cid in chunk_map:
                science_ids.append(cid)

    print(f"  Filtered chunks with science: {len(science_ids)}", flush=True)

    # Load existing raw results for resume
    # 跳过所有已处理的chunk（包括错误的，避免反复重试浪费时间）
    done_chunk_ids: set[str] = set()
    if resume:
        for rec in load_jsonl(output_path):
            scid = rec.get("source_chunk_id", "")
            if scid:
                done_chunk_ids.add(scid)
        if done_chunk_ids:
            print(f"  Resuming: {len(done_chunk_ids)} chunks already extracted", flush=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    system_prompt = EXTRACT_SYSTEM_TEMPLATE.format(domains_list=domains_list)
    processed = 0
    total_principles = 0
    errors = 0

    for list_idx, cid in enumerate(science_ids, start=1):
        if cid in done_chunk_ids:
            continue

        chunk = chunk_map[cid]
        text = chunk_text(chunk)
        if not text.strip():
            continue

        watchdog_reset()
        user_prompt = f"文本片段 (chunk_id: {cid})：\n{text[:4000]}"

        try:
            result = call_claude(endpoint, api_key, model, system_prompt, user_prompt)
            if not isinstance(result, list):
                result = []
        except Exception as exc:
            print(f"  [ERROR] chunk {cid}: {exc}", flush=True)
            errors += 1
            # Write an empty marker so resume skips this chunk
            marker = {"source_chunk_id": cid, "_error": str(exc)[:300], "scientific_statement": ""}
            append_jsonl(output_path, marker)
            done_chunk_ids.add(cid)
            continue

        for principle in result:
            if not isinstance(principle, dict):
                continue
            principle["source_chunk_id"] = cid
            append_jsonl(output_path, principle)
            total_principles += 1

        # If no principles extracted, still mark as done
        if not result:
            marker = {"source_chunk_id": cid, "_empty": True, "scientific_statement": ""}
            append_jsonl(output_path, marker)

        done_chunk_ids.add(cid)
        processed += 1

        if processed % save_every == 0:
            print(
                f"  Progress: {processed}/{len(science_ids)} chunks, "
                f"{total_principles} principles, {errors} errors",
                flush=True,
            )
            sys.stdout.flush()

        watchdog_check(f"Phase B chunk {cid}")

    print(
        f"  Phase B done: {processed} chunks processed, "
        f"{total_principles} principles extracted, {errors} errors",
        flush=True,
    )
    print(f"  Output: {output_path}", flush=True)

    # Save token usage
    usage_path = output_path.parent / "token_usage.json"
    usage_data = {
        "total_input_tokens": _token_usage["input_tokens"],
        "total_output_tokens": _token_usage["output_tokens"],
        "total_tokens": _token_usage["input_tokens"] + _token_usage["output_tokens"],
        "total_calls": _token_usage["total_calls"],
    }
    with open(usage_path, "w", encoding="utf-8") as f:
        json.dump(usage_data, f, ensure_ascii=False, indent=2)
    print(f"  Token usage: {usage_data}", flush=True)
    print(f"  Saved to: {usage_path}", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="L0 open extraction: Phase A (27b filter) + Phase B (Opus extract)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--chunks", help="Path to chunks_smart.json")
    parser.add_argument("--book-id", help="Book id used to auto-discover chunks_smart.json and default output paths")
    parser.add_argument("--config", default=str(REPO_ROOT / "config" / "api.yaml"), help="Path to config/api.yaml")
    parser.add_argument("--domains", default=str(REPO_ROOT / "config" / "domains_v2.json"), help="Path to config/domains_v2.json")
    parser.add_argument("--output-dir", help="Output directory for l0 artifacts")
    parser.add_argument("--filter-model", default="qwen3.5:27b", help="Ollama model for Phase A filter (default: qwen3.5:27b)")
    parser.add_argument("--save-every", type=int, default=50, help="Save progress every N records (default: 50)")
    parser.add_argument("--watchdog", type=int, default=15, help="Abort if no progress for N minutes (default: 15, 0=disable)")
    parser.add_argument("--resume", action="store_true", help="Resume from previous run (skip already-processed chunks)")
    parser.add_argument("--filter-only", action="store_true", help="Only run Phase A (27b filter), skip Phase B")
    parser.add_argument("--phase", choices=("all", "a-only", "b-only"), default="all", help="Pipeline phase to run (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Load inputs and print Phase A routing without calling external APIs")
    args = parser.parse_args()

    global _watchdog_limit
    _watchdog_limit = args.watchdog

    phase = "a-only" if args.filter_only and args.phase == "all" else args.phase
    if args.filter_only and args.phase != "all":
        parser.error("--filter-only cannot be combined with --phase")

    try:
        chunks_path = resolve_chunks_path(args.chunks, args.book_id)
    except FileNotFoundError as exc:
        parser.error(str(exc))
    output_dir = resolve_output_dir(args.output_dir, args.book_id)
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    filter_path = output_dir / "l0_filter.jsonl" if (output_dir / "l0_filter.jsonl").exists() else output_dir / "stage4_filter.jsonl"
    raw_path = output_dir / "l0_raw.jsonl" if (output_dir / "l0_raw.jsonl").exists() else output_dir / "stage4_raw.jsonl"
    # For new runs, use new names
    if not filter_path.exists():
        filter_path = output_dir / "l0_filter.jsonl"
    if not raw_path.exists():
        raw_path = output_dir / "l0_raw.jsonl"

    # Load inputs
    print(f"Loading chunks from {chunks_path} ...", flush=True)
    chunks = load_chunks(chunks_path)
    print(f"  Loaded {len(chunks)} chunks", flush=True)

    if phase == "b-only" and not filter_path.exists():
        print(f"[FATAL] Missing Phase A output: {filter_path}", flush=True)
        sys.exit(1)

    # Phase A
    if phase != "b-only":
        run_phase_a(
            chunks=chunks,
            filter_model=args.filter_model,
            output_path=filter_path,
            save_every=args.save_every,
            resume=args.resume,
            dry_run=args.dry_run,
        )

    if phase == "a-only":
        if args.dry_run:
            print("[dry-run] Phase A validation complete; skipped Phase B.", flush=True)
        else:
            print("Phase A complete; skipping Phase B.", flush=True)
        return

    if args.dry_run:
        print(f"[dry-run] Would run Phase B using {filter_path} -> {raw_path}", flush=True)
        return

    domain_ids, domains_list = load_domains(Path(args.domains))
    print(f"  Loaded {len(domain_ids)} domains", flush=True)

    # Phase B
    endpoint, api_key, model = load_config(args.config)
    if not endpoint:
        print("[FATAL] Claude endpoint not configured. Check config/api.yaml and L0_API_ENDPOINT env var.", flush=True)
        sys.exit(1)

    run_phase_b(
        chunks=chunks,
        filter_path=filter_path,
        endpoint=endpoint,
        api_key=api_key,
        model=model,
        domains_list=domains_list,
        output_path=raw_path,
        save_every=args.save_every,
        resume=args.resume,
    )

    print("L0 open extraction complete.", flush=True)


if __name__ == "__main__":
    main()
