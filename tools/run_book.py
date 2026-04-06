#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.quality import check_stage1, check_stage2, check_stage3, check_stage3b


STAGE_ORDER = ["1", "2", "3", "3b"]
STAGE_LABELS = {"1": "stage1", "2": "stage2", "3": "stage3", "3b": "stage3b"}


class OrchestrationError(RuntimeError):
    """Raised when a pipeline stage cannot be completed safely."""


def normalize_stage(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    aliases = {
        "1": "1",
        "stage1": "1",
        "s1": "1",
        "2": "2",
        "stage2": "2",
        "s2": "2",
        "3": "3",
        "stage3": "3",
        "s3": "3",
        "3b": "3b",
        "stage3b": "3b",
        "s3b": "3b",
    }
    if cleaned not in aliases:
        raise argparse.ArgumentTypeError(f"Unsupported stage: {value}")
    return aliases[cleaned]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def count_jsonl_records(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return default
    return json.loads(text)


def extract_chunks(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        chunks = payload.get("chunks") or []
        if isinstance(chunks, list):
            return [item for item in chunks if isinstance(item, dict)]
    return []


def inspect_chunk_file(path: Path) -> dict[str, Any]:
    chunks = extract_chunks(load_json(path, []))
    book_ids = sorted(
        {
            str(chunk.get("source_book") or chunk.get("book_id") or "").strip()
            for chunk in chunks
            if str(chunk.get("source_book") or chunk.get("book_id") or "").strip()
        }
    )
    return {
        "path": path,
        "count": len(chunks),
        "chunks": chunks,
        "book_ids": book_ids,
    }


def discover_chunk_infos(output_root: Path) -> list[dict[str, Any]]:
    infos: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in sorted(output_root.rglob("stage1/chunks_smart.json")):
        if path in seen:
            continue
        seen.add(path)
        info = inspect_chunk_file(path)
        if info["count"] > 0:
            infos.append(info)
    return infos


def discover_chunks(output_root: Path) -> list[str]:
    return [str(info["path"]) for info in discover_chunk_infos(output_root)]


def find_book_stage1_info(output_root: Path, book_id: str) -> dict[str, Any] | None:
    token = book_id.replace("_", "").lower()
    for info in discover_chunk_infos(output_root):
        if book_id in info["book_ids"]:
            return info
        lowered = str(info["path"]).replace("_", "").lower()
        if token and token in lowered:
            return info
    return None


def merge_chunks(chunk_infos: list[dict[str, Any]], merged_path: Path) -> dict[str, Any]:
    merged: list[dict[str, Any]] = []
    source_files: list[str] = []
    for info in chunk_infos:
        source_files.append(str(info["path"]))
        fallback_book = info["book_ids"][0] if info["book_ids"] else info["path"].parts[-3]
        for chunk in info["chunks"]:
            payload = dict(chunk)
            if not str(payload.get("source_book") or payload.get("book_id") or "").strip():
                payload["source_book"] = fallback_book
            merged.append(payload)
    merged_path.parent.mkdir(parents=True, exist_ok=True)
    merged_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": merged_path, "count": len(merged), "source_files": source_files}


def stage_in_range(stage: str, start_stage: str, stop_stage: str) -> bool:
    position = STAGE_ORDER.index(stage)
    return STAGE_ORDER.index(start_stage) <= position <= STAGE_ORDER.index(stop_stage)


def ensure_file(path: Path, description: str, *, allow_missing: bool) -> str | None:
    if path.exists():
        return None
    message = f"{description} not found: {path}"
    if allow_missing:
        return message
    raise OrchestrationError(message)


def ensure_script(path: Path, *, dry_run: bool) -> str | None:
    return ensure_file(path, "required script", allow_missing=dry_run)


def run_command(command: list[str], *, cwd: Path, dry_run: bool) -> None:
    print(f"$ {shlex.join(command)}")
    if dry_run:
        return
    subprocess.run(command, cwd=str(cwd), check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Stage1 -> Stage3B book pipeline")
    parser.add_argument("--book-id", required=True, help="Book identifier from config/books.yaml")
    parser.add_argument("--output-root", required=True, help="Root output directory")
    parser.add_argument("--questions", required=True, help="Question master JSON path")
    parser.add_argument("--config", required=True, help="API config YAML path")
    parser.add_argument("--books", required=True, help="Books registry YAML path")
    parser.add_argument("--toc", required=True, help="TOC config JSON path")
    parser.add_argument("--domains", required=True, help="Domain config JSON path")
    parser.add_argument("--start-stage", type=normalize_stage, default="1", help="First stage to run")
    parser.add_argument("--stop-stage", type=normalize_stage, default="3b", help="Last stage to run")
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands without executing subprocesses")
    parser.add_argument("--skip-stage1", action="store_true", help="Skip Stage 1 and reuse existing chunks")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if STAGE_ORDER.index(args.start_stage) > STAGE_ORDER.index(args.stop_stage):
        parser.error("--start-stage must be earlier than or equal to --stop-stage")

    repo_root = Path(__file__).resolve().parent.parent
    output_root = Path(args.output_root).expanduser()
    stage1_dir = output_root / args.book_id / "stage1"
    stage2_dir = output_root / "stage2"
    stage3_dir = output_root / "stage3"
    report_path = output_root / "run_report.json"

    started_at = now_iso()
    started_perf = time.perf_counter()
    warnings: list[str] = []
    run_report: dict[str, Any] = {
        "book_id": args.book_id,
        "started_at": started_at,
        "stage1": {"status": "not_requested"},
        "stage2": {"status": "not_requested"},
        "stage3": {"status": "not_requested"},
        "stage3b": {"status": "not_requested"},
    }

    try:
        config_path = Path(args.config).expanduser()
        books_path = Path(args.books).expanduser()
        questions_path = Path(args.questions).expanduser()
        toc_path = Path(args.toc).expanduser()
        domains_path = Path(args.domains).expanduser()

        for path, description in (
            (config_path, "config"),
            (books_path, "books registry"),
            (questions_path, "questions"),
            (domains_path, "domains"),
        ):
            warning = ensure_file(path, description, allow_missing=args.dry_run)
            if warning:
                warnings.append(warning)

        if stage_in_range("1", args.start_stage, args.stop_stage):
            warning = ensure_file(toc_path, "toc config", allow_missing=args.dry_run)
            if warning:
                warnings.append(warning)

        chunk_infos = discover_chunk_infos(output_root)
        existing_stage1 = find_book_stage1_info(output_root, args.book_id)
        if existing_stage1 and existing_stage1["path"].parent != stage1_dir:
            warnings.append(f"reusing existing Stage 1 chunks from {existing_stage1['path']}")

        if stage_in_range("1", args.start_stage, args.stop_stage):
            stage_started = time.perf_counter()
            should_skip = args.skip_stage1 or existing_stage1 is not None
            if should_skip:
                if existing_stage1 is None:
                    if args.dry_run:
                        run_report["stage1"] = {"status": "dry_run", "chunks": 0}
                    else:
                        raise OrchestrationError(
                            f"--skip-stage1 requested but no valid chunks_smart.json found for {args.book_id}"
                        )
                else:
                    stage1_summary = check_stage1(existing_stage1["path"].parent)
                    run_report["stage1"] = {
                        "status": "skipped",
                        "chunks": stage1_summary["chunks"],
                        "output_path": stage1_summary["output_path"],
                    }
            else:
                script_path = repo_root / "scripts" / "stage1_pipeline.py"
                warning = ensure_script(script_path, dry_run=args.dry_run)
                if warning:
                    warnings.append(warning)
                command = [
                    sys.executable,
                    str(script_path),
                    "--book-id",
                    args.book_id,
                    "--output-dir",
                    str(stage1_dir),
                    "--config",
                    str(config_path),
                    "--books",
                    str(books_path),
                    "--toc",
                    str(toc_path),
                ]
                if args.dry_run:
                    command.append("--dry-run")
                run_command(command, cwd=repo_root, dry_run=args.dry_run)
                if args.dry_run:
                    run_report["stage1"] = {"status": "dry_run", "chunks": 0}
                else:
                    stage1_summary = check_stage1(stage1_dir)
                    if not stage1_summary["valid"]:
                        raise OrchestrationError("Stage 1 quality gate failed: chunks_smart.json is missing or empty")
                    run_report["stage1"] = {
                        "status": "completed",
                        "chunks": stage1_summary["chunks"],
                        "output_path": stage1_summary["output_path"],
                    }
                    existing_stage1 = inspect_chunk_file(Path(stage1_summary["output_path"]))
            run_report["stage1"]["elapsed_seconds"] = round(time.perf_counter() - stage_started, 2)

        if stage_in_range("2", args.start_stage, args.stop_stage):
            stage_started = time.perf_counter()
            chunk_infos = discover_chunk_infos(output_root)
            if not chunk_infos and not args.dry_run:
                raise OrchestrationError(f"No valid chunks_smart.json files found under {output_root}")
            script_path = repo_root / "scripts" / "stage2_match.py"
            warning = ensure_script(script_path, dry_run=args.dry_run)
            if warning:
                warnings.append(warning)
            stage2_dir.mkdir(parents=True, exist_ok=True)
            stage2_output = stage2_dir / "question_chunk_matches.json"
            chunk_args = discover_chunks(output_root)
            if not chunk_args and args.dry_run:
                chunk_args = ["<discovered-chunks>"]
            command = [sys.executable, str(script_path)]
            for chunk_arg in chunk_args:
                command.extend(["--chunks", chunk_arg])
            command.extend(
                [
                    "--questions",
                    str(questions_path),
                    "--output",
                    str(stage2_output),
                    "--config",
                    str(config_path),
                ]
            )
            if args.dry_run:
                command.append("--dry-run")
            run_command(command, cwd=repo_root, dry_run=args.dry_run)
            if args.dry_run:
                run_report["stage2"] = {"status": "dry_run", "matched": 0, "match_rate": 0.0}
            else:
                stage2_summary = check_stage2(stage2_output)
                if not stage2_summary["valid"]:
                    raise OrchestrationError("Stage 2 quality gate failed: no match rows were produced")
                if stage2_summary["match_rate"] <= 0.8:
                    warnings.append(
                        f"Stage 2 match rate is {stage2_summary['match_rate']:.3f}, below the 0.8 warning threshold"
                    )
                run_report["stage2"] = {
                    "status": "completed",
                    "matched": stage2_summary["matched"],
                    "total_questions": stage2_summary["total_questions"],
                    "match_rate": stage2_summary["match_rate"],
                    "output_path": stage2_summary["output_path"],
                }
            run_report["stage2"]["elapsed_seconds"] = round(time.perf_counter() - stage_started, 2)

        if stage_in_range("3", args.start_stage, args.stop_stage):
            stage_started = time.perf_counter()
            stage2_output = stage2_dir / "question_chunk_matches.json"
            merged_chunks_path = stage3_dir / "merged_chunks.json"
            chunk_infos = discover_chunk_infos(output_root)
            if not chunk_infos and not args.dry_run:
                raise OrchestrationError(f"No valid chunks_smart.json files found under {output_root}")
            merged_info = {"path": merged_chunks_path, "count": 0, "source_files": []}
            if chunk_infos:
                merged_info = merge_chunks(chunk_infos, merged_chunks_path)
            elif args.dry_run:
                stage3_dir.mkdir(parents=True, exist_ok=True)

            script_path = repo_root / "scripts" / "stage3_distill.py"
            warning = ensure_script(script_path, dry_run=args.dry_run)
            if warning:
                warnings.append(warning)

            pre_count = count_jsonl_records(stage3_dir / "l0_principles.jsonl")
            command = [
                sys.executable,
                str(script_path),
                "--matches",
                str(stage2_output),
                "--chunks",
                str(merged_chunks_path),
                "--output-dir",
                str(stage3_dir),
                "--config",
                str(config_path),
                "--domains",
                str(domains_path),
                "--append",
            ]
            if args.dry_run:
                command.append("--dry-run")
            run_command(command, cwd=repo_root, dry_run=args.dry_run)
            if args.dry_run:
                run_report["stage3"] = {"status": "dry_run", "principles": pre_count}
            else:
                stage3_summary = check_stage3(stage3_dir)
                new_count = stage3_summary["principles"] - pre_count
                if new_count <= 0:
                    raise OrchestrationError("Stage 3 quality gate failed: no new principles were produced")
                run_report["stage3"] = {
                    "status": "completed",
                    "principles": stage3_summary["principles"],
                    "new_principles": new_count,
                    "cost_usd": stage3_summary["cost_usd"],
                    "merged_chunks": merged_info["count"],
                    "output_path": stage3_summary["output_path"],
                }
            run_report["stage3"]["elapsed_seconds"] = round(time.perf_counter() - stage_started, 2)

        if stage_in_range("3b", args.start_stage, args.stop_stage):
            stage_started = time.perf_counter()
            stage3_input = stage3_dir / "l0_principles.jsonl"
            stage2_output = stage2_dir / "question_chunk_matches.json"
            stage3b_output = stage3_dir / "l0_principles_v2.jsonl"
            stage3b_report = stage3_dir / "stage3b_report.txt"
            script_path = repo_root / "scripts" / "stage3b_causal.py"
            warning = ensure_script(script_path, dry_run=args.dry_run)
            if warning:
                warnings.append(warning)

            command = [
                sys.executable,
                str(script_path),
                "--input",
                str(stage3_input),
                "--matches",
                str(stage2_output),
                "--output",
                str(stage3b_output),
                "--report",
                str(stage3b_report),
                "--config",
                str(config_path),
            ]
            if args.dry_run:
                command.append("--dry-run")
            run_command(command, cwd=repo_root, dry_run=args.dry_run)
            if args.dry_run:
                run_report["stage3b"] = {"status": "dry_run", "records": count_jsonl_records(stage3b_output)}
            else:
                stage3b_summary = check_stage3b(stage3b_output)
                if not stage3b_summary["valid"]:
                    raise OrchestrationError("Stage 3B quality gate failed: no enriched records were produced")
                run_report["stage3b"] = {
                    "status": "completed",
                    "records": stage3b_summary["records"],
                    "splits": stage3b_summary["splits"],
                    "type_distribution": stage3b_summary["type_distribution"],
                    "output_path": stage3b_summary["output_path"],
                }
            run_report["stage3b"]["elapsed_seconds"] = round(time.perf_counter() - stage_started, 2)

        run_report["overall"] = "dry_run" if args.dry_run else "success"
    except (OrchestrationError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        run_report["overall"] = "failed"
        run_report["error"] = str(exc)

    finished_at = now_iso()
    elapsed_minutes = round((time.perf_counter() - started_perf) / 60.0, 2)
    run_report["finished_at"] = finished_at
    run_report["elapsed_minutes"] = elapsed_minutes
    if warnings:
        run_report["warnings"] = warnings

    output_root.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(run_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(run_report, ensure_ascii=False, indent=2))

    if run_report["overall"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
