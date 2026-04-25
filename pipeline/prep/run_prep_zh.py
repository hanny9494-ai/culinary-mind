#!/usr/bin/env python3
"""run_prep_zh.py — 串行跑所有中文书 prep step4+5 (chunking + annotation)
用法: caffeinate -s nohup python3 -u pipeline/prep/run_prep_zh.py > logs/run_prep_zh.log 2>&1 &
"""
import os, subprocess, sys, shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
os.chdir(REPO)

BOOKS = [
    "shijing",
    "hk_yuecan_yanxi",
    "zhujixiaoguan_v6b",
    "zhongguo_caipu_guangdong",
    "guangdong_pengtiao_quanshu",
    "zhujixiaoguan_dimsim2",
    "zhongguo_yinshi_meixueshi",
    "chuantong_yc",
    "yuecan_zhenwei_meat",
    "zhujixiaoguan_4",
    "fenbuxiangjiena_yc",
    "zhujixiaoguan_3",
    "gufa_yc",
    "zhujixiaoguan_2",
    "zhujixiaoguan_6",
    # EPUBs added after conversion:
    "yuecai_wangliang",
    "xidage_xunwei_hk",
]

def log(msg):
    import time
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def setup_raw_merged(book_id):
    merged = REPO / f"output/{book_id}/merged.md"
    prep_dir = REPO / f"output/{book_id}/prep"
    raw = prep_dir / "raw_merged.md"
    if not merged.exists():
        log(f"SKIP {book_id}: merged.md not found")
        return False
    prep_dir.mkdir(parents=True, exist_ok=True)
    if not raw.exists():
        shutil.copy(merged, raw)
        log(f"Copied merged.md → prep/raw_merged.md for {book_id}")
    return True

def run_prep(book_id):
    chunks = REPO / f"output/{book_id}/prep/chunks_smart.json"
    if chunks.exists():
        log(f"SKIP {book_id}: chunks_smart.json already exists")
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
        import json
        try:
            n = len(json.loads(chunks.read_text()))
            log(f"DONE {book_id}: {n} chunks")
        except:
            log(f"DONE {book_id}")
        return True
    else:
        log(f"FAILED {book_id}: exit code {result.returncode}")
        return False

if __name__ == "__main__":
    log(f"=== Starting prep for {len(BOOKS)} books ===")
    ok, skip, fail = 0, 0, 0
    for book_id in BOOKS:
        if not setup_raw_merged(book_id):
            skip += 1; continue
        success = run_prep(book_id)
        if success: ok += 1
        else: fail += 1
    log(f"=== Done: {ok} OK, {skip} skipped, {fail} failed ===")
