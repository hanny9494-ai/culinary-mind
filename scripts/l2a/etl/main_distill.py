"""Step 3 Gemini main distillation for P1-13~16.

The Lingya HTTP call intentionally uses trust_env=False plus a separate
threading timeout. httpx timeouts are not relied on for the D70 hard stop.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import yaml


for _proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_proxy_var, None)


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.l2a.etl.utils.checkpointing import CheckpointState, atomic_write_json, load_progress
from scripts.l2a.etl.prefilter import check as prefilter_check
from scripts.l2a.etl.post_normalizer import normalize as post_normalize


PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "gemini_main_distill.txt"
ATOM_DIR = ROOT / "output" / "l2a" / "atoms_r2"
DEFAULT_MODEL = "gemini-3.1-pro-preview-thinking"
DEFAULT_HARD_TIMEOUT_SECONDS = 300
DEFAULT_RETRY_BACKOFF_SECONDS = (5, 10, 20)
DEFAULT_SEMAPHORE_LIMIT = 8
CHECKPOINT_EVERY = 100
DEFAULT_PRICE_PER_1K_TOKENS_USD = 0.01


class CostCapExceeded(RuntimeError):
    pass


class ThreadTimeoutError(TimeoutError):
    pass


def lingya_chat_url(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/v1/chat/completions"):
        return endpoint
    return endpoint + "/v1/chat/completions"


def load_test_atom_paths(test_atoms_path: Path, limit_atoms: int | None = None) -> list[Path]:
    data = yaml.safe_load(test_atoms_path.read_text(encoding="utf-8"))
    records = data.get("test_atoms", [])
    paths = [ROOT / record["file"] for record in records]
    return paths[:limit_atoms] if limit_atoms is not None else paths


def load_atom_paths(*, limit_atoms: int | None, test_mode: bool, test_atoms_path: Path) -> list[Path]:
    if test_mode:
        return load_test_atom_paths(test_atoms_path, limit_atoms)
    paths = sorted(ATOM_DIR.glob("*.json"))
    return paths[:limit_atoms] if limit_atoms is not None else paths


def load_prompt_template(path: Path = PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")


def render_prompt(template: str, *, atom_id: str, atom: dict[str, Any], siblings: list[dict[str, Any]]) -> list[dict[str, str]]:
    atom_full_json = json.dumps(atom, ensure_ascii=False, indent=2, sort_keys=True)
    sibling_atoms_array = json.dumps(siblings, ensure_ascii=False, indent=2, sort_keys=True)
    rendered = (
        template.replace("{atom_id}", atom_id)
        .replace("{atom_full_json}", atom_full_json)
        .replace("{sibling_atoms_array}", sibling_atoms_array)
    )
    if rendered.startswith("SYSTEM:") and "\nUSER:\n" in rendered:
        system_part, user_part = rendered.split("\nUSER:\n", 1)
        return [
            {"role": "system", "content": system_part.removeprefix("SYSTEM:\n").strip()},
            {"role": "user", "content": user_part.strip()},
        ]
    return [{"role": "user", "content": rendered}]


def extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
    if fence_match:
        stripped = fence_match.group(1)
    else:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            stripped = stripped[start : end + 1]
    return json.loads(stripped)


def estimate_cost_usd(usage: dict[str, Any] | None, *, fallback_atom_cost_usd: float = 0.05) -> float:
    if not usage:
        return fallback_atom_cost_usd
    total_tokens = usage.get("total_tokens")
    if total_tokens is None:
        total_tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
    try:
        tokens = float(total_tokens)
    except (TypeError, ValueError):
        return fallback_atom_cost_usd
    price_per_1k = float(os.environ.get("L2A_GEMINI_USD_PER_1K_TOKENS", DEFAULT_PRICE_PER_1K_TOKENS_USD))
    return tokens / 1000.0 * price_per_1k


def _post_lingya_once(*, endpoint: str, api_key: str, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    payload = {"model": model, "messages": messages, "temperature": 0}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(trust_env=False, timeout=None) as client:
        response = client.post(lingya_chat_url(endpoint), headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


def post_with_thread_timeout(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    hard_timeout_seconds: int = DEFAULT_HARD_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            result_queue.put(("ok", _post_lingya_once(endpoint=endpoint, api_key=api_key, model=model, messages=messages)))
        except BaseException as exc:  # noqa: BLE001 - propagate exact worker failure.
            result_queue.put(("error", exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(hard_timeout_seconds)
    if thread.is_alive():
        raise ThreadTimeoutError(f"Lingya request exceeded {hard_timeout_seconds}s hard timeout")

    status, payload = result_queue.get_nowait()
    if status == "error":
        raise payload
    return payload


async def call_lingya_with_retries(
    *,
    messages: list[dict[str, str]],
    semaphore: asyncio.Semaphore,
    model: str,
    endpoint: str,
    api_key: str,
    retry_backoff_seconds: tuple[int, ...] = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> dict[str, Any]:
    async with semaphore:
        attempts = len(retry_backoff_seconds) + 1
        for attempt in range(attempts):
            try:
                return await asyncio.to_thread(
                    post_with_thread_timeout,
                    endpoint=endpoint,
                    api_key=api_key,
                    model=model,
                    messages=messages,
                )
            except Exception:
                if attempt >= attempts - 1:
                    raise
                await asyncio.sleep(retry_backoff_seconds[attempt])
    raise RuntimeError("unreachable Lingya retry state")


def response_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("Lingya response missing choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Lingya response missing message content")
    return content


def load_existing_results(output_path: Path) -> list[dict[str, Any]]:
    if not output_path.exists():
        return []
    data = json.loads(output_path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "results" in data:
        return list(data["results"])
    if isinstance(data, list):
        return data
    return []


async def distill_one_atom(
    *,
    path: Path,
    prompt_template: str,
    semaphore: asyncio.Semaphore,
    model: str,
    endpoint: str,
    api_key: str,
) -> dict[str, Any]:
    atom = json.loads(path.read_text(encoding="utf-8"))
    atom_id = atom.get("canonical_id") or path.stem

    # Option D Hybrid (P1-13.1, architect 047): Python pre-filter runs
    # BEFORE the LLM call. Hard-prune categories (amino acids / chemicals /
    # data_incomplete / brands / time periods / babyfood) bypass the LLM
    # entirely — saves cost AND gives 100% deterministic exclusion.
    prefiltered = prefilter_check(atom)
    if prefiltered is not None:
        prefiltered.setdefault("file", str(path.relative_to(ROOT)))
        prefiltered.setdefault("usage", {})
        prefiltered.setdefault("estimated_cost_usd", 0.0)
        return prefiltered

    messages = render_prompt(prompt_template, atom_id=atom_id, atom=atom, siblings=[])
    payload = await call_lingya_with_retries(
        messages=messages,
        semaphore=semaphore,
        model=model,
        endpoint=endpoint,
        api_key=api_key,
    )
    content = response_content(payload)
    parsed = extract_json_object(content)
    usage = payload.get("usage") or {}
    record = {
        "atom_id": atom_id,
        "file": str(path.relative_to(ROOT)),
        "target_node": parsed.get("target_node", {}),
        "edge_candidates": parsed.get("edge_candidates", {}),
        "confidence_overall": parsed.get("confidence_overall"),
        "per_field_confidence": parsed.get("per_field_confidence", {}),
        "issue_codes": parsed.get("issue_codes", []),
        "evidence_split_candidates": parsed.get("evidence_split_candidates", []),
        "needs_human_review": parsed.get("needs_human_review", False),
        "usage": usage,
        "estimated_cost_usd": estimate_cost_usd(usage),
    }

    # Post-normalize: canonicalise issue_code synonyms + validate enums
    return post_normalize(record)


async def run_distillation(
    *,
    atom_paths: list[Path],
    output_path: Path,
    resume: bool,
    cost_cap_usd: float,
) -> dict[str, Any]:
    endpoint = os.environ.get("L0_API_ENDPOINT")
    api_key = os.environ.get("L0_API_KEY")
    if not endpoint or not api_key:
        raise RuntimeError("L0_API_ENDPOINT and L0_API_KEY are required for Gemini main distillation")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path = output_path.parent / "_progress.json"
    state = load_progress(progress_path) if resume else CheckpointState()
    existing_results = load_existing_results(output_path) if resume else []
    results_by_atom = {record.get("atom_id"): record for record in existing_results}
    prompt_template = load_prompt_template()
    model = os.environ.get("L2A_GEMINI_MODEL", DEFAULT_MODEL)
    semaphore = asyncio.Semaphore(DEFAULT_SEMAPHORE_LIMIT)
    total_cost = sum(float(record.get("estimated_cost_usd") or 0) for record in results_by_atom.values())
    processed_since_checkpoint = 0

    async def run_path(path: Path) -> dict[str, Any]:
        return await distill_one_atom(
            path=path,
            prompt_template=prompt_template,
            semaphore=semaphore,
            model=model,
            endpoint=endpoint,
            api_key=api_key,
        )

    pending_paths = []
    for path in atom_paths:
        atom_id = path.stem
        if atom_id in state.processed_atom_ids:
            continue
        pending_paths.append(path)

    tasks = [asyncio.create_task(run_path(path)) for path in pending_paths]
    for task in asyncio.as_completed(tasks):
        record = await task
        results_by_atom[record["atom_id"]] = record
        state.processed_atom_ids.add(record["atom_id"])
        total_cost += float(record.get("estimated_cost_usd") or 0)
        processed_since_checkpoint += 1
        if total_cost > cost_cap_usd:
            for pending in tasks:
                if not pending.done():
                    pending.cancel()
            raise CostCapExceeded(f"Round cost ${total_cost:.4f} exceeded cap ${cost_cap_usd:.2f}")
        if processed_since_checkpoint >= CHECKPOINT_EVERY:
            state.metadata.update({"last_step": "main_distill", "estimated_cost_usd": total_cost})
            state.save(progress_path)
            atomic_write_json(output_path, {"results": list(results_by_atom.values()), "estimated_cost_usd": total_cost})
            processed_since_checkpoint = 0

    state.metadata.update({"last_step": "main_distill", "estimated_cost_usd": total_cost})
    state.save(progress_path)
    atomic_write_json(output_path, {"results": list(results_by_atom.values()), "estimated_cost_usd": total_cost})
    return {"step": 3, "count": len(results_by_atom), "output": str(output_path), "estimated_cost_usd": total_cost}


async def run_distillation_from_args(
    *,
    limit_atoms: int | None,
    output_path: Path,
    resume: bool,
    test_mode: bool,
    cost_cap_usd: float,
    test_atoms_path: Path,
) -> dict[str, Any]:
    atom_paths = load_atom_paths(limit_atoms=limit_atoms, test_mode=test_mode, test_atoms_path=test_atoms_path)
    return await run_distillation(atom_paths=atom_paths, output_path=output_path, resume=resume, cost_cap_usd=cost_cap_usd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run L2a Gemini main distillation")
    parser.add_argument("--limit-atoms", type=int, default=None)
    parser.add_argument("--test-mode", action="store_true")
    parser.add_argument("--test-atoms", type=Path, default=ROOT / "tests" / "l2a" / "test_atoms.yaml")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--cost-cap-usd", type=float, default=5.0)
    return parser


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = await run_distillation_from_args(
        limit_atoms=args.limit_atoms,
        output_path=args.output,
        resume=args.resume,
        test_mode=args.test_mode,
        cost_cap_usd=args.cost_cap_usd,
        test_atoms_path=args.test_atoms,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
