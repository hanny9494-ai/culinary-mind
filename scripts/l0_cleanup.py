#!/usr/bin/env python3
"""
scripts/l0_cleanup.py
Phase-1 closing step — turn the 55,348-record `l0_phn_routing_v3.jsonl`
(post-triage) into five physical bucket files.

Input:
  output/phase1/l0_phn_routing_v3.jsonl
  – every record carries `phenomenon_tags`, `_triage_label`,
    `_triage_reason`, optional `_rescue_phn`/`_rescue_score`.
  – `_triage_label` is empty/missing for records already PHN-tagged in
    v2 routing (i.e. confirmed L0 with phenomenon_tags non-empty).

Output buckets (all under output/phase1/):
  l0_clean.jsonl              — confirmed L0
                                (phenomenon_tags non-empty OR
                                 _triage_label ∈ {_rescued_l0,
                                 _rescued_l0_weak, _routed_new})
  l0_migrated_to_l2a.jsonl    — _l2a_candidate (rule-flagged static
                                attributes; LLM judge C)
  l0_tagged_l1.jsonl          — _l1_candidate (equipment; LLM judge B)
                                — TAGGED only, NOT removed from L0 store
  l0_adjacent.jsonl           — _adjacent (medical/regulation/ecology;
                                LLM judge D); subtype carried per record
  l0_review_pool.jsonl        — _review + _unclassified + _l0_orphan
                                + any (LLM judge E noise)

Stats: output/phase1/l0_cleanup_stats.json
  – per-bucket counts + pct
  – cross-tab by L0 domain
  – top 10 most-polluted books (lowest l0_clean ratio)

Run:
  /Users/jeff/miniforge3/bin/python3 scripts/l0_cleanup.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


REPO_ROOT   = Path(__file__).resolve().parents[1]
PHASE1_DIR  = REPO_ROOT / "output" / "phase1"

INPUT_FILE  = PHASE1_DIR / "l0_phn_routing_v3.jsonl"

# Architect's LLM Phase-2 outputs. Each record has _rec_idx (line index
# into v3) + llm_label ∈ {A_l0, B_l1, C_l2a, D_adjacent, E_noise} +
# llm_confidence + llm_reason. We merge them into the bucket logic so
# records that the LLM has already classified don't sit in review_pool.
LLM_TRIAGE_FILES: tuple[Path, ...] = (
    PHASE1_DIR / "review_llm_triage.jsonl",
    PHASE1_DIR / "unclassified_llm_triage.jsonl",
)

OUT_CLEAN     = PHASE1_DIR / "l0_clean.jsonl"
OUT_L2A       = PHASE1_DIR / "l0_migrated_to_l2a.jsonl"
OUT_L1        = PHASE1_DIR / "l0_tagged_l1.jsonl"
OUT_ADJACENT  = PHASE1_DIR / "l0_adjacent.jsonl"
OUT_REVIEW    = PHASE1_DIR / "l0_review_pool.jsonl"
OUT_STATS     = PHASE1_DIR / "l0_cleanup_stats.json"


# ── Bucket classifier ────────────────────────────────────────────────────────

# Sets used by classify_bucket(); see module docstring for the contract.
_CLEAN_LABELS    = {"_rescued_l0", "_rescued_l0_weak", "_routed_new", "A_l0"}
_L2A_LABELS      = {"_l2a_candidate", "C_l2a"}
_L1_LABELS       = {"_l1_candidate", "B_l1"}
_ADJACENT_LABELS = {"_adjacent", "D_adjacent"}
_REVIEW_LABELS   = {"_review", "_unclassified", "_l0_orphan"}
_NOISE_LABELS    = {"E_noise", "_noise"}   # not output, only counted

# Maps LLM label → bucket name. LLM labels are authoritative when
# present (architect runs them after the rule layer, with full reason
# + confidence in the response).
_LLM_LABEL_TO_BUCKET: dict[str, str] = {
    "A_l0":       "clean",
    "B_l1":       "l1",
    "C_l2a":      "l2a",
    "D_adjacent": "adjacent",
    "E_noise":    "noise",
}


def classify_bucket(rec: dict, llm_label_by_idx: dict[int, str] | None = None) -> str:
    """Return one of:
        'clean' / 'l2a' / 'l1' / 'adjacent' / 'review' / 'noise'

    Decision order (first match wins):
      1. `phenomenon_tags` non-empty                       → clean
      2. v3 `_triage_label` already in clean-positive set
         (rescue / routed_new)                              → clean
      3. LLM Phase-2 label (architect, via `_rec_idx` lookup)
                                                            → mapped bucket
      4. v3 `_triage_label` in l2a / l1 / adjacent / noise / review
      5. fall-through                                       → review

    The LLM step is checked AFTER step 2 so that already-confirmed L0
    (PHN-tagged or rescued) is never demoted by a later LLM call.
    """
    if rec.get("phenomenon_tags"):
        return "clean"
    label = rec.get("_triage_label") or rec.get("triage_label") or ""
    if label in _CLEAN_LABELS:
        return "clean"

    # LLM Phase-2 result (authoritative for ambiguous records).
    if llm_label_by_idx is not None:
        idx = rec.get("_rec_idx")
        if isinstance(idx, int):
            llm_label = llm_label_by_idx.get(idx)
            if llm_label and llm_label in _LLM_LABEL_TO_BUCKET:
                return _LLM_LABEL_TO_BUCKET[llm_label]

    if label in _L2A_LABELS:
        return "l2a"
    if label in _L1_LABELS:
        return "l1"
    if label in _ADJACENT_LABELS:
        return "adjacent"
    if label in _NOISE_LABELS:
        return "noise"
    if label in _REVIEW_LABELS:
        return "review"
    return "review"


# ── LLM triage merge ────────────────────────────────────────────────────────

def load_llm_triage(paths: Iterable[Path]) -> tuple[dict[int, str], dict[int, dict]]:
    """Load architect's Phase-2 LLM triage outputs.

    Returns:
      (idx → llm_label, idx → full record).

    The full record includes llm_confidence + llm_reason so we can
    propagate them into the bucket output for downstream review.
    """
    label_by_idx: dict[int, str] = {}
    record_by_idx: dict[int, dict] = {}
    for p in paths:
        if not p.exists():
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                idx = d.get("_rec_idx")
                if not isinstance(idx, int):
                    continue
                lab = d.get("llm_label")
                if not lab:
                    continue
                # Earliest seen wins (architect's two files are
                # non-overlapping by design but defensively guard).
                label_by_idx.setdefault(idx, lab)
                record_by_idx.setdefault(idx, d)
    return label_by_idx, record_by_idx


# ── Adjacent subtype helper ──────────────────────────────────────────────────

# Optional: the rule layer or LLM may have left `triage_adjacent_subtype`
# already; otherwise re-derive cheaply from the statement text.

_ADJACENT_KEYWORD_TO_SUBTYPE: tuple[tuple[tuple[str, ...], str], ...] = (
    ((
        "饮用水法规", "氯胺", "氯化", "脱氯", "净水",
    ), "water_chemistry"),
    ((
        "FDA", "USDA", "食品法典", "法规", "GMP",
    ), "regulation"),
    ((
        "碳足迹", "温室气体", "农药残留", "可持续",
    ), "ecology"),
    ((
        "患者", "临床", "感染", "免疫", "过敏", "癌症", "心血管",
        "代谢综合征", "肠道菌群", "口腔菌群", "耐药",
        "病理", "流行病学",
    ), "medical"),
)


def adjacent_subtype(rec: dict) -> str:
    sub = rec.get("triage_adjacent_subtype")
    if sub:
        return sub
    text = (rec.get("scientific_statement") or "").strip()
    for kws, name in _ADJACENT_KEYWORD_TO_SUBTYPE:
        if any(k in text for k in kws):
            return name
    return "unknown"


# ── Pipeline ────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="P1 closing — split v3 routing into buckets")
    parser.add_argument("--input",  type=Path, default=INPUT_FILE)
    parser.add_argument("--limit",  type=int, default=None,
                        help="Smoke-test cap on input lines")
    parser.add_argument("--no-llm-triage", action="store_true",
                        help="Skip the LLM Phase-2 merge (debug only).")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    PHASE1_DIR.mkdir(parents=True, exist_ok=True)

    # Load architect's LLM Phase-2 outputs once into memory. The maps are
    # keyed by `_rec_idx`, which is the line index of the v3 file.
    llm_label_by_idx: dict[int, str] = {}
    llm_record_by_idx: dict[int, dict] = {}
    if not args.no_llm_triage:
        llm_label_by_idx, llm_record_by_idx = load_llm_triage(LLM_TRIAGE_FILES)
    print(f"[cleanup] LLM triage: {len(llm_label_by_idx)} idx → label "
          f"({sum(1 for v in llm_label_by_idx.values() if v == 'A_l0')} A_l0, "
          f"{sum(1 for v in llm_label_by_idx.values() if v == 'B_l1')} B_l1, "
          f"{sum(1 for v in llm_label_by_idx.values() if v == 'C_l2a')} C_l2a, "
          f"{sum(1 for v in llm_label_by_idx.values() if v == 'D_adjacent')} D_adjacent, "
          f"{sum(1 for v in llm_label_by_idx.values() if v == 'E_noise')} E_noise)",
          flush=True)

    # Open writers
    fh = {
        "clean":    open(OUT_CLEAN,    "w", encoding="utf-8"),
        "l2a":      open(OUT_L2A,      "w", encoding="utf-8"),
        "l1":       open(OUT_L1,       "w", encoding="utf-8"),
        "adjacent": open(OUT_ADJACENT, "w", encoding="utf-8"),
        "review":   open(OUT_REVIEW,   "w", encoding="utf-8"),
    }

    counts: Counter[str] = Counter()
    by_domain: dict[str, Counter[str]] = defaultdict(Counter)
    by_book: dict[str, Counter[str]] = defaultdict(Counter)
    adjacent_subtypes: Counter[str] = Counter()
    label_distribution: Counter[str] = Counter()
    llm_merge_count = 0   # how many records ended up in a non-review
                          # bucket because of the LLM step (audit trail)

    n = 0
    rec_idx = -1
    try:
        with open(args.input, encoding="utf-8") as fin:
            for line in fin:
                rec_idx += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue

                # Stamp the line index so classify_bucket() can look up
                # the LLM Phase-2 label without recomputing.
                if "_rec_idx" not in rec:
                    rec["_rec_idx"] = rec_idx

                bucket = classify_bucket(rec, llm_label_by_idx)
                counts[bucket] += 1
                domain = rec.get("domain") or "unclassified"
                book   = rec.get("_book_id") or "?"
                by_domain[domain][bucket] += 1
                by_book[book][bucket]     += 1
                label_distribution[
                    rec.get("_triage_label") or rec.get("triage_label") or "(none)"
                ] += 1

                # Propagate LLM reason / confidence onto the output row
                # for downstream auditing.
                idx = rec.get("_rec_idx")
                if isinstance(idx, int) and idx in llm_record_by_idx:
                    llm_extra = llm_record_by_idx[idx]
                    rec.setdefault("llm_label",      llm_extra.get("llm_label"))
                    rec.setdefault("llm_confidence", llm_extra.get("llm_confidence"))
                    rec.setdefault("llm_reason",     llm_extra.get("llm_reason"))
                    if bucket != "review":
                        llm_merge_count += 1

                if bucket == "noise":
                    # Per dispatch: don't write noise; just count.
                    pass
                elif bucket == "adjacent":
                    sub = adjacent_subtype(rec)
                    adjacent_subtypes[sub] += 1
                    out = dict(rec)
                    out.setdefault("triage_adjacent_subtype", sub)
                    fh[bucket].write(json.dumps(out, ensure_ascii=False) + "\n")
                else:
                    fh[bucket].write(json.dumps(rec, ensure_ascii=False) + "\n")

                n += 1
                if args.limit is not None and n >= args.limit:
                    break
    finally:
        for f in fh.values():
            f.close()

    # ── Stats ───────────────────────────────────────────────────────────────
    pct = lambda c: round(100.0 * c / n, 2) if n else 0.0

    bucket_summary = {
        b: {"count": counts.get(b, 0), "pct": pct(counts.get(b, 0))}
        for b in ("clean", "l2a", "l1", "adjacent", "review", "noise")
    }

    domain_summary: dict[str, dict] = {}
    for d, sub in sorted(by_domain.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(sub.values())
        domain_summary[d] = {
            "total":           total,
            "clean":           sub.get("clean", 0),
            "l2a":             sub.get("l2a", 0),
            "l1":              sub.get("l1", 0),
            "adjacent":        sub.get("adjacent", 0),
            "review":          sub.get("review", 0),
            "noise":           sub.get("noise", 0),
            "clean_pct":       round(100.0 * sub.get("clean", 0) / total, 2) if total else 0.0,
        }

    # Top 10 most-polluted books = lowest clean_pct (only count books with >50 records).
    book_rows = []
    for book, sub in by_book.items():
        total = sum(sub.values())
        if total < 50:
            continue
        clean = sub.get("clean", 0)
        book_rows.append({
            "book":           book,
            "total":          total,
            "clean":          clean,
            "clean_pct":      round(100.0 * clean / total, 2) if total else 0.0,
            "l2a":            sub.get("l2a", 0),
            "l1":             sub.get("l1", 0),
            "adjacent":       sub.get("adjacent", 0),
            "review":         sub.get("review", 0),
            "non_l0_pct":     round(100.0 * (total - clean) / total, 2) if total else 0.0,
        })
    top_polluted = sorted(book_rows, key=lambda r: -r["non_l0_pct"])[:10]

    stats = {
        "_meta": {
            "task":              "P1 L0 cleanup",
            "date":              time.strftime("%Y-%m-%d", time.gmtime()),
            "input":             str(args.input),
            "total_in":          n,
            "limit":             args.limit,
            "llm_triage_merged": llm_merge_count,
            "llm_triage_size":   len(llm_label_by_idx),
        },
        "buckets":             bucket_summary,
        "by_domain":           domain_summary,
        "adjacent_subtypes":   dict(adjacent_subtypes),
        "label_distribution":  dict(label_distribution.most_common()),
        "top_10_polluted_books": top_polluted,
    }

    OUT_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    # Stdout summary
    print(f"\n── L0 Cleanup ──")
    print(f"  input:   {args.input}  ({n} records)")
    print(f"\n  bucket counts:")
    for b, info in bucket_summary.items():
        print(f"    {b:<12} {info['count']:>6}  ({info['pct']:>5.2f}%)")
    print(f"\n  adjacent subtypes:")
    for s, c in adjacent_subtypes.most_common():
        print(f"    {s:<20} {c}")
    print(f"\n  outputs:")
    for path in (OUT_CLEAN, OUT_L2A, OUT_L1, OUT_ADJACENT, OUT_REVIEW):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                line_n = sum(1 for _ in f)
            print(f"    {path.name:<35} {line_n:>6}")
    print(f"\n  stats:    {OUT_STATS}")
    print(f"\n  Top 10 polluted books (non-L0 pct desc):")
    for r in top_polluted:
        print(f"    {r['book']:<32} total={r['total']:>5}  "
              f"non_l0_pct={r['non_l0_pct']:>5.1f}%  "
              f"l2a={r['l2a']:>4}  l1={r['l1']:>3}  adj={r['adjacent']:>3}  "
              f"rev={r['review']:>4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
