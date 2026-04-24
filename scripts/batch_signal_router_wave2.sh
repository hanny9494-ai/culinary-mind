#!/bin/bash
cd /Users/jeff/culinary-mind

BOOKS=(
  f2986_baltic
  dokumen.pub_the-whole-fish-cookbook-new-
  organum_nature_texture_intensity_purity
  crave
  core_-_clare_smyth
  momofuku
  f1749_manresa
  the-french-laundry-cookbook-978157965126
  the_hand_and_flowers_cookbook
  bouchon_-_thomas_keller
  japanese_farm_food_-_nancy_singleton_hac
  relae_a_book_of_ideas_-_christian_f_pugl
  alinea_-_grant_achatz
  daniel_my_french_cuisine_-_daniel_boulud
  eleven_madison_park_the_next_chapter_紫色封
  the_everlasting_meal_cookbook_leftovers_
  eleven_madison_park_the_cookbook_-_danie
  meat_illustrated_a_foolproof_guide_to_un
)

TOTAL=${#BOOKS[@]}
COUNT=0

echo "$(date): Wave 2 — $TOTAL old-format books"
echo "============================================"

for BOOK in "${BOOKS[@]}"; do
  COUNT=$((COUNT + 1))
  PAGES=$(python3 -c "import json; print(len(json.load(open('output/$BOOK/pages.json'))))")
  echo ""
  echo "[$COUNT/$TOTAL] START $BOOK ($PAGES pages)"
  
  python3 pipeline/skills/signal_router.py \
    --book-id "$BOOK" \
    --backend dashscope \
    --resume \
    --concurrency 5 \
    2>&1 | tail -10
  
  echo "[$COUNT/$TOTAL] DONE $BOOK"
done

echo ""
echo "$(date): Wave 2 complete"
