#!/bin/bash
# batch_ocr_zh.sh — 批量跑中文书 OCR (AI Studio layout-parsing API)
# 用法: bash pipeline/prep/batch_ocr_zh.sh
# 所有书顺序处理，断点续跑（merged.md 已存在则跳过）

set -e
cd "$(dirname "$0")/../.."   # repo root

BOOKS_DIR="/Users/jeff/Documents/粤菜中菜审美书籍"
OCR_SCRIPT="pipeline/prep/paddleocr_api.py"
PYTHON="python3"
SPLIT=80   # pages per API chunk

run_ocr() {
  local book_id="$1"
  local pdf_path="$2"
  local out_dir="output/${book_id}"

  if [ -f "${out_dir}/merged.md" ]; then
    echo "[skip] ${book_id} — merged.md already exists"
    return
  fi

  echo ""
  echo "========================================"
  echo "[ocr] START: ${book_id}"
  echo "[ocr] PDF: ${pdf_path}"
  echo "========================================"
  mkdir -p "${out_dir}"
  $PYTHON -u "$OCR_SCRIPT" \
    --pdf "$pdf_path" \
    --output-dir "$out_dir" \
    --split-pages $SPLIT
  echo "[ocr] DONE: ${book_id} → ${out_dir}/merged.md"
}

# ── PDF 书单（按文件大小从小到大）──────────────────────────────
run_ocr "xianggang_yanxi"     "$BOOKS_DIR/香港粵菜筵席譜 (鲁夫) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "zhuji_m6"           "$BOOKS_DIR/珠璣小館家馔6 (江獻珠) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "zhongguo_guangdong" "$BOOKS_DIR/中国菜谱 广东 (《中国菜谱》编写组编) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "guangdong_peng"     "$BOOKS_DIR/廣東菜烹調全書 (陳淑儀) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "zhuji_diannxin"     "$BOOKS_DIR/珠璣小館：中國點心2 (江獻珠) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "zhongguo_meixi"     "$BOOKS_DIR/中国饮食美学史 (赵建军著, 赵建军, 1958- author, Zhao Jianjun zhu etc.) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "chuantong_yuecai"   "$BOOKS_DIR/传统粤菜精华录 (陈梦因，江献珠著) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "yuecai_zhenwei"     "$BOOKS_DIR/粤菜真味：肉食篇 (江献珠) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "zhuji_4"            "$BOOKS_DIR/珠璣小館家饌4 (江獻珠) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "fenbujiejie"        "$BOOKS_DIR/分步詳解-南粵家鄉菜 (江獻珠) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "zhuji_3"            "$BOOKS_DIR/珠璣小館家饌3 (江獻珠) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "gufa_yuecai"        "$BOOKS_DIR/古法粤菜新谱 (陈梦因, 江献珠) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "zhuji_2"            "$BOOKS_DIR/珠璣小館家馔2 (江獻珠) (z-library.sk, 1lib.sk, z-lib.sk).pdf"
run_ocr "zhuji_jiachangcai"  "$BOOKS_DIR/珠璣小館家常菜譜 （第六集） (江献珠) (z-library.sk, 1lib.sk, z-lib.sk).pdf"

echo ""
echo "========================================"
echo "All PDFs done. 2 EPUBs need manual conversion first:"
echo "  粤菜（王亮）.epub → ebook-convert ... yuecai_wangliang.pdf"
echo "  西打哥的尋味香港.epub → ebook-convert ... xidage.pdf"
echo "Then run: run_ocr yuecai_wangliang / run_ocr xidage"
echo "========================================"
