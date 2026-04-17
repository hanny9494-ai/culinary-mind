#!/usr/bin/env python3
"""
pipeline/skills/secondary_filter.py
Zero-cost regex pre-filter for Skill A pages (before calling Opus).

Signal router uses recall-first strategy → 30-40% false positives on signal A.
This filter removes FPs before they reach Opus ($0.12/page).

Filter logic (in evaluation order):
  1. Veto-exempt check: if Rule 4 (MF hints) or Rule 5 (high confidence) → skip Veto, keep
  2. Veto rules (if triggered → filter regardless of Rule 1-3):
       Veto-2: figure caption page (no data table)
       Veto-3: references / bibliography page
       Veto-4: index page (word, page# entries)
  3. Positive rules (any one match = keep):
       Rule 1: numeric + unit pattern (°C, %, kJ, Pa, ...)
       Rule 2: formula / equation symbols
       Rule 3: table pattern (3+ tabs OR 6+ pipe chars)

Expected Veto effect: filter 15-30% of previously-passing FP pages (figure
captions, reference lists, index pages) with near-zero FN risk.

Usage:
    python secondary_filter.py --book-id mc_vol1 --dry-run
    python secondary_filter.py --book-id mc_vol1
    python secondary_filter.py --page-text "Temperature: 60°C for 30 min"

Integration with run_skill.py:
    Skill A pages are passed through filter_skill_a() before calling Opus.
    Filtered-out pages receive a placeholder in results.jsonl with
    _filtered=True so they aren't retried.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "output"

# ── Compiled regex patterns (compiled once at module load) ────────────────────

# Rule 1: numeric value + physical/chemical unit
_UNIT_PATTERN = re.compile(
    r"""
    \d+(?:\.\d+)?           # number (int or decimal)
    \s*                     # optional whitespace
    (?:
        °[CFK]              # temperature
        | %                 # percentage
        | g/mol             # molar mass
        | kJ(?:/mol)?       # energy
        | J/g               # specific energy
        | W/(?:m|kg)        # power density
        | Pa                # pressure
        | kPa|MPa
        | pH                # pH
        | ppm               # concentration
        | mg/(?:kg|L|g|mL)  # concentration
        | mM|μM|nM          # molarity
        | m²|m³             # area/volume
        | min|hr|h\b        # time
        | mm|cm             # length (short to avoid false match)
        | rpm               # rotation
        | kcal              # energy
        | atm               # pressure
        | cP|mPa·s          # viscosity
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Rule 2: formula/equation symbols
_FORMULA_PATTERN = re.compile(
    r"""
    [=∝±×÷√∫∑Σ∏∂∇→⇌≤≥≠≈∞∈∉]   # mathematical operators
    | \\frac | \\sum | \\int | \\partial | \\Delta | \\alpha | \\beta  # LaTeX
    | \b[A-Z]_?\{?\d+\}?\s*=\s*\d  # variable = number pattern (e.g. k=3.2)
    | \bEa\b | \bk_[a-z] | \bT_[a-z]  # common scientific variable names
    """,
    re.VERBOSE,
)

# Rule 3: table-like structure (tabs or pipe separators)
_TABLE_TAB_PATTERN = re.compile(r"\t")
_TABLE_PIPE_PATTERN = re.compile(r"\|")

# Rule 4: MF-prefixed candidates
_MF_PREFIX_PATTERN = re.compile(r"MF-[TKMRC]\d{2}")

# ── Veto patterns ─────────────────────────────────────────────────────────────

# Veto-2: figure/chart caption page — line starting with "Fig." or "Figure N"
# Indicates an illustration page with a caption but no data table
_VETO2_FIGURE = re.compile(r"^(Fig\.?|Figure)\s+\d+", re.MULTILINE | re.IGNORECASE)

# Veto-3: references / bibliography section
# Header keyword + 3+ author-year citations like (1999) or (Smith, 2003)
_VETO3_HEADER = re.compile(r"(References|Bibliography|Literature Cited)", re.IGNORECASE)
_VETO3_CITATION = re.compile(r"\(\d{4}\)")          # (YYYY) style
_VETO3_CITATION2 = re.compile(                       # Author, YYYY. style
    r"[A-Z][a-z]+,\s+[A-Z]\..*?\d{4}[.;,]",
    re.DOTALL,
)

# Veto-4: book index — lines of format "Term or phrase, page_number(s)"
_VETO4_INDEX_LINE = re.compile(r"[A-Za-z][A-Za-z\s\-()]+,\s*\d{1,4}(?:[-–]\d{1,4})?")


def _check_veto(page_text: str, tab_count: int, pipe_count: int) -> tuple[bool, str]:
    """
    Check all Veto rules. Returns (vetoed: bool, veto_reason: str).
    Call this only for pages that are NOT veto-exempt (no MF hints, low confidence).
    """
    lines = page_text.splitlines()

    # Veto-2: figure caption page
    # Condition: page has a "Fig. N" / "Figure N" line AND no real data table
    if _VETO2_FIGURE.search(page_text) and tab_count < 3 and pipe_count < 4:
        return True, "veto2_figure_caption"

    # Veto-3: references / bibliography
    # Condition: header keyword present AND 3+ author-year citations
    if _VETO3_HEADER.search(page_text):
        year_hits = len(_VETO3_CITATION.findall(page_text))
        if year_hits >= 3:
            return True, "veto3_references"

    # Veto-4: index page
    # Condition: 10+ lines matching "word(s), page-number" index-entry format
    index_matches = sum(
        1 for line in lines
        if _VETO4_INDEX_LINE.match(line.strip())
    )
    if index_matches >= 10:
        return True, "veto4_index"

    return False, ""


# ── Core filter function ──────────────────────────────────────────────────────

def filter_skill_a(page_text: str, signal: dict) -> tuple[bool, str]:
    """
    Decide whether a Skill-A-signaled page is worth sending to Opus.

    Evaluation order:
      1. Veto-exempt: Rule 4 (MF hints) or Rule 5 (high confidence) → keep immediately
      2. Veto rules (2/3/4) → filter if triggered
      3. Positive rules 1-3 → keep if any matches

    Args:
        page_text: raw page text from pages.json
        signal:    signal dict from signals.json (contains hints, confidence, etc.)

    Returns:
        (keep: bool, reason: str)
        keep=True  → send to Opus
        keep=False → skip (FP filtered)
    """
    # ── Veto-exempt: Rule 4 (MF hints from router) ───────────────────────────
    hints_a = signal.get("hints", {}).get("A", {})
    if isinstance(hints_a, dict):
        mf_cands = hints_a.get("mf_candidates", [])
        if mf_cands:
            return True, "rule4_mf_hints"
        if hints_a.get("has_table") or hints_a.get("has_equation"):
            return True, "rule4_router_flags"

    # ── Veto-exempt: Rule 5 (high confidence from router) ────────────────────
    confidence = signal.get("confidence", 0)
    if confidence >= 0.85:
        return True, "rule5_high_confidence"

    # ── Veto rules (only for pages that aren't veto-exempt) ──────────────────
    tab_count  = len(_TABLE_TAB_PATTERN.findall(page_text))
    pipe_count = len(_TABLE_PIPE_PATTERN.findall(page_text))
    vetoed, veto_reason = _check_veto(page_text, tab_count, pipe_count)
    if vetoed:
        return False, veto_reason

    # ── Positive rules 1-3 ───────────────────────────────────────────────────
    if _UNIT_PATTERN.search(page_text):
        return True, "rule1_numeric_unit"

    if _FORMULA_PATTERN.search(page_text):
        return True, "rule2_formula_symbol"

    if tab_count >= 3 or pipe_count >= 6:
        return True, "rule3_table_pattern"

    return False, "filtered_no_pattern"


def explain_filter(page_text: str, signal: dict) -> dict[str, Any]:
    """
    Detailed breakdown of filter decision for a single page (debugging).
    """
    hints_a = signal.get("hints", {}).get("A", {})
    mf_cands = hints_a.get("mf_candidates", []) if isinstance(hints_a, dict) else []

    unit_matches = _UNIT_PATTERN.findall(page_text[:500])
    formula_matches = _FORMULA_PATTERN.findall(page_text[:500])
    tab_count  = len(_TABLE_TAB_PATTERN.findall(page_text))
    pipe_count = len(_TABLE_PIPE_PATTERN.findall(page_text))

    vetoed, veto_reason = _check_veto(page_text, tab_count, pipe_count)
    keep, reason = filter_skill_a(page_text, signal)

    return {
        "keep": keep,
        "reason": reason,
        "confidence": signal.get("confidence", 0),
        "rule1_unit_matches": unit_matches[:5],
        "rule2_formula_matches": formula_matches[:5],
        "rule3_tab_count": tab_count,
        "rule3_pipe_count": pipe_count,
        "rule4_mf_candidates": mf_cands,
        "rule4_has_table": hints_a.get("has_table") if isinstance(hints_a, dict) else False,
        "rule4_has_equation": hints_a.get("has_equation") if isinstance(hints_a, dict) else False,
        "veto_triggered": vetoed,
        "veto_reason": veto_reason,
        "veto2_figure_match": bool(_VETO2_FIGURE.search(page_text)),
        "veto3_ref_header": bool(_VETO3_HEADER.search(page_text)),
        "veto3_citation_count": len(_VETO3_CITATION.findall(page_text)),
        "veto4_index_lines": sum(
            1 for line in page_text.splitlines()
            if _VETO4_INDEX_LINE.match(line.strip())
        ),
    }


# ── Skill D secondary filter ──────────────────────────────────────────────────

# Compiled once at module load
_ZH_AESTHETIC_PATTERN = re.compile(
    r'(嫩滑|爽脆|入口即化|镬气|断生|过冷河|飞水|走油|'
    r'口感|质感|嫩|脆|滑|鲜|香|糯|弹|酥|'
    r'火候|老|生|熟|透|焦|糊|干|湿)'
)

_EN_AESTHETIC_PATTERN = re.compile(
    r'(texture|mouthfeel|crisp|tender|juicy|umami|aroma|'
    r'silky|creamy|crunchy|chewy|flaky|succulent|'
    r'sensation|palate|flavor profile)',
    re.IGNORECASE,
)


def secondary_filter_d(page_text: str, language: str = "zh") -> bool:
    """
    Zero-cost regex pre-filter for Skill D pages.

    Returns True (keep) if the page likely contains FlavorTarget or Glossary content.
    Returns False (skip) if no aesthetic/sensory terms are found.
    """
    if language == "zh":
        return bool(_ZH_AESTHETIC_PATTERN.search(page_text))
    else:
        return bool(_EN_AESTHETIC_PATTERN.search(page_text))


def explain_filter_d(page_text: str, language: str = "zh") -> dict[str, Any]:
    """Detailed breakdown of Skill D filter decision for debugging."""
    keep = secondary_filter_d(page_text, language)
    if language == "zh":
        matches = _ZH_AESTHETIC_PATTERN.findall(page_text[:500])
    else:
        matches = _EN_AESTHETIC_PATTERN.findall(page_text[:500])
    return {
        "keep": keep,
        "language": language,
        "reason": "rule_zh_aesthetic" if (keep and language == "zh")
                   else "rule_en_aesthetic" if (keep and language != "zh")
                   else "filtered_no_aesthetic_term",
        "matches": matches[:10],
    }


# ── Batch analysis ─────────────────────────────────────────────────────────────

def analyze_book(book_id: str) -> dict[str, Any]:
    """
    Analyze all Skill-A-signaled pages in a book and return filter statistics.
    Does NOT call any LLM — pure analysis.
    """
    pages_path   = OUTPUT_ROOT / book_id / "pages.json"
    signals_path = OUTPUT_ROOT / book_id / "signals.json"

    if not pages_path.exists():
        return {"error": f"pages.json not found for {book_id}"}
    if not signals_path.exists():
        return {"error": f"signals.json not found for {book_id}"}

    pages   = json.loads(pages_path.read_text())
    signals = json.loads(signals_path.read_text())

    pages_map = {p["page"]: p.get("text", "") for p in pages}

    # Pages with A signal set
    a_signal_pages = [
        s for s in signals
        if (s.get("signals") or {}).get("A") and not s.get("skip_reason")
    ]

    total_pages = len(pages)
    a_count     = len(a_signal_pages)
    kept        = 0
    filtered    = 0
    reason_counts: dict[str, int] = {}

    for sig in a_signal_pages:
        page_num = sig["page"]
        text     = pages_map.get(page_num, "")
        keep, reason = filter_skill_a(text, sig)
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if keep:
            kept += 1
        else:
            filtered += 1

    # Break out veto counts separately
    veto_counts = {k: v for k, v in reason_counts.items() if k.startswith("veto")}
    filter_rate = filtered / a_count * 100 if a_count > 0 else 0

    return {
        "book_id":                  book_id,
        "total_pages":              total_pages,
        "a_signal_pages":           a_count,
        "kept_for_opus":            kept,
        "filtered_out":             filtered,
        "filter_rate_pct":          round(filter_rate, 1),
        "estimated_opus_cost_usd":  round(kept * 0.12, 2),
        "estimated_cost_saved_usd": round(filtered * 0.12, 2),
        "reason_breakdown":         reason_counts,
        "veto_breakdown":           veto_counts,
    }

# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Skill A secondary filter — zero-cost regex pre-filter before Opus")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--book-id", help="Analyze all Skill A pages for a book")
    grp.add_argument("--page-text", help="Test filter on a single text string")
    p.add_argument("--dry-run", action="store_true",
                   help="Analyze only — do not write anything (default when using --book-id)")
    p.add_argument("--verbose", action="store_true",
                   help="Show per-page details")
    p.add_argument("--signal-json", default="{}", help="Signal JSON for --page-text mode")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.page_text:
        try:
            signal = json.loads(args.signal_json)
        except Exception:
            signal = {}
        detail = explain_filter(args.page_text, signal)
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        status = "✅ KEEP" if detail["keep"] else "❌ FILTER"
        print(f"\n{status} (reason: {detail['reason']})")
        return

    if not args.book_id:
        print("ERROR: Provide --book-id or --page-text", file=sys.stderr)
        sys.exit(1)

    stats = analyze_book(args.book_id)
    if "error" in stats:
        print(f"ERROR: {stats['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"\n── Secondary Filter Analysis: {args.book_id} ──")
    print(f"  Total pages:          {stats['total_pages']}")
    print(f"  A-signal pages:       {stats['a_signal_pages']}")
    print(f"  Kept for Opus:        {stats['kept_for_opus']}")
    print(f"  Filtered out:         {stats['filtered_out']}")
    print(f"  Filter rate:          {stats['filter_rate_pct']:.1f}%")
    print(f"  Est. Opus cost:       ${stats['estimated_opus_cost_usd']:.2f}")
    print(f"  Est. cost saved:      ${stats['estimated_cost_saved_usd']:.2f}")
    print(f"\n  Reason breakdown:")
    for reason, count in sorted(stats["reason_breakdown"].items(), key=lambda x: -x[1]):
        pct = count / stats["a_signal_pages"] * 100 if stats["a_signal_pages"] else 0
        print(f"    {reason:<30} {count:>5} ({pct:.0f}%)")

    if stats["veto_breakdown"]:
        print(f"\n  Veto breakdown:")
        for reason, count in sorted(stats["veto_breakdown"].items(), key=lambda x: -x[1]):
            print(f"    {reason:<30} {count:>5}")

    if args.verbose:
        pages   = json.loads((OUTPUT_ROOT / args.book_id / "pages.json").read_text())
        signals = json.loads((OUTPUT_ROOT / args.book_id / "signals.json").read_text())
        pages_map = {p["page"]: p.get("text", "") for p in pages}
        a_sigs = [s for s in signals if (s.get("signals") or {}).get("A") and not s.get("skip_reason")]
        print(f"\n  Filtered pages detail (showing filtered only):")
        for sig in a_sigs:
            text = pages_map.get(sig["page"], "")
            keep, reason = filter_skill_a(text, sig)
            if not keep:
                print(f"    p{sig['page']:04d} [{reason}]: {text[:80].replace(chr(10),' ')!r}")


if __name__ == "__main__":
    main()
