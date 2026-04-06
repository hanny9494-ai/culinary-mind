#!/usr/bin/env python3
"""Stage 4 deduplication.

Embeds scientific_statement fields via Ollama qwen3-embedding:8b,
then deduplicates by cosine similarity:
  - >0.90  -> duplicate (dropped)
  - 0.75-0.90 -> similar (kept, flagged)
  - <0.75  -> novel (kept)

Also performs internal dedup within open principles (>0.90 threshold).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import requests

# ---------------------------------------------------------------------------
# Ollama embedding session (proxy bypass)
# ---------------------------------------------------------------------------

_OLLAMA_BASE = "http://localhost:11434"
_OLLAMA_SESSION: requests.Session | None = None


def _ollama_session() -> requests.Session:
    global _OLLAMA_SESSION
    if _OLLAMA_SESSION is None:
        _OLLAMA_SESSION = requests.Session()
        _OLLAMA_SESSION.trust_env = False  # bypass http_proxy / https_proxy
    return _OLLAMA_SESSION


def ollama_embed(model: str, text: str, timeout: int = 120) -> list[float]:
    """Get embedding vector from Ollama."""
    session = _ollama_session()
    resp = session.post(
        f"{_OLLAMA_BASE}/api/embed",
        json={"model": model, "input": text},
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    # Ollama /api/embed returns {"embeddings": [[...]]}
    embeddings = body.get("embeddings") or []
    if embeddings and isinstance(embeddings[0], list):
        return embeddings[0]
    # Fallback: older format {"embedding": [...]}
    return body.get("embedding", [])


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a < 1e-12 or norm_b < 1e-12:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

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


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def embed_statements(
    records: list[dict[str, Any]],
    model: str,
    label: str,
) -> list[list[float]]:
    """Embed the scientific_statement field of each record."""
    vectors: list[list[float]] = []
    total = len(records)
    for idx, rec in enumerate(records):
        stmt = str(rec.get("scientific_statement") or "").strip()
        if not stmt:
            vectors.append([])
            continue
        try:
            vec = ollama_embed(model, stmt)
        except Exception as exc:
            print(f"  [WARN] embed error ({label} #{idx}): {exc}", flush=True)
            vec = []
        vectors.append(vec)
        if (idx + 1) % 100 == 0:
            print(f"  {label}: embedded {idx + 1}/{total}", flush=True)
    return vectors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 4 deduplication via embedding cosine similarity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--open-principles", required=True, help="Path to stage4_raw.jsonl (open-extracted principles)")
    parser.add_argument("--existing-principles", required=True, help="Path to l0_principles_v2.jsonl (Stage3b existing)")
    parser.add_argument("--output", required=True, help="Output path for deduplicated JSONL")
    parser.add_argument("--config", required=True, help="Path to config/api.yaml (for Ollama config)")
    parser.add_argument("--embed-model", default="qwen3-embedding:8b", help="Ollama embedding model (default: qwen3-embedding:8b)")
    parser.add_argument("--dup-threshold", type=float, default=0.90, help="Cosine similarity threshold for duplicate (default: 0.90)")
    parser.add_argument("--sim-threshold", type=float, default=0.75, help="Cosine similarity threshold for similar (default: 0.75)")
    args = parser.parse_args()

    dup_thresh = args.dup_threshold
    sim_thresh = args.sim_threshold
    embed_model = args.embed_model

    # Load records
    print(f"Loading open principles from {args.open_principles} ...", flush=True)
    open_recs = load_jsonl(Path(args.open_principles))
    # Filter out error/empty markers
    open_recs = [r for r in open_recs if r.get("scientific_statement", "").strip() and "_error" not in r and not r.get("_empty")]
    print(f"  Loaded {len(open_recs)} open principles (with statements)", flush=True)

    print(f"Loading existing principles from {args.existing_principles} ...", flush=True)
    existing_recs = load_jsonl(Path(args.existing_principles))
    print(f"  Loaded {len(existing_recs)} existing principles", flush=True)

    if not open_recs:
        print("No open principles to deduplicate.", flush=True)
        write_jsonl(Path(args.output), [])
        return

    # Embed all statements
    print("Embedding open principles ...", flush=True)
    open_vecs = embed_statements(open_recs, embed_model, "open")

    print("Embedding existing principles ...", flush=True)
    existing_vecs = embed_statements(existing_recs, embed_model, "existing")

    # Build numpy matrices
    dim = next((len(v) for v in open_vecs if v), 0)
    if dim == 0:
        print("  [WARN] No valid embeddings, skipping dedup", flush=True)
        write_jsonl(Path(args.output), open_recs)
        return

    open_mat = np.array([v if v else [0.0] * dim for v in open_vecs], dtype=np.float32)
    open_has_vec = np.array([bool(v) for v in open_vecs])
    open_norms = np.linalg.norm(open_mat, axis=1, keepdims=True)
    open_norms[open_norms == 0] = 1
    open_normed = open_mat / open_norms

    # --- Internal dedup (numpy矩阵运算) ---
    print("Running internal dedup (open vs open) ...", flush=True)
    sim_matrix = open_normed @ open_normed.T
    dup_i, dup_j = np.where(np.triu(sim_matrix, k=1) > dup_thresh)
    internal_dup_indices: set[int] = set()
    for i, j in zip(dup_i.tolist(), dup_j.tolist()):
        if open_has_vec[i] and open_has_vec[j] and j not in internal_dup_indices:
            internal_dup_indices.add(j)
    print(f"  Internal duplicates removed: {len(internal_dup_indices)}", flush=True)

    # --- Cross-dedup (numpy矩阵运算) ---
    print("Running cross-dedup (open vs existing) ...", flush=True)
    existing_mat = np.array([v if v else [0.0] * dim for v in existing_vecs], dtype=np.float32)
    existing_has_vec = np.array([bool(v) for v in existing_vecs])
    existing_norms = np.linalg.norm(existing_mat, axis=1, keepdims=True)
    existing_norms[existing_norms == 0] = 1
    existing_normed = existing_mat / existing_norms

    cross_sim = open_normed @ existing_normed.T
    cross_sim[:, ~existing_has_vec] = 0.0

    stats = {"duplicate": 0, "similar": 0, "novel": 0, "internal_dup": len(internal_dup_indices)}
    output_records: list[dict[str, Any]] = []

    for i, rec in enumerate(open_recs):
        if i in internal_dup_indices:
            stats["duplicate"] += 1
            continue
        if not open_has_vec[i]:
            rec["dedup_status"] = "novel"
            rec["dedup_max_sim"] = 0.0
            output_records.append(rec)
            stats["novel"] += 1
            continue

        max_idx = int(np.argmax(cross_sim[i]))
        max_sim = float(cross_sim[i, max_idx])
        max_sim_id = str(existing_recs[max_idx].get("principle_id", f"existing_{max_idx}"))

        if max_sim > dup_thresh:
            rec["dedup_status"] = "duplicate"
            rec["dedup_max_sim"] = round(max_sim, 4)
            rec["dedup_match_id"] = max_sim_id
            stats["duplicate"] += 1
            continue
        elif max_sim > sim_thresh:
            rec["dedup_status"] = "similar"
            rec["dedup_max_sim"] = round(max_sim, 4)
            rec["dedup_match_id"] = max_sim_id
            output_records.append(rec)
            stats["similar"] += 1
        else:
            rec["dedup_status"] = "novel"
            rec["dedup_max_sim"] = round(max_sim, 4)
            output_records.append(rec)
            stats["novel"] += 1

    # Write output
    write_jsonl(Path(args.output), output_records)

    print(f"\nDedup summary:", flush=True)
    print(f"  Input open principles: {len(open_recs)}", flush=True)
    print(f"  Internal duplicates:   {stats['internal_dup']}", flush=True)
    print(f"  Cross-duplicates:      {stats['duplicate'] - stats['internal_dup']}", flush=True)
    print(f"  Similar (kept):        {stats['similar']}", flush=True)
    print(f"  Novel (kept):          {stats['novel']}", flush=True)
    print(f"  Output records:        {len(output_records)}", flush=True)
    print(f"  Output: {args.output}", flush=True)


if __name__ == "__main__":
    main()
