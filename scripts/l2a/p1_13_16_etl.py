#!/usr/bin/env python3
"""P1-13~16 L2a ingredient tree ETL orchestrator.

Day 1 scope wires the seven pipeline steps, checkpoint/resume flags, and a
dry-run route for tests. Later days fill in the heavier Step 5-7 behavior.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


for _proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_proxy_var, None)


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.l2a.etl import cluster_merge, export_neo4j, hard_pruning, relationship_build
from scripts.l2a.etl import main_distill, peer_review
from scripts.l2a.etl.utils.checkpointing import atomic_write_json


ATOM_DIR = ROOT / "output" / "l2a" / "atoms_r2"
ETL_DIR = ROOT / "output" / "l2a" / "etl"
STAGING_DIR = ETL_DIR / "staging"


def iter_atom_paths(atom_dir: Path = ATOM_DIR, limit_atoms: int | None = None) -> list[Path]:
    paths = sorted(atom_dir.glob("*.json"))
    if limit_atoms is not None:
        return paths[:limit_atoms]
    return paths


def ingest_raw_atoms(*, limit_atoms: int | None = None, output_dir: Path = STAGING_DIR) -> dict:
    """Step 1: copy immutable trace metadata into staging jsonl files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = iter_atom_paths(limit_atoms=limit_atoms)
    ingested_at = datetime.now(timezone.utc).isoformat()
    manifest: list[dict] = []

    for path in paths:
        raw_bytes = path.read_bytes()
        raw_json = json.loads(raw_bytes)
        atom_id = raw_json.get("canonical_id") or path.stem
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        record = {
            "atom_id": atom_id,
            "raw_json": raw_json,
            "raw_hash": raw_hash,
            "ingested_at": ingested_at,
        }
        staging_path = output_dir / f"{atom_id}.staging.jsonl"
        tmp_payload = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        tmp_path = staging_path.with_suffix(staging_path.suffix + ".tmp")
        tmp_path.write_text(tmp_payload, encoding="utf-8")
        os.replace(tmp_path, staging_path)
        manifest.append({"atom_id": atom_id, "file": str(staging_path), "raw_hash": raw_hash})

    atomic_write_json(output_dir / "_ingest_manifest.json", {"count": len(manifest), "atoms": manifest})
    return {"step": 1, "count": len(manifest), "output_dir": str(output_dir)}


def resolve_steps(step: str) -> list[int]:
    if step == "all":
        return [5, 6, 7]
    return [int(step)]


async def run_step(step: int, args: argparse.Namespace) -> dict:
    if args.dry_run:
        return {"step": step, "dry_run": True, "limit_atoms": args.limit_atoms}

    if step == 1:
        return ingest_raw_atoms(limit_atoms=args.limit_atoms)
    if step == 2:
        return hard_pruning.run_hard_pruning(
            atom_dir=ATOM_DIR,
            output_path=ETL_DIR / "distilled" / "hard_pruned.json",
            limit_atoms=args.limit_atoms,
            resume=args.resume,
        )
    if step == 3:
        output = Path(args.output) if args.output else ETL_DIR / "distilled" / "main_distill.json"
        return await main_distill.run_distillation_from_args(
            limit_atoms=args.limit_atoms,
            output_path=output,
            resume=args.resume,
            test_mode=args.test_mode,
            cost_cap_usd=args.cost_cap_usd,
            test_atoms_path=Path(args.test_atoms),
        )
    if step == 4:
        return await peer_review.run_peer_review(
            input_path=Path(args.input) if args.input else ETL_DIR / "distilled" / "main_distill.json",
            output_path=Path(args.output) if args.output else ETL_DIR / "distilled" / "peer_review.json",
            limit_atoms=args.limit_atoms,
            resume=args.resume,
        )
    if step == 5:
        return cluster_merge.run_cluster_merge(
            input_path=Path(args.input) if args.input else None,
            output_path=Path(args.output) if args.output else ETL_DIR / "step5_merged.json",
        )
    if step == 6:
        return relationship_build.run_relationship_build(
            input_path=Path(args.input) if args.input else ETL_DIR / "step5_merged.json",
            output_path=Path(args.output) if args.output else ETL_DIR / "step6_edges.json",
        )
    if step == 7:
        return export_neo4j.run_export(
            input_path=Path(args.input) if args.input else ETL_DIR / "step6_edges.json",
            output_dir=Path(args.output_dir or args.output) if (args.output_dir or args.output) else ETL_DIR / "final",
        )
    raise ValueError(f"Unsupported step: {step}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P1-13~16 L2a ingredient tree ETL")
    parser.add_argument("--step", required=True, choices=["1", "2", "3", "4", "5", "6", "7", "all"])
    parser.add_argument("--resume", action="store_true", help="Resume from _progress.json")
    parser.add_argument("--limit-atoms", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Validate routing without side effects")
    parser.add_argument("--test-mode", action="store_true", help="Use tests/l2a/test_atoms.yaml input")
    parser.add_argument("--test-atoms", default=str(ROOT / "tests" / "l2a" / "test_atoms.yaml"))
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--cost-cap-usd", type=float, default=5.0)
    return parser


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results = []
    for step in resolve_steps(args.step):
        results.append(await run_step(step, args))
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
