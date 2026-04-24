#!/bin/bash
# batch_prep_zh.sh — 等待OCR完成，重命名目录到正确book_id，然后批量跑prep step4+5
# 用法: caffeinate -s nohup bash pipeline/prep/batch_prep_zh.sh > logs/batch_prep_zh.log 2>&1 &

set -euo pipefail
cd "$(dirname "$0")/../.."  # repo root

PYTHON="python3"
BOOKS_CONFIG="config/books.yaml"
TOC_CONFIG="config/mc_toc.json"
API_CONFIG="config/api.yaml"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ── Step 1: 等 OCR batch 完成 ──────────────────────────────────────────────────
wait_for_ocr() {
  log "Waiting for OCR batch to finish..."
  while pgrep -f "batch_ocr_zh.sh" > /dev/null 2>&1; do
    sleep 30
  done
  log "OCR batch done."
}

# ── Step 2: 重命名 OCR 输出目录 → 正确 book_id ────────────────────────────────
rename_dirs() {
  log "Renaming directories to correct book_ids..."

  declare -A RENAME_MAP=(
    ["shijing_api"]="shijing"
    ["xianggang_yanxi"]="hk_yuecan_yanxi"
    ["zhuji_m6"]="zhujixiaoguan_v6b"
    ["zhongguo_guangdong"]="zhongguo_caipu_guangdong"
    ["guangdong_peng"]="guangdong_pengtiao_quanshu"
    ["zhuji_diannxin"]="zhujixiaoguan_dimsim2"
    ["zhongguo_meixi"]="zhongguo_yinshi_meixueshi"
    ["chuantong_yuecai"]="chuantong_yc"
    ["yuecai_zhenwei"]="yuecan_zhenwei_meat"
    ["zhuji_4"]="zhujixiaoguan_4"
    ["fenbujiejie"]="fenbuxiangjiena_yc"
    ["zhuji_3"]="zhujixiaoguan_3"
    ["gufa_yuecai"]="gufa_yc"
    ["zhuji_2"]="zhujixiaoguan_2"
    ["zhuji_jiachangcai"]="zhujixiaoguan_6"
  )

  for old_id in "${!RENAME_MAP[@]}"; do
    new_id="${RENAME_MAP[$old_id]}"
    old_dir="output/${old_id}"
    new_dir="output/${new_id}"
    if [ -d "$old_dir" ] && [ ! -d "$new_dir" ]; then
      mv "$old_dir" "$new_dir"
      log "Renamed: ${old_id} → ${new_id}"
    elif [ -d "$old_dir" ] && [ -d "$new_dir" ]; then
      # Both exist — copy merged.md if new dir doesn't have it
      if [ -f "${old_dir}/merged.md" ] && [ ! -f "${new_dir}/merged.md" ]; then
        cp "${old_dir}/merged.md" "${new_dir}/merged.md"
        log "Copied merged.md: ${old_id} → ${new_id}"
      fi
    elif [ ! -d "$old_dir" ]; then
      log "Skip rename: ${old_id} not found"
    fi
  done
}

# ── Step 3: 为每本书准备 prep/raw_merged.md ────────────────────────────────────
setup_prep_dir() {
  local book_id="$1"
  local merged="output/${book_id}/merged.md"
  local prep_dir="output/${book_id}/prep"
  local raw_merged="${prep_dir}/raw_merged.md"

  if [ ! -f "$merged" ]; then
    log "SKIP ${book_id}: merged.md not found"
    return 1
  fi
  if [ -f "$raw_merged" ]; then
    log "OK ${book_id}: raw_merged.md already exists"
    return 0
  fi
  mkdir -p "$prep_dir"
  cp "$merged" "$raw_merged"
  log "Setup ${book_id}: copied merged.md → prep/raw_merged.md"
  return 0
}

# ── Step 4: 跑 prep pipeline step4+5 ──────────────────────────────────────────
run_prep() {
  local book_id="$1"
  local prep_dir="output/${book_id}/prep"
  local chunks="output/${book_id}/prep/chunks_smart.json"

  if [ -f "$chunks" ]; then
    log "SKIP prep ${book_id}: chunks_smart.json already exists"
    return
  fi

  log "Running prep step4+5 for: ${book_id}"
  $PYTHON -u pipeline/prep/pipeline.py \
    --book-id "$book_id" \
    --config "$API_CONFIG" \
    --books "$BOOKS_CONFIG" \
    --toc "$TOC_CONFIG" \
    --output-dir "$prep_dir" \
    --start-step 4 \
    --stop-step 5
  log "DONE prep: ${book_id} → ${chunks}"
}

# ── 书单（按 books.yaml 正确 ID，小→大）─────────────────────────────────────────
ZH_BOOKS=(
  "hk_yuecan_yanxi"
  "zhujixiaoguan_v6b"
  "zhongguo_caipu_guangdong"
  "guangdong_pengtiao_quanshu"
  "zhujixiaoguan_dimsim2"
  "zhongguo_yinshi_meixueshi"
  "chuantong_yc"
  "yuecan_zhenwei_meat"
  "zhujixiaoguan_4"
  "fenbuxiangjiena_yc"
  "zhujixiaoguan_3"
  "gufa_yc"
  "zhujixiaoguan_2"
  "zhujixiaoguan_6"
  "shijing"
  # EPUBs (yuecai_wangliang, xidage_xunwei_hk) handled separately after ebook-convert
)

# ── Main ───────────────────────────────────────────────────────────────────────
wait_for_ocr
rename_dirs

log "=== Starting prep pipeline for ${#ZH_BOOKS[@]} books ==="
for book_id in "${ZH_BOOKS[@]}"; do
  if setup_prep_dir "$book_id"; then
    run_prep "$book_id"
  fi
done

log "=== All done ==="
log "Chunks created:"
for book_id in "${ZH_BOOKS[@]}"; do
  chunks="output/${book_id}/prep/chunks_smart.json"
  if [ -f "$chunks" ]; then
    count=$(python3 -c "import json; d=json.load(open('$chunks')); print(len(d))" 2>/dev/null || echo "?")
    log "  ✓ ${book_id}: ${count} chunks"
  else
    log "  ✗ ${book_id}: missing"
  fi
done

# ── EPUB 转换后续处理（在 main 批次之后运行）──────────────────────────────────
handle_epub_books() {
  local epub_books=("yuecai_wangliang" "xidage_xunwei_hk")

  for book_id in "${epub_books[@]}"; do
    local pdf_path="output/${book_id}/source.pdf"

    # Wait for PDF conversion
    log "Waiting for EPUB→PDF: ${book_id}..."
    while [ ! -f "$pdf_path" ]; do sleep 10; done
    # Wait until file size stabilizes
    local size1=0; local size2=1
    while [ "$size1" != "$size2" ]; do
      size1=$(stat -f%z "$pdf_path" 2>/dev/null || echo 0)
      sleep 5
      size2=$(stat -f%z "$pdf_path" 2>/dev/null || echo 0)
    done
    log "PDF ready: ${book_id} ($(du -sh $pdf_path | cut -f1))"

    # OCR
    if [ ! -f "output/${book_id}/merged.md" ]; then
      log "OCR: ${book_id}"
      python3 -u pipeline/prep/paddleocr_api.py \
        --pdf "$pdf_path" \
        --output-dir "output/${book_id}" \
        --split-pages 80
    else
      log "OCR SKIP: ${book_id} merged.md exists"
    fi

    # Prep
    if setup_prep_dir "$book_id"; then
      run_prep "$book_id"
    fi
  done
}

handle_epub_books
log "=== EPUB books also done ==="
