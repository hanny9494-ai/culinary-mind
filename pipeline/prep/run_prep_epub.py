#!/usr/bin/env python3
"""run_prep_epub.py — 跑 2 本 EPUB 转换书的 prep step4+5"""
import os, subprocess, sys, time, json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
os.chdir(REPO)

BOOKS = ["yuecan_wangliang", "xidage_xunwei_hk"]

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def run_prep(book_id):
    chunks = REPO / f"output/{book_id}/prep/prep/chunks_smart.json"
    if chunks.exists():
        log(f"SKIP {book_id}: already done ({len(json.loads(chunks.read_text()))} chunks)")
        return True
    
    log(f"START prep step4+5: {book_id}")
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
        "--start-step", "4",
        "--stop-step", "5",
    ], env=env)
    
    if result.returncode == 0:
        try:
            n = len(json.loads(chunks.read_text()))
            log(f"DONE {book_id}: {n} chunks")
        except:
            log(f"DONE {book_id}")
        return True
    else:
        # Try step5-only if step4 validation failed
        log(f"step4 failed, trying step5-only for {book_id}")
        result2 = subprocess.run([
            sys.executable, "-u", "pipeline/prep/pipeline.py",
            "--book-id", book_id,
            "--config", "config/api.yaml",
            "--books", "config/books.yaml",
            "--toc", "config/mc_toc.json",
            "--output-dir", f"output/{book_id}/prep",
            "--start-step", "5",
            "--stop-step", "5",
        ], env=env)
        if result2.returncode == 0:
            try:
                n = len(json.loads(chunks.read_text()))
                log(f"DONE {book_id} (step5-only): {n} chunks")
            except:
                log(f"DONE {book_id} (step5-only)")
            return True
        else:
            log(f"FAILED {book_id}")
            return False

if __name__ == "__main__":
    log(f"=== Prep for {len(BOOKS)} EPUB books ===")
    for book_id in BOOKS:
        run_prep(book_id)
    log("=== Done ===")
