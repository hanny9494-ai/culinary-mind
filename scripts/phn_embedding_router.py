#!/usr/bin/env python3
"""
scripts/phn_embedding_router.py
P1-08 Embedding router — tag each L0 record (stage4_dedup.jsonl) with its
closest-matching Phenomenon (PHN) ids.

Pipeline:
  1. Load 71 PHNs from output/phase1/phn_seeds_raw.json
  2. Build an anchor text per PHN: name_en + definition + observable_cues
  3. Embed anchors via Ollama qwen3-embedding:8b → (71, D) matrix
  4. Walk every output/{book}/stage4/stage4_dedup.jsonl:
       – extract scientific_statement (fallback causal_chain_text)
       – batch-embed (default 50/batch)
       – cosine-similarity against the 71 anchors
       – keep top-K (default 3) PHNs with sim > threshold (default 0.5)
       – append one JSONL row per L0 record, augmented with:
           phenomenon_tags: [phn_id, ...]       # passing threshold
           phn_scores:      [[phn_id, sim], …]  # top-K regardless
  5. Write aggregate stats → output/phase1/phn_routing_stats.json
       – per-PHN L0 count
       – coverage %
       – low-coverage warnings (PHN with <5 L0)

Resume:
  Per-book progress tracked in output/phase1/_phn_routing_progress.json.
  `--resume` skips any book already marked `done`. Partial books are
  replayed from scratch; inside a book we process sequentially so a
  mid-book crash wastes at most ~1 book's work (~1–2 min).

Run:
  /Users/jeff/miniforge3/bin/python3 scripts/phn_embedding_router.py
  /Users/jeff/miniforge3/bin/python3 scripts/phn_embedding_router.py --resume
  /Users/jeff/miniforge3/bin/python3 scripts/phn_embedding_router.py --limit 500  # smoke
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from tqdm import tqdm


# ── Paths / config ────────────────────────────────────────────────────────────

REPO_ROOT    = Path(__file__).resolve().parents[1]
OUTPUT_ROOT  = REPO_ROOT / "output"
PHASE1_DIR   = OUTPUT_ROOT / "phase1"

PHN_FILE      = PHASE1_DIR / "phn_seeds_raw.json"
OUT_ROUTING   = PHASE1_DIR / "l0_phn_routing.jsonl"
OUT_STATS     = PHASE1_DIR / "phn_routing_stats.json"
PROGRESS_FILE = PHASE1_DIR / "_phn_routing_progress.json"

OLLAMA_URL   = "http://localhost:11434/api/embed"
MODEL        = "qwen3-embedding:8b"

DEFAULT_BATCH     = 50
DEFAULT_THRESHOLD = 0.5
DEFAULT_TOP_K     = 3
LOW_COVERAGE      = 5   # warn if a PHN collects fewer than this many L0s


# ── Ollama client ─────────────────────────────────────────────────────────────

def _ollama_embed(client: httpx.Client, texts: list[str],
                  retries: int = 3, backoff: tuple[int, ...] = (5, 15, 30)) -> np.ndarray:
    """Batch embed `texts`; returns (N, D) float32 numpy array.

    Retries with exponential backoff on transient errors.
    """
    last_err: str = ""
    for attempt in range(retries):
        try:
            resp = client.post(
                OLLAMA_URL,
                json={"model": MODEL, "input": texts},
                timeout=120,
            )
            resp.raise_for_status()
            embs = resp.json()["embeddings"]
            return np.asarray(embs, dtype=np.float32)
        except Exception as e:   # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            if attempt < retries - 1:
                delay = backoff[min(attempt, len(backoff) - 1)]
                print(f"  [warn] ollama embed attempt {attempt+1}/{retries} failed "
                      f"({last_err}); backing off {delay}s", flush=True)
                time.sleep(delay)
    raise RuntimeError(f"ollama embed failed after {retries} tries: {last_err}")


# ── PHN anchors ──────────────────────────────────────────────────────────────

def _anchor_text(phn: dict) -> str:
    """Concatenate name_en + definition + observable_cues into one string."""
    parts: list[str] = []
    if phn.get("name_en"):     parts.append(phn["name_en"])
    if phn.get("definition"):  parts.append(phn["definition"])
    cues = phn.get("observable_cues") or []
    if cues:
        parts.append(" | ".join(str(c) for c in cues))
    return "\n".join(parts)


def load_phns() -> tuple[list[dict], list[str]]:
    data = json.loads(PHN_FILE.read_text(encoding="utf-8"))
    phns = data.get("phenomena") or []
    if not phns:
        raise RuntimeError(f"No phenomena in {PHN_FILE}")
    texts = [_anchor_text(p) for p in phns]
    return phns, texts


# ── L0 source discovery ──────────────────────────────────────────────────────

def discover_l0_files() -> list[Path]:
    """Return sorted list of stage4_dedup.jsonl paths (one per book)."""
    files = sorted(OUTPUT_ROOT.glob("*/stage4/stage4_dedup.jsonl"))
    return files


def _l0_record_text(rec: dict) -> str:
    """Text used for embedding an L0 record."""
    stmt  = (rec.get("scientific_statement") or "").strip()
    chain = (rec.get("causal_chain_text") or "").strip()
    if stmt and chain and stmt != chain:
        return f"{stmt}\n{chain}"
    return stmt or chain


# ── Progress ────────────────────────────────────────────────────────────────

def _load_progress() -> dict:
    if not PROGRESS_FILE.exists():
        return {"books_done": []}
    try:
        return json.loads(PROGRESS_FILE.read_text())
    except Exception:
        return {"books_done": []}


def _save_progress(progress: dict) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(progress, indent=2))
    tmp.replace(PROGRESS_FILE)


# ── Per-book processing ─────────────────────────────────────────────────────

def process_book(
    book_path: Path,
    phn_ids:   list[str],
    anchors:   np.ndarray,            # (P, D) L2-normalised
    client:    httpx.Client,
    out_fh,
    batch_size: int,
    top_k:      int,
    threshold:  float,
    per_phn_count: dict,
    limit_remaining: int | None,
) -> tuple[int, int]:
    """Process one stage4_dedup.jsonl. Returns (records_processed, records_tagged).

    limit_remaining: if not None, stop after writing this many records (smoke cap).
    """
    book_id = book_path.parent.parent.name
    # Load records first so we can batch cleanly + support --limit early-stop.
    records: list[dict] = []
    with open(book_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            records.append(rec)
            if limit_remaining is not None and len(records) >= limit_remaining:
                break

    if not records:
        return 0, 0

    texts = [_l0_record_text(r) for r in records]
    n = len(records)
    processed = 0
    tagged = 0

    for start in range(0, n, batch_size):
        batch = texts[start: start + batch_size]
        # guard against blank rows
        non_blank_idxs = [i for i, t in enumerate(batch) if t.strip()]
        if not non_blank_idxs:
            # emit unchanged rows with empty tags
            for i in range(len(batch)):
                r = records[start + i]
                out = dict(r)
                out["phenomenon_tags"] = []
                out["phn_scores"] = []
                out["_book_id"] = book_id
                out_fh.write(json.dumps(out, ensure_ascii=False) + "\n")
                processed += 1
            continue

        non_blank_texts = [batch[i] for i in non_blank_idxs]
        embs = _ollama_embed(client, non_blank_texts)   # (len(non_blank), D)

        # L2-normalise rows so dot product == cosine
        norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-12
        embs = embs / norms

        # Cosine against anchors
        sims = embs @ anchors.T   # (len(non_blank), P)

        # Build per-record output
        sims_by_batch_idx: dict[int, np.ndarray] = {
            ni: sims[k] for k, ni in enumerate(non_blank_idxs)
        }

        for i in range(len(batch)):
            r = records[start + i]
            out = dict(r)
            out["_book_id"] = book_id
            row_sims = sims_by_batch_idx.get(i)
            if row_sims is None:
                out["phenomenon_tags"] = []
                out["phn_scores"] = []
            else:
                order = np.argsort(-row_sims)[:top_k]
                phn_scores = [
                    [phn_ids[idx], round(float(row_sims[idx]), 4)]
                    for idx in order
                ]
                phenomenon_tags = [pid for pid, s in phn_scores if s > threshold]
                out["phenomenon_tags"] = phenomenon_tags
                out["phn_scores"] = phn_scores
                if phenomenon_tags:
                    tagged += 1
                    for pid in phenomenon_tags:
                        per_phn_count[pid] += 1
            out_fh.write(json.dumps(out, ensure_ascii=False) + "\n")
            processed += 1

        # periodic flush
        if (start // batch_size) % 5 == 4:
            out_fh.flush()

    out_fh.flush()
    return processed, tagged


# ── Main ────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PHN embedding router (P1-08)")
    p.add_argument("--resume", action="store_true",
                   help="Skip books already marked done in progress file")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH,
                   help=f"Texts per Ollama embed call (default {DEFAULT_BATCH})")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                   help=f"Top-K PHNs to record per L0 (default {DEFAULT_TOP_K})")
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                   help=f"Cosine threshold for phenomenon_tags (default {DEFAULT_THRESHOLD})")
    p.add_argument("--limit", type=int, default=None,
                   help="Smoke-test cap on total records processed")
    p.add_argument("--only-book", action="append",
                   help="Restrict to one or more book ids (repeatable)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    PHASE1_DIR.mkdir(parents=True, exist_ok=True)
    phns, phn_texts = load_phns()
    phn_ids = [p["phn_id"] for p in phns]
    print(f"[phn-router] loaded {len(phns)} PHN anchors", flush=True)

    with httpx.Client(trust_env=False) as client:
        print("[phn-router] embedding anchors …", flush=True)
        anchors_raw = _ollama_embed(client, phn_texts)
        # L2 normalise anchors once
        anc_norms = np.linalg.norm(anchors_raw, axis=1, keepdims=True) + 1e-12
        anchors = anchors_raw / anc_norms

        files = discover_l0_files()
        if args.only_book:
            selected = set(args.only_book)
            files = [f for f in files if f.parent.parent.name in selected]
        print(f"[phn-router] scanning {len(files)} stage4_dedup.jsonl files", flush=True)

        progress = _load_progress() if args.resume else {"books_done": []}
        done_set = set(progress.get("books_done") or [])

        # Truncate output if not resuming
        mode = "a" if args.resume else "w"
        out_fh = open(OUT_ROUTING, mode, encoding="utf-8")

        per_phn_count: dict[str, int] = defaultdict(int)
        total_proc = 0
        total_tag = 0
        limit_remaining = args.limit

        try:
            for fp in tqdm(files, desc="books"):
                book_id = fp.parent.parent.name
                if book_id in done_set:
                    tqdm.write(f"  [skip] {book_id} already done")
                    continue
                if limit_remaining is not None and limit_remaining <= 0:
                    break

                proc, tagged = process_book(
                    fp, phn_ids, anchors, client, out_fh,
                    args.batch_size, args.top_k, args.threshold,
                    per_phn_count,
                    limit_remaining,
                )
                total_proc += proc
                total_tag  += tagged
                if limit_remaining is not None:
                    limit_remaining -= proc

                done_set.add(book_id)
                progress["books_done"] = sorted(done_set)
                _save_progress(progress)
                tqdm.write(f"  [done] {book_id}: {proc} records, {tagged} tagged "
                           f"(total: {total_proc} / tagged {total_tag})")
        finally:
            out_fh.close()

    # Stats
    stats = {
        "_meta": {
            "task":           "P1-08",
            "date":           time.strftime("%Y-%m-%d", time.gmtime()),
            "model":          MODEL,
            "threshold":      args.threshold,
            "top_k":          args.top_k,
            "total_phns":     len(phns),
            "total_records":  total_proc,
            "tagged_records": total_tag,
            "coverage_pct":   round(100.0 * total_tag / total_proc, 2) if total_proc else 0.0,
        },
        "per_phn": [
            {
                "phn_id":     pid,
                "name_en":    p.get("name_en"),
                "domain":     p.get("domain"),
                "l0_count":   per_phn_count.get(pid, 0),
            }
            for pid, p in zip(phn_ids, phns)
        ],
        "low_coverage_phns": [
            pid for pid in phn_ids
            if per_phn_count.get(pid, 0) < LOW_COVERAGE
        ],
    }
    # sort per_phn by l0_count desc for easy reading
    stats["per_phn"].sort(key=lambda r: -r["l0_count"])

    OUT_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[phn-router] processed {total_proc} records, {total_tag} tagged "
          f"({stats['_meta']['coverage_pct']}%)")
    print(f"[phn-router] low-coverage PHNs (<{LOW_COVERAGE} L0): "
          f"{len(stats['low_coverage_phns'])}")
    for pid in stats["low_coverage_phns"][:10]:
        print(f"  ! {pid}: {per_phn_count.get(pid, 0)}")
    print(f"\n  output routing: {OUT_ROUTING}")
    print(f"  stats:          {OUT_STATS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
