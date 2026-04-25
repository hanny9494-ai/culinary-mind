#!/bin/bash
# batch_signal_skill.sh — Run Signal Router + Skill A/D for all pending books
# Usage: ./scripts/batch_signal_skill.sh [phase]
# Phase: signal | skill_a | skill_d | all (default: all)
# Run with: caffeinate -s nohup bash scripts/batch_signal_skill.sh > logs/batch_signal_skill.log 2>&1 &

set -e
REPO="/Users/jeff/culinary-mind"
LOG="$REPO/logs/batch_signal_skill_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$REPO/logs"

export no_proxy=localhost,127.0.0.1
export http_proxy=
export https_proxy=

PHASE="${1:-all}"

log() {
  echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"
}

# ── BOOKS LISTS ────────────────────────────────────────────────────────────────

# English science books needing Signal (B,C,D only — no Skill A)
SIGNAL_BCD=(
  franklin_barbecue
  sous_vide_keller
  flavor_thesaurus
  vegetarian_flavor_bible
  charcuterie
  art_of_fermentation
  professional_chef
  flavor_equation
  french_patisserie
  phoenix_claws
)

# Chinese recipe books needing Signal (B,C,D — Skill D for flavor)
SIGNAL_ZH=(
  yuecan_zhenwei_meat
  fenbuxiangjiena_yc
  shijing
  hk_yuecan_yanxi
  gufa_yc
  zhujixiaoguan_2
  zhujixiaoguan_3
  zhujixiaoguan_4
  zhujixiaoguan_6
  zhujixiaoguan_v6b
  zhujixiaoguan_dimsim2
  chuantong_yc
  guangdong_pengtiao_quanshu
  zhongguo_caipu_guangdong
  zhongguo_yinshi_meixueshi
  yuecan_wangliang
  xidage_xunwei_hk
)

# PATH_1 P0 science books — need Signal + Skill A (these had signal_status=done in yaml but no files)
SIGNAL_P0=(
  mc_vol1
  food_lab
  science_good_cooking
  chocolates_confections
  science_of_chocolate
  professional_baking
  bread_hamelman
  molecular_gastronomy
  mouthfeel
  cooking_for_geeks
  modernist_pizza
  koji_alchemy
  noma_fermentation
  ratio
  essentials_food_science
  ofc
  handbook_molecular_gastronomy
  flavorama
  science_of_spice
  salt_fat_acid_heat
  taste_whats_missing
  neurogastronomy
  ice_cream_flavor
  bread_science_yoshino
  dashi_umami
  flavor_bible
  professional_pastry_chef
  bocuse_cookbook
  french_sauces
  japanese_cooking_tsuji
  jacques_pepin
  noma_vegetable
)

# Books with signal already done (from books.yaml) — need Skill A only
SKILL_A_ONLY=(
  flavorama
  science_of_spice
  salt_fat_acid_heat
  taste_whats_missing
  neurogastronomy
  ice_cream_flavor
  bread_science_yoshino
  dashi_umami
  flavor_bible
  professional_pastry_chef
  bocuse_cookbook
  french_sauces
  japanese_cooking_tsuji
  jacques_pepin
  noma_vegetable
)

# ── PHASE: SIGNAL ──────────────────────────────────────────────────────────────
run_signal() {
  local book_id="$1"
  local pages_file="$REPO/output/$book_id/pages.json"
  local sig_file="$REPO/output/$book_id/signals.json"

  if [ -f "$sig_file" ]; then
    log "[signal] SKIP $book_id: signals.json already exists"
    return 0
  fi

  if [ ! -f "$pages_file" ]; then
    log "[signal] ERROR $book_id: pages.json missing"
    return 1
  fi

  local npages
  npages=$(python3 -c "import json; d=json.load(open('$pages_file')); print(len(d))")
  log "[signal] START $book_id ($npages pages)"

  cd "$REPO"
  python3 -u pipeline/skills/signal_router.py --book-id "$book_id" >> "$LOG" 2>&1
  local exit_code=$?

  if [ $exit_code -eq 0 ] && [ -f "$sig_file" ]; then
    local ndone
    ndone=$(python3 -c "import json; d=json.load(open('$sig_file')); print(len(d.get('pages',[]) if isinstance(d,dict) else d))" 2>/dev/null || echo "?")
    log "[signal] DONE $book_id: $ndone signals written"
  else
    log "[signal] FAIL $book_id: exit=$exit_code"
  fi
}

# ── PHASE: SKILL A ─────────────────────────────────────────────────────────────
run_skill_a() {
  local book_id="$1"
  local sig_file="$REPO/output/$book_id/signals.json"
  local out_file="$REPO/output/$book_id/skill_a/results.jsonl"

  if [ -f "$out_file" ]; then
    log "[skill_a] SKIP $book_id: results.jsonl exists"
    return 0
  fi

  if [ ! -f "$sig_file" ]; then
    log "[skill_a] ERROR $book_id: signals.json missing"
    return 1
  fi

  log "[skill_a] START $book_id"
  mkdir -p "$REPO/output/$book_id/skill_a"

  cd "$REPO"
  python3 -u pipeline/skills/run_skill.py --skill a --book-id "$book_id" >> "$LOG" 2>&1
  local exit_code=$?

  if [ $exit_code -eq 0 ]; then
    local nlines=0
    [ -f "$out_file" ] && nlines=$(wc -l < "$out_file" | tr -d ' ')
    log "[skill_a] DONE $book_id: $nlines results"
  else
    log "[skill_a] FAIL $book_id: exit=$exit_code"
  fi
}

# ── PHASE: SKILL D ─────────────────────────────────────────────────────────────
run_skill_d() {
  local book_id="$1"
  local sig_file="$REPO/output/$book_id/signals.json"
  local out_file="$REPO/output/$book_id/skill_d/results.jsonl"

  if [ -f "$out_file" ]; then
    log "[skill_d] SKIP $book_id: results.jsonl exists"
    return 0
  fi

  if [ ! -f "$sig_file" ]; then
    log "[skill_d] ERROR $book_id: signals.json missing"
    return 1
  fi

  log "[skill_d] START $book_id"
  mkdir -p "$REPO/output/$book_id/skill_d"

  cd "$REPO"
  python3 -u pipeline/skills/run_skill.py --skill d --book-id "$book_id" >> "$LOG" 2>&1
  local exit_code=$?

  if [ $exit_code -eq 0 ]; then
    local nlines=0
    [ -f "$out_file" ] && nlines=$(wc -l < "$out_file" | tr -d ' ')
    log "[skill_d] DONE $book_id: $nlines results"
  else
    log "[skill_d] FAIL $book_id: exit=$exit_code"
  fi
}

# ── MAIN ───────────────────────────────────────────────────────────────────────
log "=== batch_signal_skill.sh START phase=$PHASE ==="

if [[ "$PHASE" == "signal" || "$PHASE" == "all" ]]; then
  log "--- Phase: Signal Router ---"
  log "Batch 1: English science books (B,C,D)"
  for bid in "${SIGNAL_BCD[@]}"; do
    run_signal "$bid"
  done

  log "Batch 2: Chinese recipe books"
  for bid in "${SIGNAL_ZH[@]}"; do
    run_signal "$bid"
  done

  log "Batch 3: PATH_1 P0 science books (need Skill A)"
  for bid in "${SIGNAL_P0[@]}"; do
    run_signal "$bid"
  done
fi

if [[ "$PHASE" == "skill_a" || "$PHASE" == "all" ]]; then
  log "--- Phase: Skill A (ParameterSet extraction, aigocode Opus) ---"
  # Run Signal_P0 books first after they complete signal
  for bid in "${SIGNAL_P0[@]}"; do
    run_skill_a "$bid"
  done
  # Then books with signal already done
  for bid in "${SKILL_A_ONLY[@]}"; do
    run_skill_a "$bid"
  done
fi

if [[ "$PHASE" == "skill_d" || "$PHASE" == "all" ]]; then
  log "--- Phase: Skill D (FlavorTarget, aigocode Opus) ---"
  for bid in "${SIGNAL_BCD[@]}"; do
    run_skill_d "$bid"
  done
  for bid in "${SIGNAL_ZH[@]}"; do
    run_skill_d "$bid"
  done
fi

log "=== batch_signal_skill.sh DONE ==="
