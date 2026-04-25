#!/bin/bash
# Batch re-run toc_router for all 24 Skill A books
# Uses new Scale-up Test prompt, --force overwrites old signals.json
# Results logged to output/{book_id}/toc_router_v2.log

PYTHON="/Users/jeff/miniforge3/bin/python3"
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TOC_ROUTER="$SCRIPT_DIR/pipeline/skills/toc_router.py"
LOG_DIR="$SCRIPT_DIR/output"

BOOKS=(
  mc_vol1 mc_vol2 mc_vol3 mc_vol4
  chocolates_confections science_of_chocolate molecular_gastronomy
  mouthfeel cooking_for_geeks essentials_food_science ofc
  ice_cream_flavor bread_science_yoshino van_boekel_kinetic_modeling
  rao_engineering_properties singh_food_engineering toledo_food_process_engineering
  fennema_food_chemistry belitz_food_chemistry heldman_handbook_food_engineering
  sahin_physical_properties bourne_food_texture jay_food_microbiology deman_food_chemistry
)

TOTAL=${#BOOKS[@]}
echo "$(date) Starting batch toc_router for $TOTAL books"
echo "=========================================="

DONE=0
FAIL=0
for BOOK in "${BOOKS[@]}"; do
  DONE=$((DONE+1))
  echo ""
  echo "[$DONE/$TOTAL] $BOOK — $(date '+%H:%M:%S')"
  $PYTHON "$TOC_ROUTER" --book-id "$BOOK" --force 2>&1 | tee "$LOG_DIR/$BOOK/toc_router_v2.log"
  RC=${PIPESTATUS[0]}
  if [ $RC -ne 0 ]; then
    echo "  ❌ FAILED (exit $RC)"
    FAIL=$((FAIL+1))
  else
    echo "  ✅ done"
  fi
done

echo ""
echo "=========================================="
echo "$(date) Batch complete: $DONE total, $FAIL failed"
