---
last_updated: '2026-04-04T16:09:15.098278+00:00'
mention_count: 38.0
related:
- '[[STATUS.md]]'
- '[[stage5_recipe_extract_design.md]]'
- '[[stage4_open_extract_design.md]]'
- '[[Architecture/L0.md]]'
- '[[book_inventory_20260328.md]]'
- '[[books/ofc.md]]'
- '[[report_book_inventory_20260328.md]]'
- '[[books/science_good_cooking.md]]'
- '[[books/mc_vol1.md]]'
- '[[books/food_lab.md]]'
- '[[books/mouthfeel.md]]'
- '[[orchestrator_ocr_stage1_noma_vegetable_result.md]]'
sources:
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
status: active
title: concepts — book
---

# concepts — book


## Updates (2026-04-04)
- L0 jacques_pepin book: dedup+QC completed, 401 entries passed (98.3% pass rate)
- L0 book: Neurogastronomy — Stage1: 613 entries, Stage4: 349 net increase (completed)
- L0 book: SFAH — Stage1: 1,055 entries
- L0 book: MC Vol1 — Stage1: 2,148 entries
- L0 book: 冰淇淋 — Stage1: 217 entries, Stage2 pending (waiting for 7 new books to complete)
- L0 book: Mouthfeel — Stage1: 1,162 entries
- L0 book: Flavorama — Stage1: 1,159 entries
- L0 book: Science of Spice — Stage1: 1,136 entries
- L0 book: Professional Baking — Stage1: 3,434 entries
- L0 book: OFC — Stage4 completed, 3,955 net increase
- L0 book: MC Vol2/3/4 — Stage4 Phase B in progress (API serial processing)
- Academic reference: Recipe Flow Graph (r-FG, Kyoto University 2020, Yamakata et al., LREC 2020) — DAG representing ingredient→action→intermediate product. r-NE label system: F(ingredient), T(tool), Ac(action), D(time), Q(quantity/temperature), Sf(state). F1=87.5. Used for: r-NE labels guide 27b extraction prompt entity recognition
- Academic reference: Cooklang + GPT-4 flow graph extraction (2023) — GPT-4 one-shot extracts flow graph structure from recipe text, good at naming intermediate products ('the chocolate mixture'). Lesson: LLM can extract recipe structure in one step; intermediate product naming → SubRecipe identification
- Academic reference: EaT-PIM ingredient substitution (ISWC 2022) — parse instructions→flow graph→train embedding→capture ingredient role in process→substitution. Used for P4 phase L3 inference engine ingredient substitution. Our advantage: L0 scientific principles can judge substitution scientific feasibility
- Academic reference: PADME procedural text execution (2025) — converts procedural text to executable graph, captures task dependencies, decision points, reusable subroutines. 'Reusable subroutine' concept = our SubRecipe
- Book inventory: On Food and Cooking (ofc, 1,427 chunks), MC Vol2 (mc_vol2, 485), MC Vol3 (mc_vol3, 502), MC Vol4 (mc_vol4, 703), MC Vol1 (mc_vol1, 2,148), Neurogastronomy (neurogastronomy, 613), Salt Fat Acid Heat (salt_fat_acid_heat, 1,055), 冰淇淋风味学 (ice_cream_flavor, 217), Mouthfeel (mouthfeel, 1,162), Flavorama (flavorama, 1,159), Science of Spice (science_of_spice, 1,136), Professional Baking (professional_baking, 3,434)
- Book batch groupings: Batch 0 = ofc, mc_vol2, mc_vol3, mc_vol4; Batch 1 = mc_vol1, neurogastronomy, salt_fat_acid_heat, ice_cream_flavor; Batch 2 = mouthfeel, flavorama, science_of_spice, professional_baking
- Professional Baking is the largest single book with 3,434 chunks; MC Vol1 is second largest with 2,148 chunks; 冰淇淋风味学 is smallest with 217 chunks
- noma_vegetable book: source PDF has 925 total pages, located at /Users/jeff/l0-knowledge-engine/output/noma_vegetable/source_converted.pdf
- book ofc (On Food and Cooking): L0 done, 3,955 QC-passed principles, 894 chunks_smart entries, source: 厨书（待转换）/*.epub
- book science_good_cooking (The Science of Good Cooking): L0 done, 3,806 principles, 2,865 chunks_smart, source: 厨书（待转换）/*.epub
- book mc_vol1 (Modernist Cuisine Vol 1): L0 done, 3,110 principles, 2,150 chunks_smart, source: 厨书数据库/工具科学书/*.epub
- book food_lab (The Food Lab): L0 done, 2,242 principles, 2,225 chunks_smart, source: 厨书（待转换）/*.epub
- book mouthfeel: L0 done, 2,410 principles, 1,163 chunks_smart, source: 第二批厨艺书籍/*.pdf
- book cooking_for_geeks: L0 done, 2,266 principles, 1,495 chunks_smart, source: 厨书（待转换）/*.epub
- book professional_baking (7th Ed.): L0 done, 2,136 principles, 3,440 chunks_smart, source: 第二批厨艺书籍/*.pdf
- book molecular_gastronomy: L0 done, 1,951 principles, 809 chunks_smart, source: 厨书（待转换）/*.epub
- book chocolates_confections: L0 done, 1,934 principles, 908 chunks_smart, source: 第三批书籍/*.pdf
- book professional_pastry_chef: L0 done, 1,716 principles, 2,499 chunks_smart, source: 第二批厨艺书籍/*.pdf
- book bread_hamelman (Bread by Hamelman): L0 done, 1,669 principles, 2,434 chunks_smart, source: 第三批书籍/*.pdf
- book science_of_chocolate: L0 done, 1,577 principles, 659 chunks_smart, source: 第三批书籍/*.pdf
- On Food and Cooking (ofc): L0 done, 3,955 QC-passed L0 principles, 894 smart chunks, source at 厨书（待转换）/*.epub
- The Science of Good Cooking (science_good_cooking): L0 done, 3,806 QC-passed principles, 2,865 smart chunks, source at 厨书（待转换）/*.epub
- Modernist Cuisine Vol 1 (mc_vol1): L0 done, 3,110 QC-passed principles, 2,150 smart chunks, source at 厨书数据库/工具科学书/*.epub
- The Food Lab (food_lab): L0 done, 2,242 QC-passed principles, 2,225 smart chunks, source at 厨书（待转换）/*.epub
- Mouthfeel: L0 done, 2,410 QC-passed principles, 1,163 smart chunks, source at 第二批厨艺书籍/*.pdf
- Noma Vegetable book: total pages = 925, OCR model = qwen3.5-flash via DashScope API
