#!/usr/bin/env python3
"""
scripts/phn_seed_input.py
Build Phase-1 Phenomenon seed input:
  - top-10 high-frequency L0 statements per domain (17 domains)
  - full list of 28 Mother Formulas

Sources:
  - output/{book}/stage4/stage4_dedup.jsonl      (preferred — intra-book deduped)
  - output/{book}/stage4/l0_principles_open.jsonl (fallback when dedup missing)

Output:
  output/phase1/phn_seed_input.json

Ranking per domain:
  1. Group by a normalised (stripped, lowercase) key derived from
     causal_chain_text (if non-empty) else scientific_statement.
  2. Sort by (frequency desc, mean_confidence desc, statement length desc).
  3. Keep top 10.
  For each kept item we record:
     {statement, normalised_key, frequency, mean_confidence, book_sources,
      causal_chain_text, proposition_type, domain, sample_source_chunk_id}
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT   = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "output"
MF_YAML     = REPO_ROOT / "config" / "mother_formulas.yaml"
OUT_JSON    = OUTPUT_ROOT / "phase1" / "phn_seed_input.json"
TOP_N       = 10

L0_DOMAINS = [
    "protein_science", "carbohydrate", "lipid_science", "fermentation",
    "food_safety", "water_activity", "enzyme", "color_pigment",
    "equipment_physics", "maillard_caramelization", "oxidation_reduction",
    "salt_acid_chemistry", "taste_perception", "aroma_volatiles",
    "thermal_dynamics", "mass_transfer", "texture_rheology",
]


def _norm_key(text: str) -> str:
    """Normalise a statement for cross-book frequency matching.

    Rules: strip surrounding whitespace, collapse internal whitespace,
    lowercase (no-op for CJK), trim common trailing punctuation.
    """
    if not text:
        return ""
    s = text.strip()
    s = re.sub(r"\s+", " ", s)
    s = s.lower()
    s = s.rstrip(".,。，;；:：!！?？")
    return s


def _source_file_for(book_dir: Path) -> Path | None:
    """Prefer stage4_dedup over l0_principles_open."""
    dedup = book_dir / "stage4" / "stage4_dedup.jsonl"
    if dedup.exists():
        return dedup
    opn = book_dir / "stage4" / "l0_principles_open.jsonl"
    if opn.exists():
        return opn
    return None


def _iter_l0_records(path: Path, book_id: str):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            rec["_book_id"] = book_id
            yield rec


def _ranking_key(rec: dict) -> tuple[str, str]:
    """Return (statement_for_display, normalised_key)."""
    causal = (rec.get("causal_chain_text") or "").strip()
    stmt   = (rec.get("scientific_statement") or "").strip()
    if causal:
        return causal, _norm_key(causal)
    return stmt, _norm_key(stmt)


def collect_by_domain() -> tuple[dict[str, list[dict]], dict[str, Any]]:
    """Walk all book dirs, bucket records by domain, dedup per normalised key.

    Returns:
        (domains_top, meta) where domains_top maps domain → top10 rows and
        meta reports how many books/records fed into the computation.
    """
    # domain → norm_key → aggregate
    buckets: dict[str, dict[str, dict]] = defaultdict(dict)
    files_read = 0
    records_read = 0

    for book_dir in sorted(OUTPUT_ROOT.iterdir()):
        if not book_dir.is_dir():
            continue
        src = _source_file_for(book_dir)
        if not src:
            continue
        files_read += 1
        book_id = book_dir.name
        for rec in _iter_l0_records(src, book_id):
            records_read += 1
            domain = rec.get("domain") or "other"
            if domain not in L0_DOMAINS and domain != "other":
                # keep unknown domains under "other" so nothing is silently lost
                domain = "other"
            stmt, key = _ranking_key(rec)
            if not key:
                continue
            bucket = buckets[domain]
            agg = bucket.get(key)
            if agg is None:
                agg = {
                    "statement":          stmt,
                    "normalised_key":     key,
                    "frequency":          0,
                    "confidences":        [],
                    "book_sources":       set(),
                    "causal_chain_text":  rec.get("causal_chain_text") or "",
                    "causal_chain_steps": rec.get("causal_chain_steps") or [],
                    "proposition_type":   rec.get("proposition_type") or "",
                    "domain":             domain,
                    "sample_source_chunk_id": rec.get("source_chunk_id") or "",
                }
                bucket[key] = agg
            agg["frequency"] += 1
            conf = rec.get("confidence")
            if isinstance(conf, (int, float)):
                agg["confidences"].append(float(conf))
            agg["book_sources"].add(book_id)

    # Rank and pick top-N per domain
    domains_top: dict[str, list[dict]] = {}
    for domain in L0_DOMAINS:
        rows = list(buckets.get(domain, {}).values())
        for r in rows:
            confs = r.pop("confidences")
            r["mean_confidence"] = round(sum(confs) / len(confs), 3) if confs else None
            r["book_sources"] = sorted(r["book_sources"])
            r["source_book_count"] = len(r["book_sources"])
        rows.sort(key=lambda r: (
            -r["frequency"],
            -(r["mean_confidence"] or 0.0),
            -len(r["statement"]),
        ))
        domains_top[domain] = rows[:TOP_N]

    # Attach "other" bucket for visibility
    other_rows = list(buckets.get("other", {}).values())
    for r in other_rows:
        confs = r.pop("confidences", [])
        r["mean_confidence"] = round(sum(confs) / len(confs), 3) if confs else None
        r["book_sources"] = sorted(r["book_sources"])
        r["source_book_count"] = len(r["book_sources"])
    other_rows.sort(key=lambda r: (-r["frequency"], -(r["mean_confidence"] or 0.0)))

    meta = {
        "files_read":               files_read,
        "records_read":             records_read,
        "unique_keys_total":        sum(len(v) for v in buckets.values()),
        "domains_with_data":        sum(1 for d in L0_DOMAINS if buckets.get(d)),
        "other_bucket_unique_keys": len(buckets.get("other", {})),
        "other_top20":              other_rows[:20],
    }
    return domains_top, meta


# ── Mother Formulas ─────────────────────────────────────────────────────────

def load_mother_formulas() -> list[dict]:
    with open(MF_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        raise RuntimeError(f"{MF_YAML}: expected list")
    kept_fields = (
        "id", "canonical_name", "display_name", "domain",
        "equation_latex", "sympy_expression",
        "output_symbol", "runtime_variables", "one_of_inputs", "constants",
        "units", "applicable_range", "source_books", "notes",
    )
    return [{k: mf.get(k) for k in kept_fields if k in mf} for mf in data]


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    domains_top, meta = collect_by_domain()
    mfs = load_mother_formulas()
    if len(mfs) != 28:
        print(f"WARN: expected 28 Mother Formulas, got {len(mfs)}", file=sys.stderr)

    payload = {
        "_meta": {
            "source_files_read":  meta["files_read"],
            "total_records_read": meta["records_read"],
            "unique_keys_total":  meta["unique_keys_total"],
            "top_n_per_domain":   TOP_N,
            "l0_domain_count":    len(L0_DOMAINS),
            "mother_formula_count": len(mfs),
            "other_bucket_unique_keys": meta["other_bucket_unique_keys"],
        },
        "domains":         domains_top,
        "other_top20":     meta["other_top20"],
        "mother_formulas": mfs,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    tmp.replace(OUT_JSON)

    # Summary to stdout
    print(f"\n── Phenomenon Seed Input ──")
    print(f"  files read:         {meta['files_read']}")
    print(f"  records read:       {meta['records_read']}")
    print(f"  unique keys total:  {meta['unique_keys_total']}")
    print(f"  domains with data:  {meta['domains_with_data']}/{len(L0_DOMAINS)}")
    print(f"  'other' bucket:     {meta['other_bucket_unique_keys']} unique keys")
    print(f"  mother formulas:    {len(mfs)}")
    print(f"  output:             {OUT_JSON}")
    print(f"\n  Top per domain (freq of #1):")
    for d in L0_DOMAINS:
        rows = domains_top.get(d, [])
        if rows:
            r = rows[0]
            print(f"    {d:<30} n={len(rows)} | top freq={r['frequency']} "
                  f"books={r['source_book_count']} | {r['statement'][:60]}...")
        else:
            print(f"    {d:<30} (no data)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
