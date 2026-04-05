---
last_updated: '2026-04-04T16:09:15.104234+00:00'
mention_count: 43.0
related:
- '[[STATUS.md]]'
- '[[docs/l2b_stepb_prompt_design.md]]'
- '[[docs/research/l2a_global_food_atom_sources.md]]'
- '[[stage5_recipe_extract_design.md]]'
- '[[mc_integration_plan.md]]'
- '[[ce-hub/cehub_handover.md]]'
- '[[Architecture/L0.md]]'
- '[[report_orchestrator_ocr_stage1_noma_vegetable_result.md]]'
- '[[scripts/dify/orchestrator.py]]'
- '[[research/exhaustive-food-databases-survey.md]]'
- '[[Architecture/L2a.md]]'
- '[[pipeline/stage4.md]]'
- '[[agents/orchestrator.md]]'
- '[[e2e_inference_design.md]]'
- '[[research_architecture-briefing-for-cc-lead.md]]'
- '[[research/search-grounded-llms-for-ingredient-data.md]]'
- '[[agents/L2a.md]]'
- '[[research/notebooklm-youtube-food-extraction.md]]'
- '[[agents/L1.md]]'
- '[[orchestrator/stage4_dashi_umami_result.md]]'
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
title: concepts — blocker
---

# concepts — blocker


## Updates (2026-04-04)
- L2a non-food items: 2,109 entries filtered out (LLM cleaning), pending review — may contain additives to be reclassified to L2c
- L2b Step B design document completed: docs/l2b_stepb_prompt_design.md. Execution deferred until Neo4j is set up (requires vector search for L0 binding)
- L2c startup condition: waiting for external data download completion + L2a stabilization before launching
- External data sources: 11/14 downloaded (bitterdb/supersweet/phenol_explorer links broken, require manual retrieval)
- 干鮑魚海味寶典: 73 pages webp downloaded; remaining 173 pages locked behind paid subscription — can contact author to unlock
- L0 Stage4 third batch (7 books): pending startup, waiting for chunk_type shortcut path
- L0 full Stage3 distillation: pending — must wait for ALL Stage2 to complete first
- Neo4j is a hard dependency for L2b Step B/C execution (requires vector search for L0 binding)
- USDA data quality issue: packaged food contamination discovered in full USDA dataset; only Foundation Foods subset (335 entries) is usable for L2a
- Core problem in professional cookbook extraction: sub-recipes are scattered across chapters. Basic Recipes at book end referenced by 20+ dishes; cross-chapter page references like 'see p.xxx'. SubRecipe Registry is the solution
- task_queue.db runs on port 8742 and is disconnected from MC tasks table — identified as HIGH severity gap with LOW effort to fix via Python sync script
- Agent comms panel has no actual data — MEDIUM severity, LOW effort (direct write to messages table)
- Memory Browser points to wrong directory — HIGH severity, EXTREMELY LOW effort (change .env OPENCLAW_MEMORY_DIR)
- Session panel needs MC_CLAUDE_HOME configuration — LOW severity, EXTREMELY LOW effort (change .env)
- Chat functionality requires OpenClaw — LOW severity, waiting for Mac Mini
- ce-hub bug fix: layout.sh was clearing http_proxy causing Claude Code to fail API access (403 auth error). Fix: only set no_proxy=localhost,127.0.0.1, preserve proxy settings
- ce-hub bug fix: ESM import hoisting issue in file-watcher.ts — const CWD at module top level executed before .env loaded, getting process.cwd() (ce-hub/) instead of .env value. Fix: changed to lazy getter getCwd()
- ce-hub bug fix: macOS sed incompatibility — `sed -n '/^---$/,/^---$/{ ... }'` not supported on macOS. Fix: replaced all instances with grep + sed combination
- ce-hub bug fix: Claude Code overwrites tmux pane title to `✳ agent-name` after startup. Fix: TmuxManager's findAgentTarget and isAlive changed to fuzzy matching using includes()
- ce-hub known limitation: Agent pane claude processes are independent sessions — they don't auto-read inbox, daemon must use tmux send-keys to notify them
- ce-hub known limitation: task-engine.executeTask() is still a mock — real task execution goes through file protocol, not task-engine
- ce-hub known limitation: Quality gate rules are not yet defined
- L0 pipeline OCR stage for noma_vegetable book is BLOCKED: source_converted.pdf exists at /Users/jeff/l0-knowledge-engine/output/noma_vegetable/source_converted.pdf (925 pages confirmed), but OCR directory has no output. 0 pages succeeded, 0 failed.
- L0 OCR blocker root cause: current execution environment cannot resolve/connect to dashscope.aliyuncs.com. Error: `httpx.ConnectError: [Errno 8] nodename nor servname provided, or not known`. DASHSCOPE_API_KEY exists and trust_env=False is set, but network is restricted in current session
- noma_vegetable book is NOT yet configured in books.yaml or mc_toc.json — workaround of using temporary config was planned but not executed due to OCR network blocker
- Proxy constraint: machine has proxy at 127.0.0.1:7890, ALL HTTP clients must set trust_env=False to avoid routing local Ollama calls through proxy
- Indian IFCT: 528 foods, available as book/app only (no bulk download), NIN license, targets L2a spice — import blocked by format
- Thai INMU: 2,200 foods, web-only access (no bulk download), public domain, targets L2a — import blocked by format
- Stage 4 pipeline failed for dashi_umami with PermissionError: [Errno 1] Operation not permitted writing to /Users/jeff/l0-knowledge-engine/output/dashi_umami/stage4/stage4_filter.jsonl — Codex sandbox cannot write outside workspace
- Critical L2a schema gap #1: varieties[] is embedded JSON array — Neo4j cannot efficiently filter by peak_months within nested arrays. Must be refactored to Variety as independent nodes (already noted in l2a_atom_schema_v2.md section 2c but not yet implemented)
- Gemini 2.5 Flash grounding metadata gotcha: grounding URLs are returned in a separate field, NOT inside the JSON response body. Must handle separately in parsing logic.
- Gemini File API supports video upload (visual + audio), max 1 hour, but does NOT accept YouTube URLs directly — video must be downloaded first before upload.
- Stage 4 (dashi/umami) pipeline execution FAILED with PermissionError: [Errno 1] Operation not permitted on path '/Users/jeff/l0-knowledge-engine/output/dashi_umami/stage4/stage4_filter.jsonl'. Codex sandbox cannot write to /Users/jeff/l0-knowledge-engine/... directory.
- Noma Vegetable OCR stage1 is BLOCKED: source_converted.pdf exists at /Users/jeff/l0-knowledge-engine/output/noma_vegetable/source_converted.pdf (925 pages confirmed), but OCR directory has no output — 0 pages processed
- Noma Vegetable OCR blocker root cause: current execution environment cannot resolve/connect to dashscope.aliyuncs.com — error: httpx.ConnectError: [Errno 8] nodename nor servname provided, or not known; DASHSCOPE_API_KEY exists and trust_env=False is set
- stage1_pipeline.py at /Users/jeff/culinary-engine/scripts/stage1_pipeline.py requires book to be configured in books.yaml and mc_toc.json; noma_vegetable is NOT yet configured in either file
- Two blockers must be resolved for noma_vegetable stage1: (1) add noma_vegetable to books.yaml and mc_toc.json, (2) fix network access to dashscope.aliyuncs.com in execution environment
- VCF (Volatile Compounds in Food): commercial, ~$2,000/year. Unavailable.
- Leffingwell flavor encyclopedia: commercial product. Unavailable.
- Cookpad Research dataset: discontinued in 2024. Unavailable.
- Reddit r/Cooking data: Pushshift shut down in 2023. Unavailable.
- Indian IFCT 2017 food composition: book/app only, no downloadable dataset. Unavailable.
