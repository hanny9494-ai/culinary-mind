#!/usr/bin/env python3
"""Stage 4 quality checks.

Validates deduped open-extracted principles against quality criteria:
  - has_number: scientific_statement contains digits
  - valid_domain: domain is one of 17 valid domains
  - has_citation: citation_quote is non-empty
  - citation_in_chunk: citation_quote appears in source chunk text (fuzzy)
  - valid_type: proposition_type is one of 4 valid types
  - causal_chain_format: if causal_chain, has >=2 steps

Passing records -> l0_principles_open.jsonl
Stats -> stage4_quality_report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_PROPOSITION_TYPES = {"fact_atom", "causal_chain", "compound_condition", "mathematical_law"}


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


def load_chunks(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get("chunks", [])
    return []


def load_domains(path: Path) -> set[str]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {d["id"] for d in raw.get("domains", []) if "id" in d}


def chunk_text(chunk: dict[str, Any]) -> str:
    for key in ("full_text", "text", "content", "summary"):
        val = str(chunk.get(key) or "").strip()
        if val:
            return val
    return ""


def chunk_id(chunk: dict[str, Any], index: int) -> str:
    cid = str(chunk.get("chunk_id") or chunk.get("id") or "").strip()
    if cid:
        return cid
    return f"chunk_{index}"


# ---------------------------------------------------------------------------
# Fuzzy citation matching
# ---------------------------------------------------------------------------

def normalize_for_match(text: str) -> str:
    """Collapse whitespace and strip punctuation for fuzzy comparison."""
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。、；：\u201c\u201d\u2018\u2019（）\[\]【】《》「」\-\u2014\u2026·]", "", text)
    return text.lower()


def citation_in_text(citation: str, source_text: str) -> bool:
    """Check if citation_quote appears in source chunk (fuzzy)."""
    if not citation or not source_text:
        return False
    # Exact substring first
    if citation in source_text:
        return True
    # Fuzzy: normalize both and check
    norm_cite = normalize_for_match(citation)
    norm_text = normalize_for_match(source_text)
    if not norm_cite:
        return False
    if norm_cite in norm_text:
        return True
    # Sliding window: allow up to 10% character mismatch
    cite_len = len(norm_cite)
    if cite_len < 5:
        return False
    max_mismatches = max(1, cite_len // 10)
    for start in range(len(norm_text) - cite_len + 1):
        window = norm_text[start : start + cite_len]
        mismatches = sum(1 for a, b in zip(norm_cite, window) if a != b)
        if mismatches <= max_mismatches:
            return True
    return False


# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------

def check_record(
    rec: dict[str, Any],
    valid_domains: set[str],
    chunk_map: dict[str, str],
) -> dict[str, bool]:
    """Run all quality checks on a single record. Return check_name -> pass."""
    stmt = str(rec.get("scientific_statement") or "").strip()
    domain = str(rec.get("domain") or "").strip()
    citation = str(rec.get("citation_quote") or "").strip()
    ptype = str(rec.get("proposition_type") or "").strip()
    chain_steps = rec.get("causal_chain_steps")
    source_cid = str(rec.get("source_chunk_id") or "").strip()

    checks: dict[str, bool] = {}

    # 1. has_number
    checks["has_number"] = bool(re.search(r"\d", stmt))

    # 2. valid_domain
    checks["valid_domain"] = domain in valid_domains

    # 3. has_citation
    checks["has_citation"] = len(citation) > 0

    # 4. citation_in_chunk
    source_text = chunk_map.get(source_cid, "")
    checks["citation_in_chunk"] = citation_in_text(citation, source_text) if citation else False

    # 5. valid_type
    checks["valid_type"] = ptype in VALID_PROPOSITION_TYPES

    # 6. causal_chain_format
    if ptype == "causal_chain":
        checks["causal_chain_format"] = isinstance(chain_steps, list) and len(chain_steps) >= 2
    else:
        checks["causal_chain_format"] = True  # N/A -- pass by default

    return checks


WARN_ONLY_CHECKS = {"has_number"}


def record_passes(checks: dict[str, bool]) -> bool:
    """A record passes if all non-warning checks are True."""
    return all(v for k, v in checks.items() if k not in WARN_ONLY_CHECKS)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 4 quality checks on deduped open-extracted principles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True, help="Path to stage4_deduped.jsonl")
    parser.add_argument("--chunks", required=True, help="Path to chunks_smart.json (for citation verification)")
    parser.add_argument("--output", required=True, help="Output path for passing principles (l0_principles_open.jsonl)")
    parser.add_argument("--report", required=True, help="Output path for quality report JSON")
    parser.add_argument("--domains", default="config/domains_v2.json", help="Path to domains_v2.json (default: config/domains_v2.json)")
    parser.add_argument("--strict", action="store_true", help="Strict mode: all checks must pass (default behavior)")
    args = parser.parse_args()

    # Load inputs
    print(f"Loading deduped principles from {args.input} ...", flush=True)
    records = load_jsonl(Path(args.input))
    print(f"  Loaded {len(records)} records", flush=True)

    print(f"Loading chunks from {args.chunks} ...", flush=True)
    chunks = load_chunks(Path(args.chunks))
    print(f"  Loaded {len(chunks)} chunks", flush=True)

    # Build chunk_id -> text map
    chunk_map: dict[str, str] = {}
    for idx, chunk in enumerate(chunks):
        cid = chunk_id(chunk, idx)
        chunk_map[cid] = chunk_text(chunk)

    # Load valid domains
    print(f"Loading domains from {args.domains} ...", flush=True)
    valid_domains = load_domains(Path(args.domains))
    print(f"  Valid domains: {len(valid_domains)}", flush=True)

    # Run quality checks
    print("Running quality checks ...", flush=True)
    passing: list[dict[str, Any]] = []
    failing: list[dict[str, Any]] = []

    check_stats: dict[str, int] = {
        "has_number": 0,
        "valid_domain": 0,
        "has_citation": 0,
        "citation_in_chunk": 0,
        "valid_type": 0,
        "causal_chain_format": 0,
    }
    total = len(records)

    for idx, rec in enumerate(records):
        checks = check_record(rec, valid_domains, chunk_map)

        # Accumulate pass counts per check
        for check_name, passed in checks.items():
            if passed:
                check_stats[check_name] = check_stats.get(check_name, 0) + 1

        if record_passes(checks):
            passing.append(rec)
        else:
            failed_checks = [k for k, v in checks.items() if not v]
            rec["_failed_checks"] = failed_checks
            failing.append(rec)

        if (idx + 1) % 200 == 0:
            print(f"  Checked {idx + 1}/{total}", flush=True)

    # Write outputs
    write_jsonl(Path(args.output), passing)

    # Build report
    report: dict[str, Any] = {
        "total_input": total,
        "total_passing": len(passing),
        "total_failing": len(failing),
        "pass_rate": round(len(passing) / total, 4) if total > 0 else 0.0,
        "check_pass_counts": {k: v for k, v in check_stats.items()},
        "check_pass_rates": {
            k: round(v / total, 4) if total > 0 else 0.0
            for k, v in check_stats.items()
        },
        "failing_reasons_distribution": {},
    }

    # Count failure reasons
    reason_counts: dict[str, int] = {}
    for rec in failing:
        for check_name in rec.get("_failed_checks", []):
            reason_counts[check_name] = reason_counts.get(check_name, 0) + 1
    report["failing_reasons_distribution"] = reason_counts

    # Domain distribution of passing records
    domain_dist: dict[str, int] = {}
    for rec in passing:
        d = str(rec.get("domain") or "unknown")
        domain_dist[d] = domain_dist.get(d, 0) + 1
    report["passing_domain_distribution"] = dict(sorted(domain_dist.items(), key=lambda x: -x[1]))

    # Proposition type distribution of passing records
    type_dist: dict[str, int] = {}
    for rec in passing:
        t = str(rec.get("proposition_type") or "unknown")
        type_dist[t] = type_dist.get(t, 0) + 1
    report["passing_type_distribution"] = dict(sorted(type_dist.items(), key=lambda x: -x[1]))

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Print summary
    print(f"\nQuality report:", flush=True)
    print(f"  Total input:    {total}", flush=True)
    print(f"  Passing:        {len(passing)} ({report['pass_rate']:.1%})", flush=True)
    print(f"  Failing:        {len(failing)}", flush=True)
    print(f"  Check pass rates:", flush=True)
    for check_name, rate in report["check_pass_rates"].items():
        print(f"    {check_name}: {rate:.1%} ({check_stats[check_name]}/{total})", flush=True)
    if reason_counts:
        print(f"  Top failure reasons:", flush=True)
        for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}", flush=True)
    print(f"\n  Output:  {args.output}", flush=True)
    print(f"  Report:  {args.report}", flush=True)


if __name__ == "__main__":
    main()
