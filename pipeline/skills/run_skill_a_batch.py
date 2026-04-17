#!/usr/bin/env python3
"""
pipeline/skills/run_skill_a_batch.py
Skill A 批量调度器 — 按4批顺序跑全量科学参数提取

Usage:
    python run_skill_a_batch.py --batch 1a
    python run_skill_a_batch.py --batch 1b --dry-run
    python run_skill_a_batch.py --all
    nohup python run_skill_a_batch.py --all > /tmp/skill_a_all.log 2>&1 &

Batches:
    1a  — 恢复批（已有 skill_a/ 进度，优先完成）
    1b  — 科学重炮（高密度工程/化学教材）
    1c  — 中等密度
    1d  — 精选长尾（>15 A-pages）

Each book is run via:
    python run_skill.py --skill a --book-id <id> --concurrency 3 --resume

Output:
    output/{book_id}/skill_a/results.jsonl
    output/{book_id}/skill_a/_progress.json
    output/{book_id}/skill_a/_run.log
"""

import os, sys, json, time, subprocess, argparse, logging
from pathlib import Path
from datetime import datetime

# ── Proxy bypass ──────────────────────────────────────────────────────────────
for k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(k, None)
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

REPO_ROOT  = Path(__file__).resolve().parents[2]
SKILLS_DIR = Path(__file__).resolve().parent
RUN_SKILL  = SKILLS_DIR / "run_skill.py"
OUTPUT_DIR = REPO_ROOT / "output"

# ── Batch definitions ─────────────────────────────────────────────────────────

BATCHES: dict[str, list[str]] = {
    "1a": [
        # 恢复批 — already have skill_a/ dir with partial progress
        "singh_food_engineering",
        "jay_food_microbiology",
        "bread_science_yoshino",
        "mc_vol3",
        "mc_vol2",
        "flavorama",
        "koji_alchemy",
        "handbook_molecular_gastronomy",
    ],
    "1b": [
        # 科学重炮 — high-density engineering / chemistry textbooks
        "heldman_handbook_food_engineering",
        "belitz_food_chemistry",
        "toledo_food_process_engineering",
        "fennema_food_chemistry",
        "deman_food_chemistry",
    ],
    "1c": [
        # 中等密度
        "dashi_umami",
        "bourne_food_texture",
        "ofc",
        "ice_cream_flavor",
        "mc_vol1",
        "mc_vol4",
    ],
    "1d": [
        # 精选长尾 — >15 A-pages
        "french_sauces",
        "cooking_for_geeks",
        "flavor_bible",
        "shijing",
        "essentials_food_science",
        "molecular_gastronomy",
        "food_lab",
        "mouthfeel",
        "french_patisserie",
        "science_good_cooking",
        "flavor_equation",
        "modernist_pizza",
    ],
}

BATCH_ORDER = ["1a", "1b", "1c", "1d"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def setup_logging(log_path: Path) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("skill_a_batch")


def get_book_status(book_id: str) -> dict:
    """Return current progress for a book's Skill A extraction."""
    skill_dir = OUTPUT_DIR / book_id / "skill_a"
    progress_path = skill_dir / "_progress.json"
    signals_path  = OUTPUT_DIR / book_id / "signals.json"

    status = {
        "book_id":     book_id,
        "has_signals": signals_path.exists(),
        "has_skill_a": skill_dir.exists(),
        "done":        0,
        "total":       0,
        "failed":      0,
        "pct":         0.0,
        "complete":    False,
    }

    # Count A-signal pages
    if signals_path.exists():
        try:
            sigs = json.loads(signals_path.read_text())
            a_pages = [s for s in sigs if s.get("signals", {}).get("A") and not s.get("skip_reason")]
            status["total"] = len(a_pages)
        except Exception:
            pass

    # Load progress
    if progress_path.exists():
        try:
            prog = json.loads(progress_path.read_text())
            status["done"]   = prog.get("done", 0)
            status["failed"] = prog.get("failed", 0)
            if status["total"] > 0:
                status["pct"] = round(status["done"] / status["total"] * 100, 1)
            status["complete"] = (status["done"] >= status["total"] > 0)
        except Exception:
            pass

    return status


def print_plan(batches_to_run: list[str], log: logging.Logger) -> None:
    """Print execution plan with current progress for each book."""
    log.info("=" * 60)
    log.info("Skill A Batch Plan")
    log.info("=" * 60)
    total_books = 0
    total_pages = 0
    for batch_id in batches_to_run:
        books = BATCHES[batch_id]
        log.info(f"\n── Batch {batch_id} ({len(books)} books) ──")
        for book_id in books:
            st = get_book_status(book_id)
            signals_ok = "✓" if st["has_signals"] else "✗ NO signals.json"
            prog_str   = f"{st['done']}/{st['total']} ({st['pct']}%)" if st["total"] else "no A-pages"
            done_str   = " [COMPLETE]" if st["complete"] else ""
            log.info(f"  {book_id:<45} [{signals_ok}] {prog_str}{done_str}")
            if not st["complete"] and st["has_signals"]:
                total_books += 1
                total_pages += max(0, st["total"] - st["done"])
    log.info(f"\nPending: {total_books} books, ~{total_pages} A-pages to process")
    log.info("=" * 60)


def run_book(book_id: str, dry_run: bool, log: logging.Logger) -> dict:
    """
    Run Skill A for one book via run_skill.py subprocess.
    Returns result dict with status and timing.
    """
    st = get_book_status(book_id)

    if not st["has_signals"]:
        log.warning(f"[{book_id}] SKIP — signals.json not found")
        return {"book_id": book_id, "status": "skip_no_signals", "elapsed": 0}

    if st["complete"]:
        log.info(f"[{book_id}] SKIP — already complete ({st['done']}/{st['total']} pages)")
        return {"book_id": book_id, "status": "already_done", "elapsed": 0}

    remaining = max(0, st["total"] - st["done"])
    log.info(f"[{book_id}] START — {remaining} pages remaining ({st['done']}/{st['total']} done)")

    if dry_run:
        log.info(f"[{book_id}] DRY-RUN — would run: python run_skill.py --skill a --book-id {book_id} --concurrency 3 --resume")
        return {"book_id": book_id, "status": "dry_run", "elapsed": 0}

    cmd = [
        sys.executable, str(RUN_SKILL),
        "--skill", "a",
        "--book-id", book_id,
        "--concurrency", "3",
        "--resume",
    ]

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(SKILLS_DIR),
            timeout=7200,        # 2 h max per book
            check=False,
        )
        elapsed = time.time() - t0
        rc = result.returncode
        if rc == 0:
            # Re-check progress after run
            st2 = get_book_status(book_id)
            log.info(
                f"[{book_id}] DONE — exit={rc}, {elapsed:.0f}s, "
                f"progress={st2['done']}/{st2['total']} ({st2['pct']}%)"
            )
            return {"book_id": book_id, "status": "done", "elapsed": elapsed,
                    "done": st2["done"], "total": st2["total"], "pct": st2["pct"]}
        else:
            log.error(f"[{book_id}] FAILED — exit={rc}, {elapsed:.0f}s")
            return {"book_id": book_id, "status": "failed", "exit_code": rc, "elapsed": elapsed}
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        log.error(f"[{book_id}] TIMEOUT — {elapsed:.0f}s")
        return {"book_id": book_id, "status": "timeout", "elapsed": elapsed}
    except Exception as e:
        elapsed = time.time() - t0
        log.error(f"[{book_id}] ERROR — {e}")
        return {"book_id": book_id, "status": "error", "error": str(e), "elapsed": elapsed}


def print_batch_summary(batch_id: str, results: list[dict], elapsed: float, log: logging.Logger) -> None:
    done    = sum(1 for r in results if r["status"] == "done")
    skipped = sum(1 for r in results if r["status"] in ("already_done", "skip_no_signals", "dry_run"))
    failed  = sum(1 for r in results if r["status"] in ("failed", "timeout", "error"))
    total_new_pages = sum(r.get("done", 0) - r.get("done", 0) for r in results)  # approx

    log.info(f"\n{'='*60}")
    log.info(f"Batch {batch_id} Summary  ({elapsed:.0f}s)")
    log.info(f"{'='*60}")
    log.info(f"  done:    {done}")
    log.info(f"  skipped: {skipped}")
    log.info(f"  failed:  {failed}")
    for r in results:
        icon = {"done": "✓", "already_done": "–", "skip_no_signals": "⚠",
                "failed": "✗", "timeout": "⏱", "error": "✗", "dry_run": "○"}.get(r["status"], "?")
        extra = f" {r.get('done', '')}/{r.get('total', '')} ({r.get('pct', '')}%)" if r.get("total") else ""
        log.info(f"  {icon} {r['book_id']:<45} [{r['status']}]{extra}")
    log.info(f"{'='*60}\n")

# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Skill A Batch Runner — orchestrate Skill A extraction across book batches"
    )
    p.add_argument(
        "--batch", choices=BATCH_ORDER,
        help="Run a specific batch (1a / 1b / 1c / 1d)"
    )
    p.add_argument(
        "--all", action="store_true",
        help="Run all batches in order: 1a → 1b → 1c → 1d"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print plan without executing"
    )
    p.add_argument(
        "--log", default=None,
        help="Log file path (default: /tmp/skill_a_batch_<timestamp>.log)"
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.batch and not args.all:
        print("ERROR: Provide --batch 1a/1b/1c/1d or --all", file=sys.stderr)
        sys.exit(1)

    # Log file
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_path = Path(args.log) if args.log else Path(f"/tmp/skill_a_batch_{ts}.log")
    log = setup_logging(log_path)
    log.info(f"Skill A Batch Runner started — log: {log_path}")

    batches_to_run = BATCH_ORDER if args.all else [args.batch]
    dry_run = args.dry_run

    if dry_run:
        log.info("[DRY-RUN mode — no API calls will be made]")

    # Print full plan upfront
    print_plan(batches_to_run, log)

    # Execute batches
    all_results: dict[str, list[dict]] = {}
    grand_t0 = time.time()

    for batch_id in batches_to_run:
        books = BATCHES[batch_id]
        log.info(f"\n{'#'*60}")
        log.info(f"# Starting Batch {batch_id} — {len(books)} books")
        log.info(f"{'#'*60}")

        batch_t0 = time.time()
        batch_results: list[dict] = []

        for book_id in books:
            result = run_book(book_id, dry_run=dry_run, log=log)
            batch_results.append(result)
            # Brief pause between books to avoid hammering the API
            if result["status"] not in ("already_done", "skip_no_signals", "dry_run"):
                time.sleep(2)

        batch_elapsed = time.time() - batch_t0
        print_batch_summary(batch_id, batch_results, batch_elapsed, log)
        all_results[batch_id] = batch_results

    # Grand summary
    grand_elapsed = time.time() - grand_t0
    log.info(f"\n{'='*60}")
    log.info(f"ALL BATCHES COMPLETE — total {grand_elapsed:.0f}s ({grand_elapsed/3600:.2f}h)")
    log.info(f"{'='*60}")
    for batch_id in batches_to_run:
        results = all_results[batch_id]
        done    = sum(1 for r in results if r["status"] == "done")
        failed  = sum(1 for r in results if r["status"] in ("failed", "timeout", "error"))
        log.info(f"  Batch {batch_id}: {done}/{len(results)} done, {failed} failed")
    log.info(f"\nLog saved to: {log_path}")


if __name__ == "__main__":
    main()
