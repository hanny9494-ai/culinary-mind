#!/bin/bash
# Batch Signal Router — 按顺序跑所有待处理书目
# 用 DashScope qwen3.6-plus，5 并发

cd /Users/jeff/culinary-mind

BOOKS=(
  yuecan_wangliang
  french_sauces
  noma_vegetable
  shijing
  xidage_xunwei_hk
  bread_science_yoshino
  ice_cream_flavor
  gufa_yc
  zhongguo_caipu_guangdong
  bocuse_cookbook
  japanese_cooking_tsuji
  mouthfeel
  bourne_food_texture
  franklin_barbecue
  essentials_food_science
  molecular_gastronomy
  bread_hamelman
  toledo_food_process_engineering
  neurogastronomy
  deman_food_chemistry
  sous_vide_keller
  taste_whats_missing
  noma_fermentation
  phoenix_claws
  charcuterie
  professional_baking
  zhongguo_yinshi_meixueshi
  cooking_for_geeks
  ofc
  flavor_equation
  flavor_thesaurus
  salt_fat_acid_heat
  jacques_pepin
  modernist_pizza
  flavor_bible
  science_of_spice
  fennema_food_chemistry
  heldman_handbook_food_engineering
  art_of_fermentation
  food_lab
  vegetarian_flavor_bible
  mc_vol1
  french_patisserie
  professional_chef
  professional_pastry_chef
  science_good_cooking
)

TOTAL=${#BOOKS[@]}
COUNT=0
FAILED=0

echo "$(date): Starting batch signal routing — $TOTAL books"
echo "============================================"

for BOOK in "${BOOKS[@]}"; do
  COUNT=$((COUNT + 1))
  PAGES_FILE="output/$BOOK/pages.json"
  SIG_FILE="output/$BOOK/signals.json"
  
  if [ ! -f "$PAGES_FILE" ]; then
    echo "[$COUNT/$TOTAL] SKIP $BOOK — no pages.json"
    continue
  fi
  
  TOTAL_PAGES=$(python3 -c "import json; print(len(json.load(open('$PAGES_FILE'))))")
  
  echo ""
  echo "[$COUNT/$TOTAL] START $BOOK ($TOTAL_PAGES pages)"
  echo "$(date)"
  
  python3 pipeline/skills/signal_router.py \
    --book-id "$BOOK" \
    --backend dashscope \
    --resume \
    --concurrency 5 \
    2>&1 | tail -15
  
  RC=$?
  if [ $RC -ne 0 ]; then
    echo "[$COUNT/$TOTAL] FAILED $BOOK (exit=$RC)"
    FAILED=$((FAILED + 1))
  else
    echo "[$COUNT/$TOTAL] DONE $BOOK"
  fi
done

echo ""
echo "============================================"
echo "$(date): Batch complete — $COUNT books, $FAILED failed"
