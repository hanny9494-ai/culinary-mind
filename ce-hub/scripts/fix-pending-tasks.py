#!/usr/bin/env python3
"""
fix-pending-tasks.py — Match result files to stuck 'pending' DB tasks and mark them done.

Modes:
  1. Match by task_id: result files with matching task_id → mark task done/failed
  2. Age timeout:  --expire-hours N  → mark pending tasks older than N hours as 'dead_letter'

Usage:
  python3 fix-pending-tasks.py [--db PATH] [--results-dir PATH] [--dry-run] [-v]
  python3 fix-pending-tasks.py --expire-hours 24 [--dry-run]

Default paths:
  --db          ~/culinary-mind/.ce-hub/ce-hub.db
  --results-dir ~/culinary-mind/.ce-hub/results/
"""
import argparse
import glob
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

CE_HUB_CWD = os.environ.get("CE_HUB_CWD", os.path.expanduser("~/culinary-mind"))
DEFAULT_DB = os.path.join(CE_HUB_CWD, ".ce-hub", "ce-hub.db")
DEFAULT_RESULTS = os.path.join(CE_HUB_CWD, ".ce-hub", "results")


def parse_args():
    p = argparse.ArgumentParser(description="Fix stuck pending tasks in ce-hub DB")
    p.add_argument("--db", default=DEFAULT_DB, help=f"SQLite DB path (default: {DEFAULT_DB})")
    p.add_argument("--results-dir", default=DEFAULT_RESULTS, help=f"Results dir (default: {DEFAULT_RESULTS})")
    p.add_argument("--dry-run", action="store_true", help="Don't write to DB, just report")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    p.add_argument("--expire-hours", type=float, default=None,
                   help="Mark pending tasks older than N hours as dead_letter (in addition to result matching)")
    return p.parse_args()


def load_results(results_dir: str, verbose: bool) -> dict:
    """Load all result JSON files, indexed by task_id."""
    results_by_task: dict = {}

    if not os.path.isdir(results_dir):
        print(f"[warn] results dir not found: {results_dir}", file=sys.stderr)
        return results_by_task

    files = sorted(glob.glob(os.path.join(results_dir, "*.json")))
    if verbose:
        print("\n=== Result files and their task_ids ===")

    for fpath in files:
        try:
            with open(fpath) as f:
                data = json.load(f)
            task_id = data.get("task_id")
            if verbose:
                print(f"  {os.path.basename(fpath):52s}  task_id={task_id or '(none)':40s}  "
                      f"from={data.get('from','?')}  status={data.get('status','?')}")
            if task_id:
                results_by_task[task_id] = data
        except Exception as e:
            print(f"[warn] failed to read {fpath}: {e}", file=sys.stderr)

    return results_by_task


def fix_pending_tasks(db_path: str, results_by_task: dict, expire_hours: float | None,
                      dry_run: bool, verbose: bool) -> dict:
    stats = {"found_pending": 0, "matched": 0, "updated_match": 0,
             "expired": 0, "updated_expire": 0, "unmatched": 0}

    if not os.path.exists(db_path):
        print(f"[error] DB not found: {db_path}", file=sys.stderr)
        return stats

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("SELECT * FROM tasks WHERE status = 'pending'")
    pending = cur.fetchall()
    stats["found_pending"] = len(pending)

    print(f"\nFound {len(pending)} pending tasks in DB")
    if not pending:
        con.close()
        return stats

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    expire_ms = int(expire_hours * 3600 * 1000) if expire_hours else None

    for row in pending:
        task_id = row["id"]
        title = row["title"]
        created_at = row["created_at"] or 0
        age_ms = now_ms - created_at
        age_h = age_ms / 3_600_000

        if task_id in results_by_task:
            result = results_by_task[task_id]
            result_status = result.get("status", "done")
            db_status = "done" if result_status in ("done", "partial") else "failed"
            stats["matched"] += 1

            if verbose:
                print(f"  [match] {task_id[:20]}... '{title[:50]}' age={age_h:.1f}h → {db_status}")

            if not dry_run:
                cur.execute(
                    "UPDATE tasks SET status=?, result=?, completed_at=? WHERE id=?",
                    (db_status,
                     json.dumps({
                         "summary": result.get("summary", ""),
                         "output_files": result.get("output_files", []),
                         "status": result_status,
                     }),
                     now_ms, task_id),
                )
                stats["updated_match"] += 1

        elif expire_ms and age_ms > expire_ms:
            stats["expired"] += 1
            if verbose:
                print(f"  [expire] {task_id[:20]}... '{title[:50]}' age={age_h:.1f}h → dead_letter")
            if not dry_run:
                cur.execute(
                    "UPDATE tasks SET status='dead_letter', error=?, completed_at=? WHERE id=?",
                    (f"Expired after {age_h:.1f}h with no result", now_ms, task_id),
                )
                stats["updated_expire"] += 1

        else:
            stats["unmatched"] += 1
            if verbose:
                print(f"  [skip]   {task_id[:20]}... '{title[:50]}' age={age_h:.1f}h")

    if not dry_run:
        con.commit()
        print(f"Committed {stats['updated_match']} match-updates + {stats['updated_expire']} expiry-updates to DB")
    else:
        print(f"[dry-run] would update: {stats['matched']} matched + {stats['expired']} expired")

    con.close()
    return stats


def main():
    args = parse_args()

    results_by_task = load_results(args.results_dir, args.verbose)
    print(f"Loaded {len(results_by_task)} results with explicit task_ids")

    stats = fix_pending_tasks(args.db, results_by_task, args.expire_hours,
                              args.dry_run, args.verbose)

    print(f"\nSummary:")
    print(f"  Pending tasks in DB  : {stats['found_pending']}")
    print(f"  Matched to results   : {stats['matched']}")
    print(f"  Updated (matched)    : {stats['updated_match']}")
    if args.expire_hours:
        print(f"  Expired (>{args.expire_hours:.0f}h)      : {stats['expired']}")
        print(f"  Updated (expired)    : {stats['updated_expire']}")
    print(f"  Unmatched            : {stats['unmatched']}")

    if stats["unmatched"] > 0 and not args.verbose:
        print("\n  (run with -v to see all task IDs)")


if __name__ == "__main__":
    main()
