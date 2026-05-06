"""Step 4 GPT peer review skeleton for P1-13~16."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import re
import sys
import threading
from pathlib import Path
from typing import Any

import httpx


for _proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_proxy_var, None)


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.l2a.etl.utils.checkpointing import CheckpointState, atomic_write_json, load_progress


PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "gpt_peer_review.txt"
DEFAULT_MODEL = "gpt-5.4"
DEFAULT_HARD_TIMEOUT_SECONDS = 300
DEFAULT_RETRY_BACKOFF_SECONDS = (5, 10, 20)
DEFAULT_SEMAPHORE_LIMIT = 5


def needs_peer_review(gemini_output: dict[str, Any]) -> bool:
    if float(gemini_output.get("confidence_overall") or 0.0) < 0.85:
        return True
    if gemini_output.get("needs_human_review"):
        return True
    flags = set(gemini_output.get("issue_codes") or [])
    return bool(
        flags
        & {
            "zh_sci_mismatch",
            "cuisine_deep_taxon_mismatch",
            "same_sci_cluster_outlier",
            "composition_implausible",
            "identity_conflict",
            "suspect",
        }
    )


def extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
    if fence_match:
        stripped = fence_match.group(1)
    return json.loads(stripped)


def parse_peer_review_response(content: str) -> dict[str, Any]:
    parsed = extract_json_object(content)
    required = {"agreement", "corrections", "issues_added", "issues_removed", "reason", "final_review_status"}
    missing = required - set(parsed)
    if missing:
        raise ValueError(f"Peer review response missing fields: {sorted(missing)}")
    return parsed


def _post_once(*, endpoint: str, api_key: str, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    payload = {"model": model, "messages": messages, "temperature": 0}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = endpoint.rstrip("/")
    if not url.endswith("/v1/chat/completions"):
        url += "/v1/chat/completions"
    with httpx.Client(trust_env=False, timeout=None) as client:
        response = client.post(url, headers=headers, json=payload)
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
            result_queue.put(("ok", _post_once(endpoint=endpoint, api_key=api_key, model=model, messages=messages)))
        except BaseException as exc:  # noqa: BLE001
            result_queue.put(("error", exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(hard_timeout_seconds)
    if thread.is_alive():
        raise TimeoutError(f"Lingya request exceeded {hard_timeout_seconds}s hard timeout")
    status, payload = result_queue.get_nowait()
    if status == "error":
        raise payload
    return payload


async def run_peer_review(
    *,
    input_path: Path,
    output_path: Path,
    limit_atoms: int | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path = output_path.parent / "_progress.json"
    state = load_progress(progress_path) if resume else CheckpointState()

    if not input_path.exists():
        atomic_write_json(output_path, {"results": [], "note": "input missing; Day 1 skeleton"})
        return {"step": 4, "count": 0, "output": str(output_path), "skeleton": True}

    data = json.loads(input_path.read_text(encoding="utf-8"))
    records = data.get("results", data if isinstance(data, list) else [])
    selected = [record for record in records if needs_peer_review(record)]
    if limit_atoms is not None:
        selected = selected[:limit_atoms]

    results = []
    for record in selected:
        atom_id = record.get("atom_id")
        if atom_id in state.processed_atom_ids:
            continue
        results.append({"atom_id": atom_id, "status": "pending_day2_peer_review"})
        state.processed_atom_ids.add(atom_id)
    atomic_write_json(output_path, {"results": results})
    state.metadata["last_step"] = "peer_review"
    state.save(progress_path)
    await asyncio.sleep(0)
    return {"step": 4, "count": len(results), "output": str(output_path), "skeleton": True}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run L2a GPT peer review")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit-atoms", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    return parser


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = await run_peer_review(input_path=args.input, output_path=args.output, limit_atoms=args.limit_atoms, resume=args.resume)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
