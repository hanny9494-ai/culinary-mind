#!/usr/bin/env python3
"""distill_r2.py — L2a R2 deep distillation via Lingya gemini-3-flash-preview-search (streaming)

Usage:
  python pipeline/l2a/distill_r2.py [--limit N] [--concurrency 4] [--batch-size 5]
  python pipeline/l2a/distill_r2.py --retry-failed   # retry _failed/ atoms

Notes:
  - stream=True is REQUIRED — AiGoCode non-streaming has a bug where
    message.content is None.
  - Resume is enabled by default: atoms with existing R2 files are skipped.
  - Progress checkpoint written to atoms_r2/_progress.json every 50 atoms.
  - --retry-failed: reprocesses atoms in _failed/*.json (JSON parse errors etc.)
    On success, removes files from _failed/ and writes to atoms_r2/.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# ── Clear proxy env vars (must run before any network import) ─────────────────
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY"):
    os.environ.pop(_k, None)
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "output" / "l2a"
ATOMS_R1_DIR = OUTPUT_ROOT / "atoms"
ATOMS_R2_DIR = OUTPUT_ROOT / "atoms_r2"
FAILED_DIR = ATOMS_R2_DIR / "_failed"
PROGRESS_FILE = ATOMS_R2_DIR / "_progress.json"
PROGRESS_LOG = ATOMS_R2_DIR / "_progress.log"
RUN_LOG = ATOMS_R2_DIR / "_run.log"
PROMPT_FILE = REPO_ROOT / "pipeline" / "l2a" / "prompts" / "r2_distill.txt"

# ── AiGoCode config ────────────────────────────────────────────────────────────
MODEL = "gemini-3-flash-preview-search"
LINGYA_ENDPOINT = os.environ.get("LINGYA_API_ENDPOINT", "https://api.lingyaai.cn/v1")
CHECKPOINT_EVERY = 50   # write _progress.json every N atoms
# R2 adds exactly these fields to R1 atoms (all other fields come from R1)
R2_NEW_FIELDS = {'culinary_deep', 'substitutes', 'processing_effects',
                 'quality_indicators', 'l0_principles'}
MAX_RETRIES = 3  # increased for retry-failed mode
RETRY_DELAYS = [2, 8, 30]   # exponential backoff seconds

# ── Logging ────────────────────────────────────────────────────────────────────
ATOMS_R2_DIR.mkdir(parents=True, exist_ok=True)
FAILED_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(RUN_LOG, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ── Streaming SSE call ─────────────────────────────────────────────────────────
async def call_aigocode_streaming(
    client: httpx.AsyncClient,
    system_prompt: str,
    user_content: str,
) -> tuple[str, int]:
    """
    Call AiGoCode with stream=True. Accumulate delta.content from SSE.
    Returns (full_content, total_tokens).
    Non-streaming mode has a server-side bug where message.content is None.
    """
    api_key = os.environ.get("LINGYA_API_KEY", "")
    if not api_key:
        raise RuntimeError("LINGYA_API_KEY is not set")

    url = LINGYA_ENDPOINT.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {
        "model": MODEL,
        "stream": True,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }

    content_parts: list[str] = []
    total_tokens = 0

    async with client.stream(
        "POST", url, json=payload, headers=headers,
    ) as resp:
        resp.raise_for_status()
        async for raw_line in resp.aiter_lines():
            line = raw_line.strip()
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            # Accumulate content delta
            choices = chunk.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                text = delta.get("content") or ""
                content_parts.append(text)

            # Capture usage if present (some providers emit it in the last chunk)
            if chunk.get("usage"):  # guard: usage can be None
                total_tokens = chunk["usage"].get("total_tokens", 0)

    return "".join(content_parts), total_tokens


# ── Retry wrapper ──────────────────────────────────────────────────────────────
async def call_with_retry(
    client: httpx.AsyncClient,
    system_prompt: str,
    user_content: str,
) -> tuple[str, int]:
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return await call_aigocode_streaming(client, system_prompt, user_content)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 500, 502, 503, 504):
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                log.warning(f"HTTP {e.response.status_code} on attempt {attempt+1}, retry in {delay}s")
                await asyncio.sleep(delay)
                last_exc = e
            else:
                raise
        except httpx.RequestError as e:
            delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
            log.warning(f"RequestError on attempt {attempt+1}: {e}, retry in {delay}s")
            await asyncio.sleep(delay)
            last_exc = e
    raise RuntimeError(f"All {MAX_RETRIES} attempts failed") from last_exc


# ── JSON extraction + repair ───────────────────────────────────────────────────
def repair_json(text: str) -> str:
    """Attempt light repair of common JSON issues from model output.

    Handles:
    - Trailing commas before ] or }
    - Missing closing braces/brackets (count mismatch)
    """
    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # Balance braces/brackets by appending missing closers
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()

    # Append missing closers in reverse
    if stack:
        text = text.rstrip() + "".join(reversed(stack))

    return text


def extract_json_array(text: str) -> list[dict]:
    """Extract JSON array from model response (handles markdown fences + repair)."""
    t = text.strip()
    # Strip markdown code fence
    if t.startswith("```"):
        lines = [l for l in t.splitlines() if not l.strip().startswith("```")]
        t = "\n".join(lines).strip()
    # Find array bounds
    start = t.find("[")
    end = t.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON array found in response (len={len(t)})")

    candidate = t[start:end + 1]
    # First try clean parse
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Try with repair
    repaired = repair_json(candidate)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse failed even after repair: {e}") from e


# ── Progress tracking ──────────────────────────────────────────────────────────
class Progress:
    def __init__(self, total: int, started_at: str):
        self.total = total
        self.done = 0
        self.failed = 0
        self.total_tokens = 0
        self.started_at = started_at
        self.current_batch = 0
        self.last_canonical_id = ""
        self._lock = asyncio.Lock()

    async def update(self, done_delta: int = 0, failed_delta: int = 0,
                     tokens: int = 0, canonical_id: str = "") -> None:
        async with self._lock:
            self.done += done_delta
            self.failed += failed_delta
            self.total_tokens += tokens
            if canonical_id:
                self.last_canonical_id = canonical_id
            if (self.done + self.failed) % CHECKPOINT_EVERY == 0 or done_delta + failed_delta > 0:
                await self._write()

    async def _write(self) -> None:
        now = time.time()
        started_ts = time.mktime(time.strptime(self.started_at, "%Y-%m-%dT%H:%M:%S"))
        elapsed = max(now - started_ts, 1)
        speed = self.done / elapsed  # atoms/sec
        remaining = self.total - self.done - self.failed
        eta = int(remaining / speed) if speed > 0 else -1
        # Cost estimate: gemini-3-flash-preview-search ~$0.15/M tokens (rough estimate)
        cost_usd = self.total_tokens / 1_000_000 * 0.15

        data = {
            "done": self.done,
            "total": self.total,
            "failed": self.failed,
            "started_at": self.started_at,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "current_batch": self.current_batch,
            "eta_seconds": eta,
            "cost_estimate_usd": round(cost_usd, 4),
            "last_canonical_id": self.last_canonical_id,
            "total_tokens": self.total_tokens,
        }
        try:
            PROGRESS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            log.warning(f"Failed to write progress: {e}")


def log_atom_result(canonical_id: str, status: str, tokens: int, latency_ms: int) -> None:
    try:
        with PROGRESS_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{canonical_id}\t{status}\t{tokens}\t{latency_ms}\n")
    except Exception:
        pass


# ── Core batch processing ──────────────────────────────────────────────────────
async def process_batch(
    client: httpx.AsyncClient,
    batch: list[dict],
    system_prompt: str,
    progress: Progress,
    semaphore: asyncio.Semaphore,
    retry_mode: bool = False,
) -> None:
    """Process a batch of R1 atoms, write R2 files, update progress.

    In retry_mode=True: on success, also remove the corresponding _failed/ files.
    """
    canonical_ids = [a["canonical_id"] for a in batch]
    log.info(f"{'[RETRY] ' if retry_mode else ''}Batch [{', '.join(canonical_ids)}] — sending to API")
    t0 = time.time()

    async with semaphore:
        try:
            # Only send minimal seed to reduce input tokens — R1 data merged in post-processing
            # (full R1 JSON caused streaming truncation / JSON parse errors)
            seed_batch = [
                {"canonical_id": a["canonical_id"],
                 "display_name": a.get("display_name", {}),
                 "category": a.get("category", "")}
                for a in batch
            ]
            user_msg = json.dumps(seed_batch, ensure_ascii=False)
            raw, tokens = await asyncio.wait_for(
                call_with_retry(client, system_prompt, user_msg),
                timeout=300.0  # 5 min total cap — prevents hung streaming calls
            )
            latency_ms = int((time.time() - t0) * 1000)
        except Exception as e:
            log.error(f"Batch failed after retries: {canonical_ids}: {e}")
            for atom in batch:
                cid = atom["canonical_id"]
                FAILED_DIR.joinpath(f"{cid}.json").write_text(
                    json.dumps(atom, ensure_ascii=False, indent=2))
                FAILED_DIR.joinpath(f"{cid}.err").write_text(str(e))
                log_atom_result(cid, "fail", 0, 0)
            await progress.update(failed_delta=len(batch))
            return

    # Parse response
    try:
        r2_atoms = extract_json_array(raw)
    except (ValueError, json.JSONDecodeError) as e:
        log.error(f"JSON parse failed for batch {canonical_ids}: {e}\nRaw: {raw[:300]}")
        for atom in batch:
            cid = atom["canonical_id"]
            FAILED_DIR.joinpath(f"{cid}.json").write_text(
                json.dumps(atom, ensure_ascii=False, indent=2))
            FAILED_DIR.joinpath(f"{cid}.err").write_text(
                f"JSON parse error: {e}\nRaw:\n{raw[:2000]}")
            log_atom_result(cid, "fail_parse", 0, latency_ms)
        await progress.update(failed_delta=len(batch))
        return

    if len(r2_atoms) != len(batch):
        log.warning(f"Response count mismatch: got {len(r2_atoms)}, expected {len(batch)}")

    tokens_per_atom = tokens // max(len(r2_atoms), 1)
    for i, r2 in enumerate(r2_atoms):
        if i >= len(batch):
            break
        r1 = batch[i]
        cid = r2.get("canonical_id") or r1["canonical_id"]
        # Merge: ensure all R1 fields are present (model might drop some)
        # R1 is authoritative base; only graft the 5 new R2 fields
        merged = {**r1}
        for field in R2_NEW_FIELDS:
            if field in r2:
                merged[field] = r2[field]
        merged["canonical_id"] = cid  # never let model change this
        # Ensure data_confidence always present (model sometimes omits it)
        if "data_confidence" not in merged:
            merged["data_confidence"] = r2.get("data_confidence", "high")

        out_path = ATOMS_R2_DIR / f"{cid}.json"
        try:
            out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
            log.info(f"  ✓ {cid} ({latency_ms}ms)")
            log_atom_result(cid, "done" if not retry_mode else "retry_ok", tokens_per_atom, latency_ms)
            await progress.update(done_delta=1, tokens=tokens_per_atom, canonical_id=cid)
            # Clean up _failed/ on successful retry
            if retry_mode:
                for ext in (".json", ".err"):
                    p = FAILED_DIR / f"{cid}{ext}"
                    if p.exists():
                        p.unlink()
                log.info(f"  ↩ removed {cid} from _failed/")
        except Exception as e:
            log.error(f"  ✗ write failed for {cid}: {e}")
            log_atom_result(cid, "fail_write", 0, latency_ms)
            await progress.update(failed_delta=1)


# ── Main ───────────────────────────────────────────────────────────────────────
async def main(args: argparse.Namespace) -> None:
    api_key = os.environ.get("LINGYA_API_KEY", "")
    if not api_key:
        raise SystemExit("ERROR: LINGYA_API_KEY env var not set")

    # Load system prompt
    if not PROMPT_FILE.exists():
        raise SystemExit(f"ERROR: Prompt file not found: {PROMPT_FILE}")
    system_prompt = PROMPT_FILE.read_text(encoding="utf-8").strip()

    # ── Retry-failed mode ──────────────────────────────────────────────────────
    if args.retry_failed:
        failed_jsons = sorted(FAILED_DIR.glob("*.json"))
        if not failed_jsons:
            log.info("No failed atoms found in _failed/. Nothing to retry.")
            return
        to_process: list[dict] = []
        for f in failed_jsons:
            try:
                atom = json.loads(f.read_text(encoding="utf-8"))
                # Ensure canonical_id matches stem (some failed atoms keep R1 data)
                atom.setdefault("canonical_id", f.stem)
                to_process.append(atom)
            except Exception as e:
                log.warning(f"Skip unreadable failed atom {f.name}: {e}")
        if args.limit:
            to_process = to_process[:args.limit]
        total = len(to_process)
        log.info(f"Retry mode: {total} failed atoms to reprocess (concurrency={args.concurrency})")

        started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        progress = Progress(total=total, started_at=started_at)

        # Always batch_size=1 for retry — avoids compound JSON parse failures
        batches = [[atom] for atom in to_process]
        semaphore = asyncio.Semaphore(args.concurrency)

        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(120.0),
        ) as client:
            tasks = [
                asyncio.create_task(
                    process_batch(client, [atom], system_prompt, progress, semaphore, retry_mode=True)
                )
                for atom in to_process
            ]
            await asyncio.gather(*tasks)

        await progress._write()
        remaining_failed = len(list(FAILED_DIR.glob("*.json")))
        log.info(f"Retry done: {progress.done} recovered, {progress.failed} still failing")
        log.info(f"Remaining in _failed/: {remaining_failed} atoms")
        return

    # ── Normal mode ────────────────────────────────────────────────────────────

    # Discover R1 atoms
    r1_files = sorted(ATOMS_R1_DIR.glob("*.json"))
    if not r1_files:
        raise SystemExit(f"ERROR: No R1 atoms found in {ATOMS_R1_DIR}")
    log.info(f"Found {len(r1_files)} R1 atoms")

    # Resume: skip already-done R2 files + previously failed atoms
    done_ids: set[str] = set()
    if args.resume:
        done_ids = {p.stem for p in ATOMS_R2_DIR.glob("*.json")
                    if not p.name.startswith("_")}
        log.info(f"Resume: {len(done_ids)} already done, skipping")
        failed_ids = {p.stem for p in FAILED_DIR.glob("*.json")}
        if failed_ids:
            done_ids |= failed_ids
            log.info(f"Resume: skipping {len(failed_ids)} previously failed atoms (use --retry-failed to reprocess)")

    # Build work queue
    to_process = []
    for f in r1_files:
        cid = f.stem
        if cid in done_ids:
            continue
        try:
            atom = json.loads(f.read_text(encoding="utf-8"))
            to_process.append(atom)
        except Exception as e:
            log.warning(f"Skip unreadable R1 {f.name}: {e}")

    if args.limit:
        to_process = to_process[:args.limit]

    total = len(to_process)
    if total == 0:
        log.info("Nothing to process — all done! (use --retry-failed to reprocess failed atoms)")
        return

    log.info(f"Processing {total} atoms via {MODEL} (concurrency={args.concurrency}, "
             f"batch_size={args.batch_size})")

    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    progress = Progress(total=total + len(done_ids), started_at=started_at)
    progress.done = len(done_ids)

    # Build batches
    batches: list[list[dict]] = []
    for i in range(0, total, args.batch_size):
        batches.append(to_process[i:i + args.batch_size])

    semaphore = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(120.0),
    ) as client:
        tasks = []
        for batch_idx, batch in enumerate(batches):
            progress.current_batch = batch_idx
            task = asyncio.create_task(
                process_batch(client, batch, system_prompt, progress, semaphore)
            )
            tasks.append(task)

        await asyncio.gather(*tasks)

    # Final progress write
    await progress._write()
    log.info(f"Done: {progress.done} success, {progress.failed} failed out of {total} new")
    log.info(f"Progress: {PROGRESS_FILE}")
    log.info(f"Cost estimate: ${progress.total_tokens/1_000_000*0.15:.4f} USD ({progress.total_tokens} tokens @ gemini-3-flash-preview-search)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="L2a R2 deep distillation via Lingya gemini-3-flash-preview-search")
    p.add_argument("--limit", type=int, default=None,
                   help="Process only first N atoms (for testing)")
    p.add_argument("--concurrency", type=int, default=4,
                   help="Number of concurrent API calls (default: 4)")
    p.add_argument("--batch-size", type=int, default=1,
                   help="Atoms per API call (default: 1; batch>1 causes count mismatches with gemini-3-flash)")
    p.add_argument("--no-resume", action="store_false", dest="resume",
                   help="Disable resume (reprocess already-done atoms)")
    p.add_argument("--retry-failed", action="store_true",
                   help="Retry atoms in _failed/ (JSON parse errors etc.). Uses batch_size=1.")
    p.set_defaults(resume=True, retry_failed=False)
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        sys.exit(1)
