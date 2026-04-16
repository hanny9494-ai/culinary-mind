#!/usr/bin/env python3
"""
pipeline/skills/gates.py
Gate system — 5 automated quality gates for the extraction pipeline.

G0: gate_preflight   — before OCR: PDF exists, disk space, not already done
G1: gate_ocr_qc      — after OCR: blank page rate, avg chars per page
G2: gate_signal_qc   — after Signal: A% / skip% anomaly detection
G3: gate_pilot       — before full Skill: trial-run N pages, measure yield
G4: gate_final_qc    — after full Skill: schema validation, error rate

Gate results saved to output/{book_id}/gates/{gate_name}.json.

Usage:
    python gates.py --gate ocr_qc   --book-id mc_vol1
    python gates.py --gate signal_qc --book-id mc_vol1
    python gates.py --gate pilot    --book-id mc_vol1 --skill a --pages 5
    python gates.py --gate final_qc --book-id mc_vol1 --skill a
    python gates.py --gate preflight --book-id mc_vol1 \
        --books-yaml config/books.yaml
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "output"

# Proxy bypass (inherited by imported modules too)
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(_k, None)
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _save_gate(book_id: str, gate_name: str, result: dict) -> Path:
    """Write gate result JSON to output/{book_id}/gates/{gate_name}.json."""
    gates_dir = OUTPUT_ROOT / book_id / "gates"
    gates_dir.mkdir(parents=True, exist_ok=True)
    out = gates_dir / f"{gate_name}.json"
    result["_ts"] = _ts()
    result["_gate"] = gate_name
    result["_book_id"] = book_id
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return out


def _load_pages(book_id: str) -> list[dict]:
    path = OUTPUT_ROOT / book_id / "pages.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _load_signals(book_id: str) -> list[dict]:
    path = OUTPUT_ROOT / book_id / "signals.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _load_results(book_id: str, skill: str) -> list[dict]:
    path = OUTPUT_ROOT / book_id / f"skill_{skill}" / "results.jsonl"
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return records


def _load_book_entry(book_id: str, books_yaml_path: Path | None = None) -> dict | None:
    """Load a single book entry from books.yaml."""
    yaml_path = books_yaml_path or (REPO_ROOT / "config" / "books.yaml")
    try:
        import yaml
        with open(yaml_path) as f:
            books = yaml.safe_load(f)
        if isinstance(books, list):
            return next((b for b in books if b.get("id") == book_id), None)
        return None
    except Exception:
        return None


def _get_free_disk_gb() -> float:
    """Return free disk space in GB for the output directory."""
    total, used, free = shutil.disk_usage(OUTPUT_ROOT)
    return free / (1024 ** 3)

# ── G0: Preflight ─────────────────────────────────────────────────────────────

def gate_preflight(
    book_id: str,
    books_yaml_path: Path | str | None = None,
    min_disk_gb: float = 5.0,
) -> dict:
    """
    G0 Preflight gate — run before OCR.

    Checks:
    - source PDF exists (from books.yaml source_path or standard locations)
    - disk space ≥ min_disk_gb GB free
    - ocr_status is not 'done' (avoid unnecessary re-runs)
    - PaddleOCR API reachable (optional, soft check)

    Returns dict with passed/checks/ts.
    """
    yaml_path = Path(books_yaml_path) if books_yaml_path else (REPO_ROOT / "config" / "books.yaml")
    book = _load_book_entry(book_id, yaml_path)

    checks: dict[str, Any] = {}
    notes: list[str] = []

    # Check 1: source PDF exists
    pdf_found = False
    pdf_path_used = None
    if book and book.get("source_path"):
        sp = Path(book["source_path"])
        if sp.exists():
            pdf_found = True
            pdf_path_used = str(sp)
    if not pdf_found:
        # Standard locations
        for candidate in [
            OUTPUT_ROOT / book_id / "source.pdf",
            OUTPUT_ROOT / book_id / f"{book_id}.pdf",
            OUTPUT_ROOT / book_id / "source_converted.pdf",
        ]:
            if candidate.exists():
                pdf_found = True
                pdf_path_used = str(candidate)
                break
    checks["source_pdf_exists"] = pdf_found
    if pdf_path_used:
        checks["source_pdf_path"] = pdf_path_used

    # Check 2: disk space
    free_gb = _get_free_disk_gb()
    checks["free_disk_gb"] = round(free_gb, 1)
    checks["disk_space_ok"] = free_gb >= min_disk_gb
    if free_gb < min_disk_gb:
        notes.append(f"Low disk space: {free_gb:.1f}GB free (need {min_disk_gb}GB)")

    # Check 3: not already done (prevent wasted re-run)
    ocr_status = book.get("ocr_status", "pending") if book else "unknown"
    checks["ocr_status"] = ocr_status
    checks["not_already_done"] = ocr_status not in ("done",)
    if ocr_status == "done":
        notes.append("ocr_status is already 'done' — use --force to re-run")

    # Check 4: PaddleOCR API reachable (soft)
    try:
        import httpx
        resp = httpx.get(
            "https://t1m0ybsdk3d2hcyc.aistudio-app.com/layout-parsing",
            timeout=5, follow_redirects=False,
        )
        checks["paddleocr_api_reachable"] = resp.status_code < 500
    except Exception as e:
        checks["paddleocr_api_reachable"] = False
        notes.append(f"PaddleOCR API unreachable: {e}")

    passed = (
        checks.get("source_pdf_exists", False)
        and checks.get("disk_space_ok", False)
        and checks.get("not_already_done", True)
    )

    result = {"passed": passed, "checks": checks, "notes": notes}
    return result

# ── G1: OCR QC ───────────────────────────────────────────────────────────────

def gate_ocr_qc(book_id: str) -> dict:
    """
    G1 OCR Quality Check — run after OCR, before Signal routing.

    Checks pages.json for:
    - blank page rate < 20% (pages with < 50 chars)
    - average chars per page > 200

    Borderline (needs_review):
    - blank_pct 15-25% OR avg_chars 150-300

    Returns dict with passed/checks/stats/ts.
    """
    pages = _load_pages(book_id)
    if not pages:
        return {
            "passed": False,
            "error": f"pages.json not found or empty for {book_id}",
        }

    total = len(pages)
    blank = sum(1 for p in pages if len(p.get("text", "").strip()) < 50)
    char_counts = [len(p.get("text", "")) for p in pages]
    avg_chars = sum(char_counts) / total
    min_chars = min(char_counts)
    max_chars = max(char_counts)

    blank_pct = blank / total * 100

    stats = {
        "pages_total": total,
        "blank_count": blank,
        "blank_pct": round(blank_pct, 1),
        "avg_chars_per_page": round(avg_chars, 0),
        "min_chars": min_chars,
        "max_chars": max_chars,
    }

    passed = blank_pct < 20.0 and avg_chars > 200.0

    # Borderline — flag for human review but don't hard-fail
    needs_review = (15 < blank_pct < 25) or (150 < avg_chars < 300)

    result = {
        "passed": passed,
        "needs_review": needs_review if not passed else False,
        "stats": stats,
        "thresholds": {"max_blank_pct": 20.0, "min_avg_chars": 200.0},
    }
    return result

# ── G2: Signal QC ────────────────────────────────────────────────────────────

def gate_signal_qc(book_id: str) -> dict:
    """
    G2 Signal Quality Check — run after Signal routing, before Pilot/Skill.

    Checks signals.json for anomalies:
    - A signal > 80%: INFO only (expected for parameter-dense books, not a fail)
    - A signal < 5%: FAIL — router likely missing science content
    - skip_pct > 40%: FAIL — possible OCR quality issue

    Returns dict with passed/anomalies/stats/ts.
    """
    signals = _load_signals(book_id)
    if not signals:
        return {
            "passed": False,
            "error": f"signals.json not found or empty for {book_id}",
        }

    total = len(signals)
    a_count = sum(1 for s in signals if (s.get("signals") or {}).get("A"))
    b_count = sum(1 for s in signals if (s.get("signals") or {}).get("B"))
    c_count = sum(1 for s in signals if (s.get("signals") or {}).get("C"))
    d_count = sum(1 for s in signals if (s.get("signals") or {}).get("D"))
    skip_count = sum(1 for s in signals if s.get("skip_reason"))

    stats = {
        "total_pages": total,
        "a_count": a_count, "a_pct": round(a_count / total * 100, 1),
        "b_count": b_count, "b_pct": round(b_count / total * 100, 1),
        "c_count": c_count, "c_pct": round(c_count / total * 100, 1),
        "d_count": d_count, "d_pct": round(d_count / total * 100, 1),
        "skip_count": skip_count, "skip_pct": round(skip_count / total * 100, 1),
    }

    anomalies: list[str] = []
    # A% > 80% is NOT a fail condition — parameter-dense books naturally have high A%.
    # Signal router is per-page: high A% just means many pages have science content.
    # Record as info only.
    info_notes: list[str] = []
    if stats["a_pct"] > 80:
        info_notes.append(f"A信号较高({stats['a_pct']:.0f}%>80%) — 正常（参数密集型书籍）")

    # True fail conditions:
    # 1. A% < 5% when book has Skill A — router likely missed science content
    if stats["a_pct"] < 5:
        anomalies.append(f"A信号过低({stats['a_pct']:.0f}%<5%) — 可能OCR质量差或router配置错误")
    # 2. skip_pct > 40% — too many pages skipped, likely OCR quality issue
    if stats["skip_pct"] > 40:
        anomalies.append(f"跳过页过多({stats['skip_pct']:.0f}%>40%) — 可能OCR质量差")

    passed = len(anomalies) == 0
    result = {
        "passed": passed,
        "anomalies": anomalies,
        "info": info_notes,
        "stats": stats,
        "thresholds": {"min_a_pct": 5, "max_skip_pct": 40},
    }
    return result

# ── G3: TOC Analysis helpers (Stage 1 of two-phase pilot) ────────────────────

_TOC_PROMPT = """You are analyzing a book's table of contents to identify chapters with high value for three skill types.

Read the TOC/index pages below and return a JSON object identifying the best chapters for:
- skill_a: chapters likely containing quantitative science parameters (temperatures, times, formulas, data tables, rate constants)
- skill_b: chapters likely containing complete recipes (ingredient lists + steps)
- skill_d: chapters likely containing sensory/flavor/aesthetic descriptions (texture, mouthfeel, flavor profiles, taste terminology)

Return ONLY this JSON (no explanations):
{
  "skill_a": [{"chapter": "chapter name", "page_start": N, "page_end": N}],
  "skill_b": [{"chapter": "chapter name", "page_start": N, "page_end": N}],
  "skill_d": [{"chapter": "chapter name", "page_start": N, "page_end": N}]
}

If you cannot identify chapters for a skill, use []. If the text is not a TOC, return all empty lists.
"""


def _call_dashscope_sync(
    prompt: str,
    system: str,
    model: str = "qwen3.6-plus",
    timeout_sec: float = 30.0,
) -> str | None:
    """
    Synchronous single-shot DashScope call for lightweight tasks (TOC analysis).
    Returns raw response text or None on failure.
    """
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        return None
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 1024,
        "enable_thinking": False,
        "response_format": {"type": "json_object"},
    }
    try:
        import httpx as _httpx
        resp = _httpx.post(url, headers=headers, json=body, timeout=timeout_sec,
                           follow_redirects=False)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logging.getLogger("gate_toc").warning(f"DashScope TOC call failed: {e}")
        return None


def _analyze_toc(book_id: str, skill: str) -> dict | None:
    """
    Stage 1 of two-phase pilot: call DashScope Flash to analyze TOC pages.

    Reads first 10 pages from pages.json (usually contains TOC/index),
    asks DashScope to identify chapters relevant to the target skill.

    Returns dict with skill-keyed chapter lists, or None on failure/no TOC.
    """
    log = logging.getLogger(f"gate_toc.{book_id}")
    pages = _load_pages(book_id)
    if not pages:
        log.warning(f"No pages found for {book_id}")
        return None

    # Use first 10 pages (usually TOC area)
    toc_pages = pages[:10]
    toc_text = "\n\n".join(
        f"[Page {p.get('page', i+1)}]\n{p.get('text', '')[:600]}"
        for i, p in enumerate(toc_pages)
        if p.get("text", "").strip()
    )
    if not toc_text.strip():
        log.info(f"First 10 pages are blank — TOC not available for {book_id}")
        return None

    raw = _call_dashscope_sync(
        prompt=f"Book: {book_id}\n\n=== TOC / First Pages ===\n{toc_text[:3000]}",
        system=_TOC_PROMPT,
    )
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
        skill_key = f"skill_{skill}"
        chapters = parsed.get(skill_key, [])
        if not isinstance(chapters, list):
            return None
        valid = [
            c for c in chapters
            if isinstance(c, dict)
            and isinstance(c.get("page_start"), (int, float))
            and isinstance(c.get("page_end"), (int, float))
            and c["page_end"] > c["page_start"]
        ]
        if not valid:
            log.info(f"TOC: no valid chapters for {skill_key} in {book_id}")
            return None
        log.info(f"TOC: found {len(valid)} chapters for {skill_key} in {book_id}")
        return {skill_key: valid, "_all": parsed}
    except Exception as e:
        log.warning(f"TOC parse error: {e}")
        return None


def _select_pilot_pages(
    candidates: list[dict],
    pages_map: dict[int, str],
    toc_result: dict | None,
    skill: str,
    sample_size: int,
    seed: int = 42,
) -> tuple[list[dict], str]:
    """
    Select pilot pages using two-phase strategy.

    Phase 1 (TOC-guided): if toc_result has chapters, random.sample from
    candidate pages within those chapter page ranges.
    Phase 2 (fallback): top-confidence candidates.

    Returns (selected_pages, sampling_method_str).
    """
    if toc_result:
        chapters = toc_result.get(f"skill_{skill}", [])
        toc_candidates: list[dict] = []
        for sig in candidates:
            page_num = sig["page"]
            for ch in chapters:
                ps = int(ch.get("page_start", 0))
                pe = int(ch.get("page_end", 0))
                if ps <= page_num <= pe and pages_map.get(page_num, "").strip():
                    toc_candidates.append(sig)
                    break

        if len(toc_candidates) >= sample_size:
            rng = random.Random(seed)
            selected = rng.sample(toc_candidates, sample_size)
            return selected, "toc_guided_random"
        elif toc_candidates:
            toc_nums = {s["page"] for s in toc_candidates}
            rest = sorted(
                [s for s in candidates if s["page"] not in toc_nums],
                key=lambda x: x.get("confidence", 0), reverse=True
            )
            combined = toc_candidates + rest[:sample_size - len(toc_candidates)]
            return combined[:sample_size], "toc_guided_hybrid"

    # Fallback: confidence top-N
    sorted_cands = sorted(candidates, key=lambda x: x.get("confidence", 0), reverse=True)
    return sorted_cands[:sample_size], "confidence_topN_fallback"


# ── G3: Pilot Thresholds (per-skill) ────────────────────────────────────────
# Skill D has lower thresholds because FlavorTarget density is naturally sparse
PILOT_THRESHOLDS: dict[str, dict[str, float]] = {
    "a": {"auto_skip": 20.0, "auto_pass": 50.0},
    "b": {"auto_skip": 20.0, "auto_pass": 50.0},
    "c": {"auto_skip": 20.0, "auto_pass": 50.0},
    "d": {"auto_skip": 10.0, "auto_pass": 30.0},  # D density naturally lower
}

# ── G3: Pilot Gate ───────────────────────────────────────────────────────────

def gate_pilot(
    book_id: str,
    skill: str,
    sample_size: int = 5,
    explicit_pages: list[int] | None = None,
    toc_only: bool = False,
) -> dict:
    """
    G3 Pilot Gate — trial-run a few pages before full extraction.

    Two-phase page selection:
      Stage 1: TOC analysis via DashScope Flash (cheap, ~$0.002/book)
               Identifies chapters with high density of the target skill.
      Stage 2: Random sample from high-value chapters (reproducible seed=42).
               Fallback: confidence top-N if TOC analysis fails.

    Args:
        explicit_pages: if provided, use these exact page numbers (skip TOC analysis)
        toc_only: if True, only run Stage 1 (TOC analysis) and return

    Thresholds are per-skill (see PILOT_THRESHOLDS):
      D skill: skip<10%, pass>=30%  (sparse density)
      A/B/C:   skip<20%, pass>=50%

    Returns dict with passed/yield_pct/recommendation/cost_estimate/toc_analysis/sampling_method/ts.
    """
    skill = skill.lower()
    skill_key = {"a": "A", "b": "B", "c": "C", "d": "D"}.get(skill, skill.upper())

    signals = _load_signals(book_id)
    if not signals:
        return {
            "passed": False,
            "error": f"signals.json not found for {book_id}",
        }

    pages_map = {p["page"]: p.get("text", "") for p in _load_pages(book_id)}

    # Collect all signal-matching candidate pages
    candidates = [
        s for s in signals
        if (s.get("signals") or {}).get(skill_key)
        and not s.get("skip_reason")
        and pages_map.get(s["page"], "").strip()
    ]

    if not candidates:
        return {
            "passed": False,
            "error": f"No {skill_key}-signal pages found in signals.json for {book_id}",
            "total_candidates": 0,
        }

    # Two-phase pilot page selection:
    # Stage 1: TOC analysis (cheap Flash call) to identify high-value chapters
    # Stage 2: Random sample from those chapters (or fallback to confidence top-N)
    toc_result = None
    sampling_method = "confidence_topN_fallback"  # default
    if not toc_only and not explicit_pages:
        toc_result = _analyze_toc(book_id, skill)

    if explicit_pages:
        explicit_set = set(explicit_pages)
        pilot_pages = [s for s in candidates if s["page"] in explicit_set]
        # Add synthetic entries for pages not in signals
        found_pages = {s["page"] for s in pilot_pages}
        for pn in explicit_set - found_pages:
            if pages_map.get(pn, "").strip():
                pilot_pages.append({"page": pn, "confidence": 0.5, "signals": {skill_key: True}})
        sampling_method = "explicit_pages"
    else:
        pilot_pages, sampling_method = _select_pilot_pages(
            candidates, pages_map, toc_result, skill, sample_size,
        )

    if not pilot_pages:
        return {
            "passed": False,
            "error": f"No pilot pages could be selected for {book_id} skill_{skill}",
            "total_candidates": len(candidates),
            "sampling_method": sampling_method,
        }

    # Short-circuit: if toc_only, return TOC analysis without running LLM
    if toc_only:
        return {
            "passed": None,
            "toc_only": True,
            "toc_analysis": toc_result,
            "sampling_method": sampling_method,
            "total_candidate_pages": len(candidates),
            "skill": skill,
        }

    # Run Skill on pilot pages
    try:
        sys.path.insert(0, str(REPO_ROOT / "pipeline" / "skills"))
        import run_skill as _rs

        cfg = _rs.load_api_config()
        log = __import__("logging").getLogger(f"gate_pilot_{skill}")

        results: list[Any] = []
        times: list[float] = []
        for sig in pilot_pages:
            page_num = sig["page"]
            page_text = pages_map.get(page_num, "")
            hints = sig.get("hints", {})
            skill_hints = hints.get(skill_key, {})
            hint_str = ""
            if skill == "a" and skill_hints.get("mf_candidates"):
                hint_str = f"\n[Hint: possible MF matches: {', '.join(skill_hints['mf_candidates'])}]"
            user_msg = f"Book: {book_id}\nPage: {page_num}{hint_str}\n\n{page_text[:4000]}"
            t0 = time.time()
            try:
                raw = _rs.call_llm(skill, user_msg, cfg, log)
                parsed = _rs.extract_json(raw)
                if skill in ("a", "b", "c"):
                    items = parsed if isinstance(parsed, list) else []
                else:  # d
                    items = (
                        (parsed.get("flavor_targets") or []) +
                        (parsed.get("glossary") or [])
                        if isinstance(parsed, dict) else []
                    )
                results.append(items)
            except Exception as e:
                log.warning(f"Pilot page {page_num} failed: {e}")
                results.append(None)
            times.append(time.time() - t0)

    except Exception as e:
        return {
            "passed": None,
            "error": f"Could not run Skill {skill}: {e}",
            "recommendation": "human_review",
        }

    # Compute yield
    non_empty = sum(1 for r in results if r is not None and r != [])
    total_run = len(results)
    yield_pct = (non_empty / total_run * 100) if total_run > 0 else 0.0

    # Cost estimates (Opus ~$0.12/page, Flash ~$0.002/page)
    cost_per_page = {"a": 0.12, "b": 0.003, "c": 0.003, "d": 0.12}.get(skill, 0.05)
    total_candidates = len(candidates)
    estimated_useful = int(total_candidates * yield_pct / 100)
    estimated_cost = round(total_candidates * cost_per_page, 2)
    estimated_waste = round((total_candidates - estimated_useful) * cost_per_page, 2)

    # Preview of first few results
    preview = []
    for r in results[:3]:
        if r:
            preview.append(str(r[0])[:200] if r else "[]")

    result: dict[str, Any] = {
        "sample_size": total_run,
        "non_empty_pages": non_empty,
        "yield_pct": round(yield_pct, 1),
        "total_candidate_pages": total_candidates,
        "estimated_useful_records": estimated_useful,
        "estimated_cost_usd": estimated_cost,
        "estimated_waste_usd": estimated_waste,
        "avg_time_per_page_s": round(sum(times) / len(times), 2) if times else 0,
        "sample_results_preview": preview,
        "pilot_pages": [p["page"] for p in pilot_pages],
        "sampling_method": sampling_method,
        "toc_analysis": toc_result,
    }

    thr = PILOT_THRESHOLDS.get(skill, PILOT_THRESHOLDS["a"])
    auto_pass = thr["auto_pass"]
    auto_skip = thr["auto_skip"]
    result["thresholds"] = {"auto_pass": auto_pass, "auto_skip": auto_skip}

    if yield_pct >= auto_pass:
        result["passed"] = True
        result["recommendation"] = "auto_proceed"
    elif yield_pct >= auto_skip:
        result["passed"] = None  # human review threshold
        result["recommendation"] = "human_review"
        result["needs_review"] = True
    else:
        result["passed"] = False
        result["recommendation"] = f"skip_skill_{skill}"

    return result

# ── G4: Final QC ──────────────────────────────────────────────────────────────

_SKILL_A_REQUIRED = {"mother_formula", "formula_id", "parameter_name", "value", "unit"}
_SKILL_B_REQUIRED = {"name", "ingredients", "steps"}
_SKILL_C_REQUIRED = {"canonical_name", "category"}
_SKILL_D_REQUIRED_FT = {"aesthetic_word", "matrix_type"}
_SKILL_D_REQUIRED_GL = {"term_zh", "definition_zh"}

_VALID_MF_PREFIXES = {"MF-T", "MF-K", "MF-M", "MF-R", "MF-C"}


def _validate_record(record: dict, skill: str) -> list[str]:
    """Return list of schema errors for one record."""
    errors: list[str] = []
    if skill == "a":
        for field in _SKILL_A_REQUIRED:
            if record.get(field) is None:
                errors.append(f"missing field: {field}")
        fid = record.get("formula_id", "")
        if fid and not any(fid.startswith(p) for p in _VALID_MF_PREFIXES):
            errors.append(f"invalid formula_id: {fid}")
    elif skill == "b":
        for field in _SKILL_B_REQUIRED:
            if not record.get(field):
                errors.append(f"missing field: {field}")
    elif skill == "c":
        for field in _SKILL_C_REQUIRED:
            if not record.get(field):
                errors.append(f"missing field: {field}")
    elif skill == "d":
        _type = record.get("_type", "")
        if _type == "flavor_target":
            for f in _SKILL_D_REQUIRED_FT:
                if not record.get(f):
                    errors.append(f"missing flavor_target field: {f}")
        elif _type == "glossary":
            for f in _SKILL_D_REQUIRED_GL:
                if not record.get(f):
                    errors.append(f"missing glossary field: {f}")
    return errors


def gate_final_qc(
    book_id: str,
    skill: str,
    sample_size: int = 10,
) -> dict:
    """
    G4 Final QC — run after full Skill extraction.

    Checks results.jsonl for:
    - Schema completeness (required fields present)
    - Error records (_error field) < 10%
    - Duplicate detection (same page + parameter_name)
    - Skill A: MF binding rate

    Returns dict with passed/stats/schema_errors/ts.
    """
    skill = skill.lower()
    records = _load_results(book_id, skill)
    if not records:
        return {
            "passed": False,
            "error": f"results.jsonl not found or empty for {book_id}/skill_{skill}",
        }

    total = len(records)
    error_records = [r for r in records if r.get("_error")]
    error_pct = len(error_records) / total * 100

    # Schema validation (on sample)
    import random
    sample = random.sample(records, min(sample_size, total))
    schema_errors: list[dict] = []
    for rec in sample:
        errs = _validate_record(rec, skill)
        if errs:
            schema_errors.append({"page": rec.get("_page"), "errors": errs})

    # Duplicate detection (page + parameter_name for skill A)
    if skill == "a":
        seen: set[tuple] = set()
        dups = 0
        for r in records:
            key = (r.get("_page"), r.get("parameter_name"), r.get("formula_id"))
            if key in seen:
                dups += 1
            seen.add(key)
    else:
        dups = 0

    stats: dict[str, Any] = {
        "total_records": total,
        "error_count": len(error_records),
        "error_pct": round(error_pct, 1),
        "schema_sample_size": len(sample),
        "schema_error_count": len(schema_errors),
        "duplicate_count": dups,
    }

    # Skill A: MF binding rate
    if skill == "a":
        mf_bound = sum(1 for r in records if r.get("formula_id"))
        stats["mf_binding_pct"] = round(mf_bound / total * 100, 1)

    passed = (
        error_pct < 10.0
        and len(schema_errors) == 0
    )

    result = {
        "passed": passed,
        "stats": stats,
        "schema_errors": schema_errors[:10],  # cap at 10 for readability
        "thresholds": {"max_error_pct": 10.0},
    }
    return result

# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gate system — quality gates for extraction pipeline")
    p.add_argument("--gate", required=True,
                   choices=["preflight", "ocr_qc", "signal_qc", "pilot", "final_qc"],
                   help="Which gate to run")
    p.add_argument("--book-id", required=True, help="Book ID")
    p.add_argument("--skill", choices=["a", "b", "c", "d"],
                   help="Skill (required for pilot and final_qc)")
    p.add_argument("--pages", default="5",
                   help="Pilot: sample size (int, default: 5) OR comma-separated page numbers e.g. 45,67,89")
    p.add_argument("--toc-only", action="store_true",
                   help="Pilot gate: only run TOC analysis (Stage 1), don\'t run LLM extraction")
    p.add_argument("--sample", type=int, default=10,
                   help="Sample size for final_qc (default: 10)")
    p.add_argument("--books-yaml", default=str(REPO_ROOT / "config" / "books.yaml"),
                   help="Path to books.yaml (for preflight)")
    p.add_argument("--no-save", action="store_true",
                   help="Don't write result to disk, just print")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    book_id = args.book_id

    if args.gate == "preflight":
        result = gate_preflight(book_id, args.books_yaml)
        gate_name = "preflight"
    elif args.gate == "ocr_qc":
        result = gate_ocr_qc(book_id)
        gate_name = "ocr_qc"
    elif args.gate == "signal_qc":
        result = gate_signal_qc(book_id)
        gate_name = "signal_qc"
    elif args.gate == "pilot":
        if not args.skill:
            print("ERROR: --skill required for pilot gate", file=sys.stderr)
            sys.exit(1)
        # Parse --pages: either an int (sample size) or comma-separated page numbers
        explicit_pages: list[int] | None = None
        sample_size = 5
        pages_arg = str(args.pages).strip()
        if "," in pages_arg:
            try:
                explicit_pages = [int(x.strip()) for x in pages_arg.split(",") if x.strip()]
            except ValueError:
                print(f"ERROR: --pages must be an int or comma-separated ints, got: {pages_arg}", file=sys.stderr)
                sys.exit(1)
        else:
            try:
                sample_size = int(pages_arg)
            except ValueError:
                print(f"ERROR: --pages must be an int or comma-separated ints, got: {pages_arg}", file=sys.stderr)
                sys.exit(1)

        toc_only = getattr(args, "toc_only", False)
        result = gate_pilot(
            book_id, args.skill,
            sample_size=sample_size,
            explicit_pages=explicit_pages,
            toc_only=toc_only,
        )
        gate_name = f"pilot_{args.skill}"
    elif args.gate == "final_qc":
        if not args.skill:
            print("ERROR: --skill required for final_qc gate", file=sys.stderr)
            sys.exit(1)
        result = gate_final_qc(book_id, args.skill, sample_size=args.sample)
        gate_name = "final_qc"
    else:
        print(f"Unknown gate: {args.gate}", file=sys.stderr)
        sys.exit(1)

    # Print result
    print(json.dumps(result, ensure_ascii=False, indent=2))
    status = "✅ PASSED" if result.get("passed") is True else (
        "⚠️  NEEDS REVIEW" if result.get("passed") is None else "❌ FAILED"
    )
    print(f"\n{status} — Gate: {gate_name} | Book: {book_id}")

    if result.get("recommendation"):
        print(f"Recommendation: {result['recommendation']}")

    # Save to disk
    if not args.no_save:
        out_path = _save_gate(book_id, gate_name, result)
        print(f"Result saved → {out_path}")


if __name__ == "__main__":
    main()
