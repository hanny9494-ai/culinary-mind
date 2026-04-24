#!/usr/bin/env python3
"""
scripts/orchestrator.py
Deterministic pipeline scheduler — replaces LLM-driven dispatch.

Reads books.yaml as single source of truth, drives each book through the
Skill lifecycle state machine, runs quality gates at each stage, and
writes the outcome back to books.yaml.

Usage:
    python orchestrator.py --track A --dry-run            # preview plan
    python orchestrator.py --track A                       # full auto
    python orchestrator.py --track A --book-id mc_vol1     # single book
    python orchestrator.py --track B --concurrency 3       # parallel
    python orchestrator.py --track A --skip-gates          # skip G2/G3

Responsibilities:
  - Decide which books need the target skill run
  - Check OCR/Signal prerequisites (but not run them — that's ocr-claw / signal_router)
  - Run G2 signal_qc / G3 pilot / G4 final_qc via pipeline.skills.gates
  - Invoke run_skill.py via subprocess (capture returncode)
  - Update books.yaml skill_X_status
"""

import argparse
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
# Run child processes with the same interpreter that launched us — avoids
# drift between orchestrator's env and run_skill.py's. The launcher chooses
# the interpreter (miniforge3 is still the right pick for this repo because
# homebrew python 3.14 has the SSL bug).
PYTHON_BIN = sys.executable
BOOKS_YAML = REPO_ROOT / "config" / "books.yaml"
OUTPUT_ROOT = REPO_ROOT / "output"
RUN_SKILL_PY = REPO_ROOT / "pipeline" / "skills" / "run_skill.py"
TOC_ROUTER_PY = REPO_ROOT / "pipeline" / "skills" / "toc_router.py"
OCR_API_PY = REPO_ROOT / "pipeline" / "prep" / "paddleocr_api.py"

# Make pipeline.skills importable so we can call gates/lifecycle in-process.
sys.path.insert(0, str(REPO_ROOT / "pipeline" / "skills"))
import gates as _gates                  # noqa: E402
import lifecycle as _lifecycle          # noqa: E402

# Proxy bypass (run_skill does this too; safety for our direct gate calls)
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(_k, None)
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")


# ── Structured logging ────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [orch] %(message)s",
)
log = logging.getLogger("orchestrator")


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _load_books_yaml() -> list[dict]:
    with open(BOOKS_YAML) as f:
        data = yaml.safe_load(f) or []
    if not isinstance(data, list):
        raise RuntimeError(f"{BOOKS_YAML}: expected top-level list")
    return data


def _dump_books_yaml(books: list[dict]) -> None:
    """Atomic rewrite of books.yaml preserving key order best-effort."""
    tmp = BOOKS_YAML.with_suffix(".yaml.tmp")
    with open(tmp, "w") as f:
        yaml.safe_dump(
            books,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    tmp.replace(BOOKS_YAML)


def _update_book_status(book_id: str, field: str, value: str) -> None:
    """Rewrite books.yaml with book_id[field] = value. Thread-safe via lock."""
    with _yaml_lock:
        books = _load_books_yaml()
        for b in books:
            if b.get("id") == book_id:
                b[field] = value
                break
        _dump_books_yaml(books)


_yaml_lock = threading.Lock()
_log_lock = threading.Lock()
_quota_lock = threading.Lock()


# ── PaddleOCR-VL free-tier daily quota ────────────────────────────────────────
# The AI Studio free tier caps total OCR at 20 000 pages/day (UTC date).
# We track cumulative pages per day in output/_ocr_daily_quota.json so a
# single big-batch run can't blow through the quota silently.
OCR_DAILY_QUOTA = 20000
_QUOTA_PATH = OUTPUT_ROOT / "_ocr_daily_quota.json"


def _today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _quota_load() -> dict:
    if not _QUOTA_PATH.exists():
        return {}
    try:
        return json.loads(_QUOTA_PATH.read_text()) or {}
    except Exception:
        return {}


def _quota_save(data: dict) -> None:
    _QUOTA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _QUOTA_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(_QUOTA_PATH)


def _quota_used_today() -> int:
    return int(_quota_load().get(_today_utc(), 0))


def _quota_check_and_reserve(pages_needed: int) -> tuple[bool, int]:
    """Atomically check remaining quota and optimistically reserve pages.

    Returns (ok, used_after). If ok=False the reservation is not applied.
    """
    with _quota_lock:
        data = _quota_load()
        today = _today_utc()
        used = int(data.get(today, 0))
        if used + pages_needed > OCR_DAILY_QUOTA:
            return False, used
        data[today] = used + pages_needed
        _quota_save(data)
        return True, data[today]


def _quota_adjust(delta: int) -> None:
    """Adjust today's counter (e.g. refund on failure, or correct upward)."""
    if delta == 0:
        return
    with _quota_lock:
        data = _quota_load()
        today = _today_utc()
        data[today] = max(0, int(data.get(today, 0)) + delta)
        _quota_save(data)


def _estimate_pdf_pages(pdf_path: Path) -> int | None:
    """Return page count using pypdfium2, or None on failure."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(pdf_path))
        n = len(doc)
        doc.close()
        return n
    except Exception:
        return None


def _write_orchestrator_log(book_id: str, entry: dict) -> None:
    """Append one entry to orchestrator_log.jsonl (line-delimited JSON).

    JSONL is chosen over a re-serialised JSON array because it is
    append-only and safe under concurrent workers — each write is one
    atomic write() syscall; no read-modify-write race. The per-process
    _log_lock is kept as an extra safety belt for shared file handles.
    """
    out_dir = OUTPUT_ROOT / book_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "orchestrator_log.jsonl"
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _log_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)


# ── Per-book driver ───────────────────────────────────────────────────────────

class Outcome:
    SKIPPED = "skipped"
    DONE = "done"
    FAILED = "failed"
    GATE_BLOCKED = "gate_blocked"
    NEEDS_REVIEW = "needs_review"


def _plan_for_book(book: dict, skill: str, skip_gates: bool) -> dict:
    """
    Pure function: what would we do for this book?
    Returns {'action': one of ['skip','run'], 'reason': str, 'steps': [...]}.
    """
    book_id = book.get("id", "?")
    skills = [s.upper() for s in (book.get("skills") or [])]
    target = skill.upper()

    if target not in skills:
        return {"action": "skip", "reason": f"skills field does not include {target}"}

    cur_status = book.get(f"skill_{skill.lower()}_status", "pending")
    if cur_status in ("done", "skip"):
        return {"action": "skip", "reason": f"skill_{skill}_status={cur_status}"}

    ocr_status = book.get("ocr_status", "pending")
    needs_ocr = ocr_status != "done"
    if needs_ocr:
        # We can drive OCR ourselves via paddleocr_api.py — but only if the
        # book entry tells us where the PDF is. Without source_pdf the book
        # isn't actionable.
        src = book.get("source_pdf")
        if not src:
            return {"action": "skip",
                    "reason": f"needs OCR but no source_pdf (ocr_status={ocr_status})"}
        src_path = src if Path(src).is_absolute() else str(REPO_ROOT / src)
        if not Path(src_path).exists():
            return {"action": "skip",
                    "reason": f"source_pdf missing on disk: {src}"}

    signal_status = book.get("signal_status", "pending")
    needs_toc_routing = signal_status != "done"

    phase = _lifecycle.compute_lifecycle(_lifecycle.enrich_book_with_gates(book))
    if phase == "qc_passed":
        return {"action": "skip", "reason": "lifecycle=qc_passed"}

    steps: list[str] = []
    if needs_ocr:
        # Orchestrator drives OCR itself via pipeline/prep/paddleocr_api.py.
        steps.append("ocr")
    if needs_toc_routing:
        # Orchestrator drives signal routing itself via toc_router.py.
        steps.append("toc_routing")
    if not skip_gates:
        steps += ["G2_signal_qc", "G3_pilot"]
    steps += ["run_skill", "G4_final_qc", "update_books_yaml"]
    reason = f"phase={phase}, status={cur_status}"
    if needs_ocr:
        reason += f", ocr_status={ocr_status} → ocr"
    if needs_toc_routing:
        reason += f", signal_status={signal_status} → toc_routing"
    return {
        "action": "run",
        "reason": reason,
        "steps": steps,
    }


def _run_subprocess_skill(book_id: str, skill: str, pages: int | None,
                          log_handle) -> tuple[int, float]:
    """Invoke run_skill.py. Returns (returncode, duration_seconds)."""
    cmd = [
        PYTHON_BIN, str(RUN_SKILL_PY),
        "--skill", skill,
        "--book-id", book_id,
        "--resume",
    ]
    if pages:
        cmd += ["--pages", str(pages)]
    t0 = time.time()
    log_handle.info(f"[{book_id}] subprocess: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    dur = time.time() - t0
    if result.returncode != 0:
        log_handle.error(f"[{book_id}] run_skill exited {result.returncode}")
        log_handle.error(f"[{book_id}] stderr tail: {result.stderr[-500:]}")
    return result.returncode, dur


def _run_subprocess_ocr(book: dict, log_handle,
                        split_pages: int = 80) -> tuple[int, float, str]:
    """Invoke paddleocr_api.py. Returns (returncode, duration_seconds, stderr_tail).

    Reads book['source_pdf'] (absolute or repo-relative) and writes to
    output/{book_id}/prep/. paddleocr_api is idempotent — it skips if
    merged.md already exists.

    PaddleOCR-VL 1.5 API caps each request at ~100 pages; we pass
    split-pages=80 by default to leave headroom. Override via CLI
    --ocr-split-pages if a book needs tighter/larger chunks.
    """
    book_id = book["id"]
    src = book["source_pdf"]
    src_path = src if Path(src).is_absolute() else str(REPO_ROOT / src)
    out_dir = str(OUTPUT_ROOT / book_id / "prep")
    cmd = [PYTHON_BIN, str(OCR_API_PY),
           "--pdf", src_path,
           "--output-dir", out_dir,
           "--split-pages", str(split_pages)]
    t0 = time.time()
    log_handle.info(f"[{book_id}] subprocess: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    dur = time.time() - t0
    stderr_tail = (result.stderr or "")[-500:]
    if result.returncode != 0:
        log_handle.error(f"[{book_id}] paddleocr_api exited {result.returncode}")
        log_handle.error(f"[{book_id}] stderr tail: {stderr_tail}")
    return result.returncode, dur, stderr_tail


def _build_pages_json_from_prep(book_id: str, log_handle) -> tuple[bool, int]:
    """Convert output/{book_id}/prep/doc_NNNN.md → output/{book_id}/pages.json.

    pages.json schema: list of {"page": int, "text": str, "source": str}.
    Returns (success, page_count).
    """
    prep_dir = OUTPUT_ROOT / book_id / "prep"
    pages_path = OUTPUT_ROOT / book_id / "pages.json"
    if not prep_dir.exists():
        log_handle.error(f"[{book_id}] prep dir missing: {prep_dir}")
        return False, 0
    docs = sorted(prep_dir.glob("doc_*.md"))
    if not docs:
        log_handle.error(f"[{book_id}] no doc_*.md in {prep_dir}")
        return False, 0
    pages: list[dict] = []
    for p in docs:
        # doc_0001.md → 1
        try:
            page_num = int(p.stem.split("_", 1)[1])
        except Exception:
            log_handle.warning(f"[{book_id}] skipping unparseable filename: {p.name}")
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:
            log_handle.warning(f"[{book_id}] failed to read {p.name}: {e}")
            text = ""
        pages.append({"page": page_num, "text": text, "source": "paddleocr_api"})
    tmp = pages_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(pages, ensure_ascii=False))
    tmp.replace(pages_path)
    log_handle.info(f"[{book_id}] wrote pages.json with {len(pages)} pages → {pages_path}")
    return True, len(pages)


def _run_subprocess_toc_router(book_id: str, log_handle) -> tuple[int, float, str]:
    """Invoke toc_router.py --book-id. Returns (returncode, duration_seconds, stderr_tail)."""
    cmd = [PYTHON_BIN, str(TOC_ROUTER_PY), "--book-id", book_id]
    t0 = time.time()
    log_handle.info(f"[{book_id}] subprocess: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    dur = time.time() - t0
    stderr_tail = (result.stderr or "")[-500:]
    if result.returncode != 0:
        log_handle.error(f"[{book_id}] toc_router exited {result.returncode}")
        log_handle.error(f"[{book_id}] stderr tail: {stderr_tail}")
    return result.returncode, dur, stderr_tail


# ── Stage pipeline ────────────────────────────────────────────────────────────
# Refactor 2026-04-20: the book-serial _process_book was replaced by a
# three-pool stage pipeline. Each pool has independent concurrency and
# talks to a different API (OCR → DashScope paddle; TOC → DashScope
# qwen3.6; Skill → 灵雅 gpt54/gemini). The individual subprocess /
# gate calls are unchanged — only the composition is new.
#
# A book flows:  initial dispatch → ocr_q → toc_q → skill_q → finalize
# Auto-chaining happens inside the worker when a stage succeeds.

@dataclass
class BookState:
    book:            dict
    skill:           str
    skip_gates:      bool
    pages:           int | None
    pilot_sample:    int
    ocr_split_pages: int
    entry:           dict
    started:         float


_NEXT_TOC   = "toc"
_NEXT_SKILL = "skill"
_NEXT_DONE: str | None = None   # terminal (finalize, don't re-enqueue)


def _mk_entry(book: dict, skill: str, plan: dict) -> dict:
    return {
        "ts":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "book_id": book["id"],
        "skill":   skill,
        "plan":    plan,
        "steps":   [],
    }


# ── Stage: OCR ────────────────────────────────────────────────────────────────

def _stage_ocr(s: BookState) -> str | None:
    book_id = s.book["id"]
    entry   = s.entry
    try:
        src = s.book["source_pdf"]
        src_path = Path(src if Path(src).is_absolute() else REPO_ROOT / src)
        est_pages = _estimate_pdf_pages(src_path) or 0
        ok, used_after = _quota_check_and_reserve(est_pages or 1)
        if not ok:
            entry["steps"].append({
                "step":             "ocr",
                "skipped":          "daily_quota_exceeded",
                "est_pages":        est_pages,
                "quota_used_today": used_after,
                "quota_cap":        OCR_DAILY_QUOTA,
            })
            entry["outcome"]    = Outcome.SKIPPED
            entry["blocked_at"] = "ocr_quota"
            log.warning(
                f"[OCR] [{book_id}] skipped — daily quota would exceed "
                f"{OCR_DAILY_QUOTA} (est {est_pages}, used {used_after})"
            )
            return _NEXT_DONE

        rc, dur, stderr_tail = _run_subprocess_ocr(
            s.book, log, split_pages=s.ocr_split_pages)
        ok_build, n_pages = (False, 0)
        if rc == 0:
            ok_build, n_pages = _build_pages_json_from_prep(book_id, log)
        # Reconcile the reservation with the actual pages written.
        _quota_adjust(n_pages - (est_pages or 1))
        entry["steps"].append({
            "step":             "ocr",
            "returncode":       rc,
            "duration_s":       round(dur, 1),
            "pages_built":      n_pages,
            "est_pages":        est_pages,
            "quota_used_today": _quota_used_today(),
            "quota_cap":        OCR_DAILY_QUOTA,
        })
        if rc != 0 or not ok_build:
            _update_book_status(book_id, "ocr_status", "failed")
            entry["outcome"] = Outcome.FAILED
            entry["error"]   = (f"ocr subprocess rc={rc}" if rc != 0
                                else "pages.json build failed")
            if stderr_tail:
                entry["stderr_tail"] = stderr_tail
            log.error(f"[OCR] [{book_id}] failed — ocr_status=failed; continuing")
            return _NEXT_DONE
        _update_book_status(book_id, "ocr_status", "done")
        log.info(
            f"[OCR] [{book_id}] done ({n_pages} pages, "
            f"quota used {_quota_used_today()}/{OCR_DAILY_QUOTA}) "
            f"→ ocr_status=done"
        )
        return _NEXT_TOC
    except Exception as e:   # noqa: BLE001
        entry["outcome"] = Outcome.FAILED
        entry["error"]   = f"OCR stage exception: {e}"
        log.exception(f"[OCR] [{book_id}] unhandled error: {e}")
        return _NEXT_DONE


# ── Stage: TOC routing ────────────────────────────────────────────────────────

def _stage_toc(s: BookState) -> str | None:
    book_id = s.book["id"]
    entry   = s.entry
    try:
        rc, dur, stderr_tail = _run_subprocess_toc_router(book_id, log)
        entry["steps"].append({
            "step":       "toc_routing",
            "returncode": rc,
            "duration_s": round(dur, 1),
        })
        if rc != 0:
            _update_book_status(book_id, "signal_status", "failed")
            entry["outcome"] = Outcome.FAILED
            entry["error"]   = f"toc_router failed: {stderr_tail}"
            log.error(f"[TOC] [{book_id}] failed — signal_status=failed; continuing")
            return _NEXT_DONE
        _update_book_status(book_id, "signal_status", "done")
        log.info(f"[TOC] [{book_id}] done → signal_status=done")
        return _NEXT_SKILL
    except Exception as e:   # noqa: BLE001
        entry["outcome"] = Outcome.FAILED
        entry["error"]   = f"TOC stage exception: {e}"
        log.exception(f"[TOC] [{book_id}] unhandled error: {e}")
        return _NEXT_DONE


# ── Stage: Skill (G2 → G3 → run_skill → G4 → books.yaml) ──────────────────────

def _stage_skill_and_gates(s: BookState) -> str | None:
    book_id = s.book["id"]
    skill   = s.skill
    entry   = s.entry
    try:
        # G2 / G3 only when skip_gates is not set
        if not s.skip_gates:
            g2 = _gates.gate_signal_qc(book_id)
            _gates._save_gate(book_id, "signal_qc", g2)
            entry["steps"].append({
                "step":      "G2_signal_qc",
                "passed":    g2.get("passed"),
                "anomalies": g2.get("anomalies", []),
            })
            if g2.get("passed") is False:
                entry["outcome"]    = Outcome.GATE_BLOCKED
                entry["blocked_at"] = "G2"
                log.warning(f"[SKILL] [{book_id}] G2 blocked: {g2.get('anomalies')}")
                return _NEXT_DONE

            g3 = _gates.gate_pilot(book_id, skill, sample_size=s.pilot_sample)
            _gates._save_gate(book_id, f"pilot_{skill.lower()}", g3)
            entry["steps"].append({
                "step":           "G3_pilot",
                "yield_pct":      g3.get("yield_pct"),
                "passed":         g3.get("passed"),
                "recommendation": g3.get("recommendation"),
            })
            passed = g3.get("passed")
            if passed is False:
                _update_book_status(book_id, f"skill_{skill.lower()}_status", "skip")
                entry["outcome"]      = Outcome.GATE_BLOCKED
                entry["blocked_at"]   = "G3"
                entry["final_status"] = "skip"
                log.info(f"[SKILL] [{book_id}] G3 pilot recommends skip — books.yaml updated")
                return _NEXT_DONE
            if passed is None:
                entry["outcome"]    = Outcome.NEEDS_REVIEW
                entry["blocked_at"] = "G3"
                log.info(f"[SKILL] [{book_id}] G3 pilot needs human review")
                return _NEXT_DONE

        # ── Full extraction ──
        _update_book_status(book_id, f"skill_{skill.lower()}_status", "running")
        rc, dur = _run_subprocess_skill(book_id, skill, s.pages, log)
        entry["steps"].append({
            "step":       "run_skill",
            "returncode": rc,
            "duration_s": round(dur, 1),
        })
        if rc != 0:
            _update_book_status(book_id, f"skill_{skill.lower()}_status", "failed")
            entry["outcome"] = Outcome.FAILED
            log.error(f"[SKILL] [{book_id}] run_skill failed (rc={rc})")
            return _NEXT_DONE

        # ── G4 final_qc ──
        g4 = _gates.gate_final_qc(book_id, skill)
        _gates._save_gate(book_id, f"final_qc_{skill.lower()}", g4)
        entry["steps"].append({
            "step":   "G4_final_qc",
            "passed": g4.get("passed"),
            "stats":  g4.get("stats"),
        })

        # ── Update books.yaml ──
        final_field_value = "done" if g4.get("passed") else "partial"
        _update_book_status(book_id, f"skill_{skill.lower()}_status", final_field_value)
        entry["final_status"] = final_field_value
        entry["outcome"]      = Outcome.DONE if g4.get("passed") else Outcome.NEEDS_REVIEW
        log.info(f"[SKILL] [{book_id}] DONE — skill_{skill.lower()}_status={final_field_value}")
        return _NEXT_DONE
    except Exception as e:   # noqa: BLE001
        entry["outcome"] = Outcome.FAILED
        entry["error"]   = f"SKILL stage exception: {e}"
        log.exception(f"[SKILL] [{book_id}] unhandled error: {e}")
        return _NEXT_DONE


# ── Pipeline runner ───────────────────────────────────────────────────────────

class _Pipeline:
    """Three stage pools (ocr / toc / skill) with auto-chaining.

    Each pool has its own thread-pool of workers consuming from a Queue.
    When a stage returns _NEXT_TOC or _NEXT_SKILL the worker re-enqueues the
    BookState onto the next pool. When it returns _NEXT_DONE the book is
    finalized (log written, pending counter decremented).

    Single process — books.yaml writes are centralized behind _yaml_lock.
    """

    def __init__(self, ocr_c: int, toc_c: int, skill_c: int,
                 dashboard_interval: float = 15.0):
        self.ocr_c, self.toc_c, self.skill_c = ocr_c, toc_c, skill_c
        self.ocr_q:   queue.Queue = queue.Queue()
        self.toc_q:   queue.Queue = queue.Queue()
        self.skill_q: queue.Queue = queue.Queue()
        self._in_flight = {"ocr": 0, "toc": 0, "skill": 0}
        self._lock = threading.Lock()
        self._results: list[dict] = []
        self._results_lock = threading.Lock()
        self._pending = 0
        self._all_done = threading.Event()
        self._stop_dash = threading.Event()
        self._dashboard_interval = dashboard_interval

    def _bump(self, stage: str, delta: int) -> None:
        with self._lock:
            self._in_flight[stage] += delta

    def _finalize(self, s: BookState) -> None:
        s.entry.setdefault("outcome", "unknown")
        s.entry["duration_s"] = round(time.time() - s.started, 2)
        try:
            _write_orchestrator_log(s.book["id"], s.entry)
        except Exception as e:   # noqa: BLE001
            log.error(f"[{s.book['id']}] failed to write orchestrator_log: {e}")
        with self._results_lock:
            self._results.append(s.entry)
        with self._lock:
            self._pending -= 1
            if self._pending <= 0:
                self._all_done.set()

    def _worker(self, stage_name: str, stage_fn, q: queue.Queue) -> None:
        while True:
            s = q.get()
            try:
                if s is None:
                    return
                self._bump(stage_name, 1)
                try:
                    next_stage = stage_fn(s)
                except Exception as e:   # noqa: BLE001
                    s.entry["outcome"] = Outcome.FAILED
                    s.entry["error"]   = f"{stage_name} worker exception: {e}"
                    log.exception(f"[{stage_name.upper()}] [{s.book['id']}] worker crashed: {e}")
                    next_stage = _NEXT_DONE
                if next_stage == _NEXT_TOC:
                    self.toc_q.put(s)
                elif next_stage == _NEXT_SKILL:
                    self.skill_q.put(s)
                else:
                    self._finalize(s)
            finally:
                if s is not None:
                    self._bump(stage_name, -1)
                q.task_done()

    def _dashboard(self) -> None:
        while not self._stop_dash.wait(self._dashboard_interval):
            with self._lock:
                o, t, sk = (self._in_flight["ocr"],
                            self._in_flight["toc"],
                            self._in_flight["skill"])
                pending = self._pending
            log.info(
                f"[dashboard] "
                f"OCR {o}/{self.ocr_c} run, {self.ocr_q.qsize()} q | "
                f"TOC {t}/{self.toc_c} run, {self.toc_q.qsize()} q | "
                f"SKILL {sk}/{self.skill_c} run, {self.skill_q.qsize()} q | "
                f"pending={pending}"
            )

    def run(self, dispatch: list[tuple[BookState, str]]) -> list[dict]:
        """dispatch: list of (BookState, initial_stage∈{'ocr','toc','skill'})."""
        self._pending = len(dispatch)
        if self._pending == 0:
            return []

        workers: list[threading.Thread] = []
        for _ in range(self.ocr_c):
            w = threading.Thread(target=self._worker,
                                 args=("ocr",   _stage_ocr,              self.ocr_q),
                                 daemon=True, name="ocr_w")
            w.start(); workers.append(w)
        for _ in range(self.toc_c):
            w = threading.Thread(target=self._worker,
                                 args=("toc",   _stage_toc,              self.toc_q),
                                 daemon=True, name="toc_w")
            w.start(); workers.append(w)
        for _ in range(self.skill_c):
            w = threading.Thread(target=self._worker,
                                 args=("skill", _stage_skill_and_gates,  self.skill_q),
                                 daemon=True, name="skill_w")
            w.start(); workers.append(w)

        dash = threading.Thread(target=self._dashboard, daemon=True, name="dashboard")
        dash.start()

        qs = {"ocr": self.ocr_q, "toc": self.toc_q, "skill": self.skill_q}
        for s, start_stage in dispatch:
            qs[start_stage].put(s)

        self._all_done.wait()
        self._stop_dash.set()

        # Shutdown workers cleanly.
        for _ in range(self.ocr_c):   self.ocr_q.put(None)
        for _ in range(self.toc_c):   self.toc_q.put(None)
        for _ in range(self.skill_c): self.skill_q.put(None)
        for w in workers:
            w.join(timeout=5)
        return self._results


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic pipeline scheduler")
    p.add_argument("--track", required=True, choices=["A", "B", "C", "D"],
                   help="Which skill track to drive")
    p.add_argument("--book-id", help="Restrict to one book")
    p.add_argument("--dry-run", action="store_true", help="Print plan without executing")
    p.add_argument("--skip-gates", action="store_true",
                   help="Skip G2/G3 (use only for known-safe resumes)")
    # Back-compat: --concurrency used to mean "parallel book workers".
    # In the new stage-pipeline it aliases --skill-concurrency if the latter
    # isn't given. Default None so we can detect "not set".
    p.add_argument("--concurrency", type=int, default=None,
                   help="[DEPRECATED alias for --skill-concurrency] "
                        "Parallel skill workers. Prefer the per-stage flags.")
    p.add_argument("--ocr-concurrency", type=int, default=1,
                   help="OCR pool workers (default 1; AI Studio PaddleOCR "
                        "free API does not tolerate concurrency)")
    p.add_argument("--toc-concurrency", type=int, default=5,
                   help="TOC router pool workers (default 5; DashScope qwen3.6)")
    p.add_argument("--skill-concurrency", type=int, default=None,
                   help="Skill pool workers (default 3; 灵雅 gpt54/gemini). "
                        "If not set, falls back to --concurrency, then 3.")
    p.add_argument("--pages", type=int, default=None,
                   help="Pass through to run_skill.py --pages (max pages per book)")
    p.add_argument("--pilot-sample", type=int, default=5,
                   help="G3 pilot sample size (default 5)")
    p.add_argument("--ocr-split-pages", type=int, default=80,
                   help="paddleocr_api --split-pages value (default 80; "
                        "API hard cap is ~100 per request)")
    p.add_argument("--dashboard-interval", type=float, default=15.0,
                   help="Dashboard print interval seconds (default 15)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    skill = args.track.lower()

    books = _load_books_yaml()
    if args.book_id:
        books = [b for b in books if b.get("id") == args.book_id]
        if not books:
            log.error(f"book_id '{args.book_id}' not found")
            return 1

    # Decide targets
    targets = []
    for b in books:
        plan = _plan_for_book(b, skill, args.skip_gates)
        targets.append((b, plan))

    runnable = [(b, p) for b, p in targets if p["action"] == "run"]
    skipped  = [(b, p) for b, p in targets if p["action"] == "skip"]

    log.info(f"track={args.track} total={len(targets)} runnable={len(runnable)} skipped={len(skipped)}")
    if args.dry_run:
        print(f"\n── Plan (track={args.track}, dry-run) ──")
        for b, p in targets:
            print(f"  {b.get('id', '?'):<30} {p['action']:<5} — {p['reason']}")
            if p["action"] == "run":
                print(f"    steps: {p.get('steps', [])}")
        return 0

    if not runnable:
        log.info("Nothing to run.")
        return 0

    ocr_c   = args.ocr_concurrency
    toc_c   = args.toc_concurrency
    skill_c = (args.skill_concurrency if args.skill_concurrency is not None
               else (args.concurrency if args.concurrency is not None else 3))

    # Classify each runnable into its starting stage based on the plan.
    dispatch: list[tuple[BookState, str]] = []
    initial = {"ocr": 0, "toc": 0, "skill": 0}
    for b, p in runnable:
        steps = p.get("steps", [])
        if "ocr" in steps:
            start = "ocr"
        elif "toc_routing" in steps:
            start = "toc"
        else:
            start = "skill"
        state = BookState(
            book=b,
            skill=skill,
            skip_gates=args.skip_gates,
            pages=args.pages,
            pilot_sample=args.pilot_sample,
            ocr_split_pages=args.ocr_split_pages,
            entry=_mk_entry(b, skill, p),
            started=time.time(),
        )
        dispatch.append((state, start))
        initial[start] += 1

    log.info(f"pipeline pools: ocr={ocr_c} toc={toc_c} skill={skill_c}")
    log.info(f"initial dispatch: ocr={initial['ocr']} "
             f"toc={initial['toc']} skill={initial['skill']}")

    pipeline = _Pipeline(ocr_c=ocr_c, toc_c=toc_c, skill_c=skill_c,
                         dashboard_interval=args.dashboard_interval)
    results = pipeline.run(dispatch)

    # Summary
    from collections import Counter
    outcomes = Counter(r.get("outcome", "?") for r in results)
    print(f"\n── Orchestrator Summary (track={args.track}) ──")
    for k, v in outcomes.most_common():
        print(f"  {k:<20} {v}")
    print(f"  processed:           {len(results)}")

    # Return non-zero if any hard failures
    return 1 if outcomes.get(Outcome.FAILED, 0) > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
