#!/usr/bin/env python3
"""Re-run step5 annotation for 3 failed books (step4 validation failed but chunks_raw.json exists)"""
import os, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
os.chdir(REPO)

BOOKS = ["hk_yuecan_yanxi", "guangdong_pengtiao_quanshu", "zhujixiaoguan_4"]

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def run_step5(book_id):
    chunks_smart = REPO / f"output/{book_id}/prep/prep/chunks_smart.json"
    chunks_raw = REPO / f"output/{book_id}/prep/chunks_raw.json"
    
    if not chunks_raw.exists():
        log(f"SKIP {book_id}: no chunks_raw.json")
        return False
    
    # Check how many chunks done
    if chunks_smart.exists():
        import json
        done = json.loads(chunks_smart.read_text())
        total = json.loads(chunks_raw.read_text())
        log(f"{book_id}: resuming {len(done)}/{len(total)} chunks done")
    else:
        log(f"START {book_id}: fresh step5 annotation")

    env = os.environ.copy()
    env["no_proxy"] = "localhost,127.0.0.1"
    env.pop("http_proxy", None); env.pop("https_proxy", None)
    env.pop("HTTP_PROXY", None); env.pop("HTTPS_PROXY", None)
    env["PYTHONPATH"] = str(REPO / "pipeline")
    
    result = subprocess.run([
        sys.executable, "-u", "pipeline/prep/pipeline.py",
        "--book-id", book_id,
        "--config", "config/api.yaml",
        "--books", "config/books.yaml",
        "--toc", "config/mc_toc.json",
        "--output-dir", f"output/{book_id}/prep",
        "--start-step", "5",
        "--stop-step", "5",
    ], env=env)
    
    if result.returncode == 0:
        import json
        try:
            n = len(json.loads(chunks_smart.read_text()))
            log(f"DONE {book_id}: {n} chunks annotated")
        except:
            log(f"DONE {book_id}")
        return True
    else:
        log(f"FAILED {book_id}: exit code {result.returncode}")
        return False

if __name__ == "__main__":
    log(f"=== Step5 retry for {len(BOOKS)} books ===")
    for book_id in BOOKS:
        run_step5(book_id)
    log("=== Done ===")
