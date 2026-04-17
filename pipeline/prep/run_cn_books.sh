#!/usr/bin/env bash
# run_cn_books.sh — Batch OCR all Chinese books (language: zh, l0_status: pending)
#
# Usage:
#   bash pipeline/prep/run_cn_books.sh [--dry-run] [--book-id shijing]
#
# What it does:
#   1. Reads config/books.yaml for books where language=zh AND l0_status=pending
#   2. Skips EPUB books (needs manual conversion to PDF first)
#   3. For each eligible PDF: runs paddleocr_vl.py → output/{book_id}/
#   4. On success, marks l0_status=running in books.yaml (human updates to done when pipeline finishes)
#
# Expected runtime: 17 books × ~300 pages × ~30s/page ≈ 42h single-threaded
# VL model loads once and stays in memory across pages (sequential per-page).
#
# Interrupt: Ctrl+C will save progress for the current book (resume-safe).
# Resume: re-run the script; already-processed pages are skipped.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BOOKS_YAML="$REPO_ROOT/config/books.yaml"
OCR_SCRIPT="$REPO_ROOT/pipeline/prep/paddleocr_vl.py"
OUTPUT_ROOT="$REPO_ROOT/output"
PYTHON="/Users/jeff/miniforge3/bin/python3"
LOG_DIR="$REPO_ROOT/output/cn_ocr_logs"

mkdir -p "$LOG_DIR"

# ── Flags ──────────────────────────────────────────────────────────────────────
DRY_RUN=false
ONLY_BOOK=""

for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN=true ;;
    --book-id=*) ONLY_BOOK="${arg#--book-id=}" ;;
    *)           echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done

export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

# ── Parse books.yaml with Python ───────────────────────────────────────────────
BOOK_LIST=$($PYTHON - "$BOOKS_YAML" "$ONLY_BOOK" << 'PYEOF'
import sys, yaml, pathlib

yaml_path = pathlib.Path(sys.argv[1])
only_id = sys.argv[2] if len(sys.argv) > 2 else ""

with open(yaml_path) as f:
    data = yaml.safe_load(f)

for book in data.get("books", []):
    lang = book.get("language", "en")
    l0_status = book.get("l0_status", "done")
    fmt = book.get("format", "pdf")
    book_id = book.get("id", "")

    if lang != "zh":
        continue
    if l0_status not in ("pending",):
        continue
    if fmt == "epub":
        print(f"SKIP_EPUB\t{book_id}\t{book.get('title','')}\t{book.get('source_path','')}", flush=True)
        continue
    if only_id and book_id != only_id:
        continue

    src = book.get("source_path", "")
    print(f"PDF\t{book_id}\t{book.get('title','')}\t{src}", flush=True)
PYEOF
)

# ── Process each book ──────────────────────────────────────────────────────────
echo "=== run_cn_books.sh ==="
echo "repo:   $REPO_ROOT"
echo "books:  $BOOKS_YAML"
echo ""

DONE_COUNT=0
SKIP_COUNT=0
FAIL_COUNT=0

while IFS=$'\t' read -r type book_id title source_path; do
  if [[ "$type" == "SKIP_EPUB" ]]; then
    echo "⏭  SKIP (EPUB) [$book_id] $title"
    echo "   → Convert first: ebook-convert '$source_path' /tmp/${book_id}.pdf"
    SKIP_COUNT=$((SKIP_COUNT + 1))
    continue
  fi

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📖 [$book_id] $title"
  echo "   PDF: $source_path"

  if [[ ! -f "$source_path" ]]; then
    echo "   ❌ ERROR: PDF not found: $source_path"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    continue
  fi

  OUTPUT_DIR="$OUTPUT_ROOT/$book_id"
  LOG_FILE="$LOG_DIR/${book_id}_$(date +%Y%m%d_%H%M%S).log"

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "   [dry-run] would run: python3 paddleocr_vl.py --pdf '$source_path' --output-dir '$OUTPUT_DIR'"
    continue
  fi

  mkdir -p "$OUTPUT_DIR"
  echo "   output: $OUTPUT_DIR"
  echo "   log:    $LOG_FILE"
  echo "   start:  $(date '+%Y-%m-%d %H:%M:%S')"

  set +e
  PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    "$PYTHON" "$OCR_SCRIPT" \
      --pdf "$source_path" \
      --output-dir "$OUTPUT_DIR" \
      2>&1 | tee "$LOG_FILE"
  EXIT_CODE=$?
  set -e

  if [[ $EXIT_CODE -eq 0 ]]; then
    echo "   ✅ done: $(date '+%Y-%m-%d %H:%M:%S')"
    DONE_COUNT=$((DONE_COUNT + 1))
  elif [[ $EXIT_CODE -eq 130 ]]; then
    echo "   ⚠️  interrupted — progress saved, re-run to resume"
    exit 130
  else
    echo "   ❌ FAILED (exit $EXIT_CODE) — check $LOG_FILE"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi

done <<< "$BOOK_LIST"

echo ""
echo "=== Summary ==="
echo "  done:    $DONE_COUNT"
echo "  skipped: $SKIP_COUNT (EPUB — convert manually first)"
echo "  failed:  $FAIL_COUNT"
echo ""
if [[ $SKIP_COUNT -gt 0 ]]; then
  echo "EPUB conversion command:"
  echo "  ebook-convert '/path/to/book.epub' '/tmp/book.pdf'"
  echo "  Then re-run with: bash run_cn_books.sh --book-id=<id>"
fi
