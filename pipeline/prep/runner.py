#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_QUEUE = [
    "bocuse_cookbook",
    "essentials_food_science",
    "taste_whats_missing",
    "flavor_bible",
    "modernist_pizza",
    "professional_pastry_chef",
    "french_patisserie",
    "phoenix_claws",
]


class RunnerError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def count_json_list(path: Path) -> int:
    data = load_json(path, [])
    return len(data) if isinstance(data, list) else 0


def log_line(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")
    print(message, flush=True)


def ensure_root_raw(book_dir: Path) -> bool:
    root_raw = book_dir / "raw_merged.md"
    prep_raw = book_dir / "prep" / "raw_merged.md"
    stage1_raw = book_dir / "stage1" / "raw_merged.md"
    if root_raw.exists():
        return True
    if prep_raw.exists():
        root_raw.write_text(prep_raw.read_text(encoding="utf-8"), encoding="utf-8")
        return True
    if stage1_raw.exists():
        root_raw.write_text(stage1_raw.read_text(encoding="utf-8"), encoding="utf-8")
        return True
    return False


def infer_book_status(book_dir: Path) -> dict[str, Any]:
    raw_merged = book_dir / "raw_merged.md"
    chunks_raw = book_dir / "chunks_raw.json"
    # Try new path first, fall back to old
    prep_dir = book_dir / "prep"
    stage1_dir = book_dir / "stage1"
    if (prep_dir / "chunks_smart.json").exists():
        smart = prep_dir / "chunks_smart.json"
        failures = prep_dir / "annotation_failures.json"
    else:
        smart = stage1_dir / "chunks_smart.json"
        failures = stage1_dir / "annotation_failures.json"
    progress = load_json(book_dir / "stage1_progress.json", {})
    raw_count = count_json_list(chunks_raw)
    smart_count = count_json_list(smart)
    failure_count = count_json_list(failures)
    completed = (
        raw_count > 0 and smart_count > 0 and smart_count + failure_count >= raw_count
    ) or str(progress.get("status") or "") == "completed"
    if completed:
        action = "done"
    elif raw_count > 0:
        action = "step4_5"
    elif raw_merged.exists():
        action = "step4_5"
    else:
        action = "blocked"
    return {
        "action": action,
        "raw_count": raw_count,
        "smart_count": smart_count,
        "failure_count": failure_count,
        "progress": progress,
    }




def acquire_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("w", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise RunnerError(f"Another prep_serial_runner is already active: {lock_path}") from exc
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serial queue runner for local Ollama prep Step4+5")
    parser.add_argument("--config", required=True)
    parser.add_argument("--books", required=True)
    parser.add_argument("--toc", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--queue", nargs="*", default=DEFAULT_QUEUE)
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--lock-file", default=None)
    parser.add_argument("--state-file", default=None)
    parser.add_argument("--log-file", default=None)
    parser.add_argument("--watchdog", type=int, default=0)
    parser.add_argument("--repair-state", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def finalize_book_state(
    state: dict[str, Any],
    state_path: Path,
    book_id: str,
    book_dir: Path,
    *,
    result_label: str,
    returncode: int,
    error: str | None = None,
) -> dict[str, Any]:
    post = infer_book_status(book_dir)
    state["books"][book_id].update(post)
    state["books"][book_id]["finished_at"] = now_iso()
    state["books"][book_id]["returncode"] = returncode
    state["books"][book_id]["result"] = result_label
    if error:
        state["books"][book_id]["error"] = error
    save_json(state_path, state)
    return post


def main() -> int:
    args = build_parser().parse_args()
    output_root = Path(args.output_root).expanduser()
    logs_dir = output_root / "logs"
    lock_path = Path(args.lock_file).expanduser() if args.lock_file else logs_dir / "prep_serial_runner.lock"
    state_path = Path(args.state_file).expanduser() if args.state_file else logs_dir / "prep_serial_runner_state.json"
    log_path = Path(args.log_file).expanduser() if args.log_file else logs_dir / "prep_serial_runner.log"
    logs_dir.mkdir(parents=True, exist_ok=True)
    lock_handle = acquire_lock(lock_path)

    state = {
        "started_at": now_iso(),
        "runner_pid": os.getpid(),
        "queue": list(args.queue),
        "books": {},
    }
    save_json(state_path, state)
    log_line(log_path, f"[runner] start pid={os.getpid()} queue={','.join(args.queue)}")

    try:
        for book_id in args.queue:
            book_dir = output_root / book_id
            ensure_root_raw(book_dir)
            status = infer_book_status(book_dir)
            state["books"][book_id] = {**status, "checked_at": now_iso(), "book_dir": str(book_dir)}
            save_json(state_path, state)

            if status["action"] == "done":
                log_line(log_path, f"[runner] skip completed {book_id} raw={status['raw_count']} smart={status['smart_count']} fail={status['failure_count']}")
                continue
            if status["action"] == "blocked":
                log_line(log_path, f"[runner] blocked {book_id}: missing raw_merged.md")
                state["books"][book_id]["result"] = "blocked"
                save_json(state_path, state)
                return 2

            cmd = [
                sys.executable,
                "/Users/jeff/culinary-mind/pipeline/prep/pipeline.py",
                "--book-id", book_id,
                "--config", args.config,
                "--books", args.books,
                "--toc", args.toc,
                "--output-dir", str(book_dir),
                "--start-step", "4",
                "--stop-step", "5",
            ]
            if args.watchdog > 0:
                cmd.extend(["--watchdog", str(args.watchdog)])
            if args.repair_state:
                cmd.append("--repair-state")
            if args.dry_run:
                cmd.append("--dry-run")

            state["books"][book_id]["started_at"] = now_iso()
            state["books"][book_id]["command"] = cmd
            save_json(state_path, state)
            log_line(log_path, f"[runner] launch {book_id}")

            try:
                result = subprocess.run(cmd, cwd="/Users/jeff/culinary-mind")
            except BaseException as exc:
                post = finalize_book_state(
                    state,
                    state_path,
                    book_id,
                    book_dir,
                    result_label="runner_error",
                    returncode=99,
                    error=repr(exc),
                )
                log_line(
                    log_path,
                    f"[runner] crashed {book_id} raw={post['raw_count']} smart={post['smart_count']} fail={post['failure_count']} error={repr(exc)}",
                )
                raise

            post = finalize_book_state(
                state,
                state_path,
                book_id,
                book_dir,
                result_label="done" if result.returncode == 0 else "failed",
                returncode=result.returncode,
            )
            if result.returncode != 0:
                log_line(
                    log_path,
                    f"[runner] failed {book_id} rc={result.returncode} raw={post['raw_count']} smart={post['smart_count']} fail={post['failure_count']}",
                )
                return result.returncode
            log_line(log_path, f"[runner] done {book_id} raw={post['raw_count']} smart={post['smart_count']} fail={post['failure_count']}")
    finally:
        log_line(log_path, "[runner] exit")
        try:
            lock_handle.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
