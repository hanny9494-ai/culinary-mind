#!/bin/bash

# Signal Router Batch Processing Script
# Runs pipeline on each book sequentially with error tracking

cd /Users/jeff/culinary-mind

# Book list
BOOKS=(
mc_vol3
mc_vol2
mc_vol4
bread_science_yoshino
ice_cream_flavor
gufa_yc
zhongguo_caipu_guangdong
f2986_baltic
dokumen.pub_the-whole-fish-cookbook-new-
bocuse_cookbook
japanese_cooking_tsuji
mouthfeel
organum_nature_texture_intensity_purity
bourne_food_texture
crave
franklin_barbecue
essentials_food_science
molecular_gastronomy
bread_hamelman
toledo_food_process_engineering
neurogastronomy
deman_food_chemistry
core_-_clare_smyth
momofuku
sous_vide_keller
taste_whats_missing
f1749_manresa
noma_fermentation
the-french-laundry-cookbook-978157965126
phoenix_claws
charcuterie
professional_baking
the_hand_and_flowers_cookbook
zhongguo_yinshi_meixueshi
bouchon_-_thomas_keller
cooking_for_geeks
japanese_farm_food_-_nancy_singleton_hac
ofc
flavor_equation
relae_a_book_of_ideas_-_christian_f_pugl
alinea_-_grant_achatz
daniel_my_french_cuisine_-_daniel_boulud
flavor_thesaurus
eleven_madison_park_the_next_chapter_紫色封
salt_fat_acid_heat
jacques_pepin
modernist_pizza
flavor_bible
science_of_spice
fennema_food_chemistry
the_everlasting_meal_cookbook_leftovers_
heldman_handbook_food_engineering
eleven_madison_park_the_cookbook_-_danie
art_of_fermentation
food_lab
vegetarian_flavor_bible
meat_illustrated_a_foolproof_guide_to_un
mc_vol1
french_patisserie
professional_chef
professional_pastry_chef
science_good_cooking
)

# Tracking arrays
declare -a SUCCESSFUL=()
declare -a FAILED=()

# Summary file with timestamp
SUMMARY_FILE="signal_router_summary_$(date +%Y%m%d_%H%M).txt"

echo "========================================" | tee -a "$SUMMARY_FILE"
echo "Signal Router Batch Processing" | tee -a "$SUMMARY_FILE"
echo "Started: $(date)" | tee -a "$SUMMARY_FILE"
echo "Total books: ${#BOOKS[@]}" | tee -a "$SUMMARY_FILE"
echo "========================================" | tee -a "$SUMMARY_FILE"
echo "" | tee -a "$SUMMARY_FILE"

# Process each book
for i in "${!BOOKS[@]}"; do
    BOOK="${BOOKS[$i]}"
    echo "[$((i+1))/${#BOOKS[@]}] Processing: $BOOK" | tee -a "$SUMMARY_FILE"
    
    # Run the signal router pipeline
    if python3 pipeline/skills/signal_router.py --book-id "$BOOK" --backend dashscope --resume --concurrency 5; then
        echo "  ✓ SUCCESS: $BOOK" | tee -a "$SUMMARY_FILE"
        SUCCESSFUL+=("$BOOK")
    else
        echo "  ✗ FAILED: $BOOK" | tee -a "$SUMMARY_FILE"
        FAILED+=("$BOOK")
    fi
    
    echo "" | tee -a "$SUMMARY_FILE"
done

# Generate final summary
echo "========================================" | tee -a "$SUMMARY_FILE"
echo "BATCH PROCESSING COMPLETE" | tee -a "$SUMMARY_FILE"
echo "Finished: $(date)" | tee -a "$SUMMARY_FILE"
echo "========================================" | tee -a "$SUMMARY_FILE"
echo "" | tee -a "$SUMMARY_FILE"
echo "SUMMARY:" | tee -a "$SUMMARY_FILE"
echo "  Total books processed: ${#BOOKS[@]}" | tee -a "$SUMMARY_FILE"
echo "  Successful completions: ${#SUCCESSFUL[@]}" | tee -a "$SUMMARY_FILE"
echo "  Failed books: ${#FAILED[@]}" | tee -a "$SUMMARY_FILE"
echo "" | tee -a "$SUMMARY_FILE"

if [ ${#FAILED[@]} -gt 0 ]; then
    echo "FAILED BOOKS:" | tee -a "$SUMMARY_FILE"
    for book in "${FAILED[@]}"; do
        echo "  - $book" | tee -a "$SUMMARY_FILE"
    done
    echo "" | tee -a "$SUMMARY_FILE"
fi

if [ ${#SUCCESSFUL[@]} -gt 0 ]; then
    echo "SUCCESSFUL BOOKS:" | tee -a "$SUMMARY_FILE"
    for book in "${SUCCESSFUL[@]}"; do
        echo "  - $book" | tee -a "$SUMMARY_FILE"
    done
    echo "" | tee -a "$SUMMARY_FILE"
fi

echo "Summary saved to: $SUMMARY_FILE"
