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


def load_prompt_template(path: Path = PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")


def render_prompt(
    template: str,
    *,
    raw_atom_json: dict[str, Any],
    siblings: list[dict[str, Any]],
    gemini_target_node: dict[str, Any],
    gemini_issues: list[str],
    gemini_conf: float,
) -> list[dict[str, str]]:
    rendered = (
        template.replace("{raw_atom_json}", json.dumps(raw_atom_json, ensure_ascii=False, sort_keys=True))
        .replace("{siblings}", json.dumps(siblings, ensure_ascii=False, sort_keys=True))
        .replace("{gemini_target_node}", json.dumps(gemini_target_node, ensure_ascii=False, sort_keys=True))
        .replace("{gemini_issues}", json.dumps(gemini_issues, ensure_ascii=False, sort_keys=True))
        .replace("{gemini_conf}", str(gemini_conf))
    )
    if rendered.startswith("SYSTEM:") and "\nUSER:\n" in rendered:
        system_part, user_part = rendered.split("\nUSER:\n", 1)
        return [
            {"role": "system", "content": system_part.removeprefix("SYSTEM:\n").strip()},
            {"role": "user", "content": user_part.strip()},
        ]
    return [{"role": "user", "content": rendered}]


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


async def _post_async(
    *, client: httpx.AsyncClient, endpoint: str, api_key: str,
    model: str, messages: list[dict[str, str]],
    hard_timeout_seconds: int = DEFAULT_HARD_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Native async POST. Replaces threading.join wrapper (Round 3 v3 fix)."""
    payload = {"model": model, "messages": messages, "temperature": 0}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = endpoint.rstrip("/")
    if not url.endswith("/v1/chat/completions"):
        url += "/v1/chat/completions"
    response = await asyncio.wait_for(
        client.post(url, headers=headers, json=payload),
        timeout=hard_timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


# Backward-compat shim (raises rather than silently working with leak).
def post_with_thread_timeout(*args, **kwargs):  # pragma: no cover - legacy
    raise RuntimeError(
        "post_with_thread_timeout is deprecated; use _post_async (Round 3 v3 fix)"
    )


_HTTPX_ASYNC_CLIENT: httpx.AsyncClient | None = None


def _get_async_client() -> httpx.AsyncClient:
    global _HTTPX_ASYNC_CLIENT
    if _HTTPX_ASYNC_CLIENT is None or _HTTPX_ASYNC_CLIENT.is_closed:
        _HTTPX_ASYNC_CLIENT = httpx.AsyncClient(
            trust_env=False,
            timeout=httpx.Timeout(DEFAULT_HARD_TIMEOUT_SECONDS),
            limits=httpx.Limits(max_connections=DEFAULT_SEMAPHORE_LIMIT * 2,
                                max_keepalive_connections=DEFAULT_SEMAPHORE_LIMIT),
        )
    return _HTTPX_ASYNC_CLIENT


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
        client = _get_async_client()
        attempts = len(retry_backoff_seconds) + 1
        for attempt in range(attempts):
            try:
                return await _post_async(
                    client=client,
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


# Real Lingya pricing (per dispatch_1778178479123, Jeff 02:00 decision):
#   input:  ¥5.6 / 1M = $0.000778 / 1K (at ¥7.2/USD)
#   output: ¥17 / 1M  = $0.00236 / 1K (3x input typical)
#   blended (67:33 in:out): $0.0013 / 1K
DEFAULT_PRICE_PER_1K_TOKENS_USD = 0.0153  # Lingya Gemini blended USD: input $5.6/1M + output $33.6/1M
ATOM_DIR = ROOT / "output" / "l2a" / "atoms_r2"


def estimate_cost_usd(usage: dict, price_per_1k: float = DEFAULT_PRICE_PER_1K_TOKENS_USD) -> float:
    tokens = (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
    return tokens / 1000.0 * price_per_1k


def response_content(payload: dict[str, Any]) -> str:
    return payload["choices"][0]["message"]["content"]


async def review_one_atom(
    *,
    record: dict[str, Any],
    semaphore: asyncio.Semaphore,
    model: str,
    endpoint: str,
    api_key: str,
    prompt_template: str,
) -> dict[str, Any]:
    """Call GPT 5.4 to peer-review a single Gemini main_distill record."""
    atom_id = record.get("atom_id") or "?"
    raw_path = ATOM_DIR / f"{atom_id}.json"
    raw_atom = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {}

    messages = render_prompt(
        prompt_template,
        raw_atom_json=raw_atom,
        siblings=[],  # cluster siblings handled in Step 5; empty for canary
        gemini_target_node=record.get("target_node", {}),
        gemini_issues=list(record.get("issue_codes") or []),
        gemini_conf=float(record.get("confidence_overall") or 0.0),
    )
    payload = await call_lingya_with_retries(
        messages=messages,
        semaphore=semaphore,
        model=model,
        endpoint=endpoint,
        api_key=api_key,
    )
    content = response_content(payload)
    try:
        parsed = parse_peer_review_response(content)
    except Exception as exc:
        parsed = {
            "agreement": "refine",
            "corrections": {},
            "issues_added": [],
            "issues_removed": [],
            "reason": f"parse_error: {exc}",
            "final_review_status": "needs_review",
        }
    usage = payload.get("usage") or {}
    return {
        "atom_id": atom_id,
        "gemini_confidence": float(record.get("confidence_overall") or 0.0),
        "gemini_issues": list(record.get("issue_codes") or []),
        "gpt_review": parsed,
        "usage": usage,
        "estimated_cost_usd": estimate_cost_usd(usage),
    }


async def run_peer_review(
    *,
    input_path: Path,
    output_path: Path,
    limit_atoms: int | None = None,
    resume: bool = False,
    cost_cap_usd: float = 2.0,
) -> dict[str, Any]:
    """Run GPT 5.4 peer_review on records that pass needs_peer_review()."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path = output_path.parent / "_progress.json"
    state = load_progress(progress_path) if resume else CheckpointState()

    if not input_path.exists():
        atomic_write_json(output_path, {"results": [], "note": "input missing"})
        return {"step": 4, "count": 0, "output": str(output_path)}

    data = json.loads(input_path.read_text(encoding="utf-8"))
    records = data.get("results", data if isinstance(data, list) else [])
    candidates = [r for r in records if needs_peer_review(r)]
    if limit_atoms is not None:
        candidates = candidates[:limit_atoms]

    endpoint = os.environ.get("L0_API_ENDPOINT")
    api_key = os.environ.get("L0_API_KEY")
    if not endpoint or not api_key:
        raise RuntimeError("L0_API_ENDPOINT and L0_API_KEY are required for GPT peer review")

    prompt_template = load_prompt_template()
    model = os.environ.get("L2A_GPT_MODEL", DEFAULT_MODEL)
    semaphore = asyncio.Semaphore(DEFAULT_SEMAPHORE_LIMIT)

    pending = [r for r in candidates if r.get("atom_id") not in state.processed_atom_ids]
    results: list[dict[str, Any]] = []
    total_cost = 0.0

    async def review_path(record: dict[str, Any]) -> dict[str, Any]:
        return await review_one_atom(
            record=record,
            semaphore=semaphore,
            model=model,
            endpoint=endpoint,
            api_key=api_key,
            prompt_template=prompt_template,
        )

    tasks = [asyncio.create_task(review_path(r)) for r in pending]
    for task in asyncio.as_completed(tasks):
        out = await task
        results.append(out)
        total_cost += float(out.get("estimated_cost_usd") or 0.0)
        state.processed_atom_ids.add(out["atom_id"])
        state.metadata["last_step"] = "peer_review"
        state.metadata["estimated_cost_usd"] = total_cost
        state.save(progress_path)
        if total_cost > cost_cap_usd:
            atomic_write_json(output_path, {
                "results": results,
                "estimated_cost_usd": total_cost,
                "blocked_at_cap": True,
                "cap_usd": cost_cap_usd,
            })
            raise RuntimeError(
                f"peer_review cost ${total_cost:.4f} exceeded cap ${cost_cap_usd:.2f}; "
                "stopped per Round 2 protocol fix"
            )

    atomic_write_json(output_path, {
        "results": results,
        "n_total_records": len(records),
        "n_candidates_for_review": len(candidates),
        "n_processed_this_run": len(results),
        "estimated_cost_usd": total_cost,
    })
    return {
        "step": 4,
        "count": len(results),
        "output": str(output_path),
        "estimated_cost_usd": total_cost,
        "trigger_rate": f"{len(candidates)}/{len(records)}",
    }


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
