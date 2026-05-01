#!/usr/bin/env python3
"""
scripts/l0_rescue.py
P1-10 — for records LLM marked `A_l0` but PHN routing left empty,
retry PHN matching with progressively lower cosine thresholds (0.45,
then 0.40). The architect plan calls these "rescue" because they ARE
real L0 chains the embedder couldn't surface at the default 0.5
threshold.

Spec: raw/architect/028-l0-triage-final-v2-20260426.md (post-Phase-2
recovery for A bucket records that still have empty phenomenon_tags).

Strategy:
  1. Reuse anchor embeddings from output/phase1/phn_seeds_raw.json
     (same 76 PHN as the v2 router).
  2. For each A_l0 record without phenomenon_tags, recompute the
     cosine similarities and pick top_k passing the lowered threshold.
  3. Tag the row with `phenomenon_tags`, `phn_scores`, `_rescue_threshold`,
     `_rescue_pass`. We only mutate empty `phenomenon_tags`.

Run:
  /Users/jeff/miniforge3/bin/python3 scripts/l0_rescue.py \\
      --input  output/phase1/l0_phn_routing_v2_llm.jsonl \\
      --output output/phase1/l0_phn_routing_v2_rescued.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import httpx
import numpy as np
from tqdm import tqdm


REPO_ROOT   = Path(__file__).resolve().parents[1]
PHASE1_DIR  = REPO_ROOT / "output" / "phase1"
PHN_FILE    = PHASE1_DIR / "phn_seeds_raw.json"
OLLAMA_URL  = "http://localhost:11434/api/embed"
MODEL       = "qwen3-embedding:8b"

DEFAULT_RESCUE_THRESHOLDS = (0.45, 0.40)
DEFAULT_TOP_K             = 3
DEFAULT_BATCH             = 50


# ── Anchor + record embedding (re-uses pattern from phn_embedding_router.py) ─

def ollama_embed(client: httpx.Client, texts: list[str],
                 retries: int = 3, backoff: tuple[int, ...] = (5, 15, 30)) -> np.ndarray:
    last_err = ""
    for attempt in range(retries):
        try:
            resp = client.post(OLLAMA_URL,
                               json={"model": MODEL, "input": texts},
                               timeout=120)
            resp.raise_for_status()
            return np.asarray(resp.json()["embeddings"], dtype=np.float32)
        except Exception as e:   # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            if attempt < retries - 1:
                time.sleep(backoff[min(attempt, len(backoff) - 1)])
    raise RuntimeError(f"ollama embed failed after {retries} tries: {last_err}")


def _anchor_text(phn: dict) -> str:
    parts = []
    if phn.get("name_en"):    parts.append(phn["name_en"])
    if phn.get("definition"): parts.append(phn["definition"])
    cues = phn.get("observable_cues") or []
    if cues:
        parts.append(" | ".join(str(c) for c in cues))
    return "\n".join(parts)


def _record_text(rec: dict) -> str:
    stmt  = (rec.get("scientific_statement") or "").strip()
    chain = (rec.get("causal_chain_text") or "").strip()
    if stmt and chain and stmt != chain:
        return f"{stmt}\n{chain}"
    return stmt or chain


def load_phn_anchors() -> tuple[list[dict], list[str], np.ndarray]:
    data = json.loads(PHN_FILE.read_text(encoding="utf-8"))
    phns = data.get("phenomena") or []
    ids = [p["phn_id"] for p in phns]
    texts = [_anchor_text(p) for p in phns]
    with httpx.Client(trust_env=False) as client:
        raw = ollama_embed(client, texts)
    norms = np.linalg.norm(raw, axis=1, keepdims=True) + 1e-12
    return phns, ids, raw / norms


# ── Rescue logic ────────────────────────────────────────────────────────────

def needs_rescue(rec: dict) -> bool:
    """Run the lower-threshold retry only on LLM-confirmed A_l0 records
    that still have no phenomenon_tags."""
    return (
        rec.get("triage_label") == "A_l0"
        and not rec.get("phenomenon_tags")
        and bool(_record_text(rec))
    )


def rescue_one(emb: np.ndarray, anchors: np.ndarray, phn_ids: list[str],
               thresholds: tuple[float, ...], top_k: int) -> tuple[list, list, float | None]:
    """Return (phenomenon_tags, phn_scores, threshold_passed_or_None)."""
    sims = emb @ anchors.T
    order = np.argsort(-sims)[:top_k]
    phn_scores = [[phn_ids[i], round(float(sims[i]), 4)] for i in order]
    for thr in thresholds:
        tags = [pid for pid, s in phn_scores if s > thr]
        if tags:
            return tags, phn_scores, thr
    return [], phn_scores, None


# ── CLI ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="P1-10 A_l0 rescue (lower-threshold retry)")
    p.add_argument("--input",  required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--top-k",  type=int, default=DEFAULT_TOP_K)
    p.add_argument("--thresholds", nargs="+", type=float,
                   default=list(DEFAULT_RESCUE_THRESHOLDS),
                   help="Tried in order, descending; first one that yields ≥1 tag wins.")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    p.add_argument("--limit",  type=int, default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1
    thresholds = tuple(sorted(args.thresholds, reverse=True))

    # Load + embed anchors
    phns, phn_ids, anchors = load_phn_anchors()
    print(f"[rescue] loaded {len(phns)} PHN anchors", flush=True)

    # Pass through everything; rescue the eligible subset.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    with open(args.input, encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue

    eligible_idx = [i for i, r in enumerate(records) if needs_rescue(r)]
    if args.limit is not None:
        eligible_idx = eligible_idx[: args.limit]
    print(f"[rescue] {len(eligible_idx)}/{len(records)} records eligible "
          f"(A_l0 + empty phenomenon_tags)", flush=True)

    rescued = 0
    by_threshold: Counter[float] = Counter()

    with httpx.Client(trust_env=False) as client:
        for start in tqdm(range(0, len(eligible_idx), args.batch_size), desc="rescue batches"):
            batch_idx = eligible_idx[start: start + args.batch_size]
            texts = [_record_text(records[i]) for i in batch_idx]
            embs = ollama_embed(client, texts)
            norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-12
            embs = embs / norms
            for k, ridx in enumerate(batch_idx):
                tags, scores, thr = rescue_one(embs[k], anchors, phn_ids,
                                               thresholds, args.top_k)
                rec = records[ridx]
                rec["phn_scores"] = scores
                if tags:
                    rec["phenomenon_tags"]    = tags
                    rec["_rescue_threshold"]  = thr
                    rec["_rescue_pass"]       = True
                    rescued += 1
                    by_threshold[thr] += 1
                else:
                    rec["_rescue_pass"]       = False

    # Write out
    with open(args.output, "w", encoding="utf-8") as fout:
        for rec in records:
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n── L0 A-bucket Rescue ──")
    print(f"  eligible:     {len(eligible_idx)}")
    print(f"  rescued:      {rescued}")
    if eligible_idx:
        print(f"  rescue rate:  {100.0 * rescued / len(eligible_idx):.2f}%")
    for thr, c in sorted(by_threshold.items(), reverse=True):
        print(f"    threshold {thr}: {c}")
    print(f"  output:       {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
