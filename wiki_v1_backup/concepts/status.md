---
last_updated: '2026-04-04T16:09:15.102168+00:00'
mention_count: 48.0
related:
- '[[Architecture/L2b.md]]'
- '[[config/books.yaml]]'
- '[[STATUS.md]]'
- '[[Architecture/L0.md]]'
- '[[Architecture/L2a.md]]'
- '[[docs/research/l2c_cantonese_condiments_data_sources.md]]'
- '[[docs/research/ocr_tools_comparison_2026.md]]'
- '[[scripts/l2c_scrape_tds.py]]'
- '[[docs/research/l2c_tds_sources.md]]'
- '[[docs/research/l2a_global_food_atom_sources.md]]'
- '[[l2a_atom_schema_v2.md]]'
- '[[api_routing.md]]'
- '[[l0-l2-linking-research.md]]'
- '[[recipe_schema_v1.md]]'
- '[[system_architecture_evaluation.md]]'
- '[[stage5_recipe_extract_design.md]]'
- '[[mc_integration_plan.md]]'
- '[[stage4_open_extract_design.md]]'
- '[[roadmap_priorities_v2.md]]'
- '[[pipeline_scripts.md]]'
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
title: concepts — status
---

# concepts — status


## Updates (2026-04-04)
- L2b current data: 29,085 validated recipes extracted from 63 books.
- L0 current data: 50,000+ entries, status is 'wrapping up' (收官中).
- L2a pilot: 75 varieties of natural ingredients completed as pilot, full L2a layer not yet built.
- Layers not yet built: L1 (equipment parameters), L2a (natural ingredients, pilot done), L2c (commercial ingredients), FT (flavor targets), L3 (reasoning engine), L6 (translation layer).
- Project name: culinary-engine (餐饮研发引擎), GitHub: https://github.com/hanny9494-ai/culinary-engine, current version: STATUS.md v7, last updated: 2026-03-30
- L0 total QC-passed entries as of 2026-03-30: 45,093 条
- L2a recipe_id assignment: 65 books, 30,582 recipes all assigned unique IDs
- L2a external data merge: books 18,951 + USDA 19,295 = 38,246 raw ingredients total
- L2a cleaning: deleted 197 garbage entries + separated 13 brand products → 12,775 clean natural ingredients
- L2a Gemini R1 distillation completed: 21,266 atoms (composition 95%, l0_domains 96%, flavor 96%)
- L2a GPT-5.4 R2 deep distillation in progress: 21,422 atoms, covering 品种/粤菜适性/科学原理/替代品/质量指标. Config: 1,429 batches × 15/batch, 4 concurrent, ~6 hours, estimated cost ¥37
- L2a new data sources ingredient extraction completed: 台湾鱼类 + 畜禽 432 品种 + 两本新书 = 1,119 new ingredients
- L2a full normalization pipeline result: 60,499 → 23,629 canonicals (92.7% mapped), then LLM cleaning removed 2,109 non-food → 21,127 ingredient atoms
- L2c scope: 粤菜调味料 310 SKU + 全品类 6,500-10,000 SKU total
- OCR pipeline: PaddleOCR API batch OCR in progress for 11 PDF + 5 EPUB files
- L0 pipeline automation: completed — all merged into new repo, TOC mandatory check added
- P0 priority queue: GPT-5.4 R2 deep distillation running (21,422 atoms), non-food 2,109 entries pending review
- L2c TDS scraper covers 5 brands, 193 SKU (P1 task)
- L2a external data sources: 13/14 downloaded (3 broken links: bitterdb, supersweet, phenol_explorer)
- L2a ingredient book OCR pipeline: 17 食材图鉴 books OCR completed → Flash ingredient name extraction completed
- L2b total recipe count: 30,582 recipes from 65 books, all with unique recipe_id assigned
- L2a full 3,000 atom distillation cost estimate: two rounds, approximately ¥800-1,200, 6-8 days
- L2a schema has 7 pending decision points awaiting Jeff's approval (as of 2026-03-26)
- Document generation timestamp: 2026-03-30 for api_routing.md; research date 2026-03-26 for l0-l2-linking-research.md and l2a_atom_schema_v2.md
- L2a atom schema v2 is a joint researcher + architect design document, status: pending Jeff's approval on 7 decision points
- Schema validation cases: Corsu Vecchiu with Carrot Salad (French Laundry, simple ✅), Tilefish Steamed with Millet (Tsuji Japanese Cooking, medium ✅), Sunflower Barigoule (Eleven Madison Park, extremely complex 10 cross-references ✅), 盐曲熟成鲈鱼 (handwritten, multi-day process ✅), 叉烧汉堡包 (handwritten, nested sub-recipes ✅)
- L3 inference engine estimated build time: 1-2 weeks (retriever integration 3 days, LangGraph agent graph 4-5 days, end-to-end testing 2 days)
- Data import estimated build time: 2-3 days for Plan C hybrid approach
- Stage5 pipeline processes 11 books total for L2b recipe calibration library extraction
- Stage5 design document is mother-conversation design dated 2026-03-18, positioning: extract structured recipes from 11 books to populate L2b recipe calibration library
- System architecture evaluation authored by architect agent, version v1.0, dated 2026-03-26, scope: data import layer, inference engine (L3), user interface, API layer
- Mission Control integration plan authored by architect agent on 2026-03-26, targeting 1-2 day implementation for agent collaboration capability
- Stage4 expected output: 4,000-7,000 new atomic propositions; net increase after dedup: 3,000-5,000 new entries
- Roadmap v2 dated 2026-03-18; maintained in parent conversation
- Deprecated scripts: stage1_serial_runner.py (unreliable, multi-book serial runner that breaks after one book), stage1_parallel_annotate.py (possibly deprecated, replaced by stage1_pipeline.py Step5), fill_pending_parts_with_paddle.py (status unknown, may fill missing pages with PaddleOCR)
- Tested and confirmed: dispatch file written → researcher pane receives message and begins execution within 3 seconds
- ce-hub known limitation: Cost tracker infrastructure is ready but has no real API call data yet
- ce-hub implementation dates: 2026-04-02 to 2026-04-03 (v2 TUI implementation)
- L2a ingredient data research conducted on 2026-03-26 by researcher agent evaluating Google Gemini, Grok, and Perplexity for ingredient data enrichment
- Orchestrator v2 target file is scripts/dify/orchestrator.py, current version is 398 lines (old, no tmux, no parallel, no report, no auto-fix)
- Book inventory report generated 2026-03-28, covers 63 registered books scanned from books.yaml + output/ directory
- L0 science+recipe books total: 45 books in scope
- Book inventory tracks 63 registered books in books.yaml plus Documents directory scan
- Book inventory report generated 2026-03-28 covers 45 science+recipe books in L0 processing pipeline
- Project already has GEMINI_API_KEY available, enabling immediate use of Gemini 2.5 Flash with Search Grounding for L2a without additional credential setup.
- Project name is 'culinary-engine' (also referenced as 'l0-knowledge-engine'). Local path: /Users/jeff/culinary-engine/ and /Users/jeff/l0-knowledge-engine/. Dual naming suggests in-progress rename or migration.
- Database availability audit covered 67 total resources: 32 directly downloadable, 12 need scraping/registration, 17 unavailable/commercial/defunct, 6 previously known.
