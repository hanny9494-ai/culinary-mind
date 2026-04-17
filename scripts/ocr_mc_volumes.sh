#!/bin/bash
# scripts/ocr_mc_volumes.sh
# OCR multi-volume MC PDFs with correct page merging.
#
# Problem: ocr_claw.py writes pages.json starting from page 1 each time,
# so running multiple parts into the same --out-dir overwrites previous results.
#
# Fix: each part goes to its own temp dir (output/mc_vol{N}/parts/part{M}/),
# then all parts are merged into output/mc_vol{N}/pages.json with sequential
# page numbers via pipeline/utils/merge_part_pages.py.
#
# Usage:
#   bash scripts/ocr_mc_volumes.sh          # process vol 2, 3, 4
#   bash scripts/ocr_mc_volumes.sh 3        # process only vol 3
#   VOLUMES="2 3" bash scripts/ocr_mc_volumes.sh

set -euo pipefail
cd /Users/jeff/culinary-mind

VOLUMES="${1:-2 3 4}"
# Allow VOLUMES env override
VOLUMES="${VOLUMES:-2 3 4}"

for VOL in $VOLUMES; do
  BOOK="mc_vol${VOL}"
  PDF_DIR="output/mc/vol${VOL}/mineru_parts"
  OUT_DIR="output/${BOOK}"
  PARTS_DIR="${OUT_DIR}/parts"

  echo ""
  echo "========================================"
  echo "$(date '+%Y-%m-%d %H:%M:%S'): Starting OCR for $BOOK"
  echo "========================================"
  mkdir -p "$OUT_DIR" "$PARTS_DIR"

  # ── OCR each part into its own subdirectory ──────────────────────────────
  PART=0
  PART_DIRS=()
  for PDF in $(ls "$PDF_DIR"/mc_vol${VOL}_part*.pdf 2>/dev/null | sort); do
    PART=$((PART + 1))
    PART_OUT="${PARTS_DIR}/part${PART}"
    mkdir -p "$PART_OUT"

    echo "  [part${PART}] PDF: $(basename "$PDF") → $PART_OUT"

    # Skip if this part already has a pages.json (resume support)
    if [ -f "${PART_OUT}/pages.json" ]; then
      PAGE_COUNT=$(python3 -c "import json; d=json.load(open('${PART_OUT}/pages.json')); print(len(d))" 2>/dev/null || echo "?")
      echo "  [part${PART}] Already done (${PAGE_COUNT} pages), skipping"
    else
      python3 pipeline/skills/ocr_claw.py \
        --pdf "$PDF" \
        --out-dir "$PART_OUT" \
        --mode api \
        2>&1 | tail -8
    fi

    PART_DIRS+=("$PART_OUT")
  done

  if [ $PART -eq 0 ]; then
    echo "  WARNING: No PDFs found in $PDF_DIR — skipping $BOOK"
    continue
  fi

  echo ""
  echo "  $(date '+%H:%M:%S'): Merging $PART parts into ${OUT_DIR}/pages.json ..."

  # ── Merge all parts into one pages.json with sequential page numbers ─────
  python3 pipeline/utils/merge_part_pages.py \
    --parts-dir "$PARTS_DIR" \
    --out "${OUT_DIR}/pages.json" \
    --book-id "$BOOK"

  echo "  ✓ $BOOK merge complete: $(python3 -c "import json; d=json.load(open('${OUT_DIR}/pages.json')); print(len(d),'pages, range',d[0]['page'],'-',d[-1]['page'])")"
  echo "$(date '+%Y-%m-%d %H:%M:%S'): $BOOK OCR+merge done"
done

echo ""
echo "All volumes done."
