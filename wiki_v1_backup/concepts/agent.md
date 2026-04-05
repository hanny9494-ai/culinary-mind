---
last_updated: '2026-04-04T16:09:15.091645+00:00'
mention_count: 25.0
related:
- '[[CLAUDE.md]]'
- '[[.claude/agents/cc-lead.md]]'
- '[[.claude/agents/pipeline-supervisor.md]]'
- '[[.claude/agents/pipeline-runner.md]]'
- '[[.claude/agents/architect.md]]'
- '[[.claude/agents/researcher.md]]'
- '[[.claude/agents/coder.md]]'
- '[[.claude/agents/code-reviewer.md]]'
- '[[.claude/agents/open-data-collector.md]]'
- '[[.claude/agents/ops.md]]'
- '[[.claude/agents/]]'
- '[[docs/research/claude_code_agent_isolation.md]]'
- '[[STATUS.md]]'
- '[[system_architecture_evaluation.md]]'
- '[[stage5_recipe_extract_design.md]]'
- '[[ce-hub/cehub_handover.md]]'
- '[[scripts/dify/orchestrator.py]]'
- '[[Architecture/L0.md]]'
- '[[e2e_inference_design.md]]'
- '[[agents/researcher.md]]'
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
title: concepts — agent
---

# concepts — agent


## Updates (2026-04-04)
- CC Lead role: Command center (mother conversation). Responsibilities: receive Jeff's instructions, decompose into executable tasks, draft tasks in standard Task Protocol format, dispatch to appropriate agents, collect results, update STATUS.md, record major decisions, sync CLAUDE.md. Must read STATUS.md at start of every work session.
- CC Lead constraints: Does NOT write code (coder does), does NOT run pipeline scripts (pipeline-supervisor/pipeline-runner does), does NOT read large data files (spawn explorer subagent), does NOT make strategic decisions for Jeff (presents options, Jeff decides), does NOT push directly to main (uses PR flow). Context lifespan preservation: coding tasks must be dispatched to agents.
- Agent: pipeline-supervisor — Type: manager. Responsibility: overall pipeline manager for all data layers L0-L6, monitoring and scheduling.
- Agent: pipeline-runner — Type: executor. Responsibility: runs Stage1-5 full pipeline.
- Agent: architect — Type: architecture. Responsibility: evaluates how new data sources/methods integrate into the 7-layer architecture, outputs technical proposals.
- Agent: researcher — Type: exploration. Responsibility: searches external resources, papers, open-source projects, evaluates value to project.
- Agent: coder — Type: coding. Responsibility: database, strategy layer, frontend, script writing (core productivity).
- Agent: code-reviewer — Type: review. Responsibility: reviews code changes, catches regressions and resource violations.
- Agent: open-data-collector — Type: collection. Responsibility: crawls external data via OpenClaw and similar tools (Mac Mini sandbox).
- Agent: ops — Type: operations. Responsibility: service health checks, infrastructure management.
- Infrastructure: coder agent fix — Codex pushes to GitHub + CC Lead fetches + reviews (closed loop)
- Infrastructure: Agent tool worktree isolation confirmed — all subagents are isolated; file-writing tasks use 'claude -p' or run directly in terminal
- 母对话 (mother conversation) maintains STATUS.md; agents are NOT allowed to modify it
- Agent isolation pattern: subagents use worktree isolation; file-writing tasks should use 'claude -p' flag or run directly in terminal
- L3 inference engine tool set: [1] VectorRetriever→L0 semantic similar principles, [2] HybridRetriever→L2b recipes+fulltext, [3] Text2CypherRetriever→graph structure queries (ingredient substitution paths), [4] DomainRouter→query domain classification, [5] Graphiti→user history preferences (personalized memory)
- 27b extraction prompt design fuses r-NE label system and Cooklang experience. Key rules: (1) fuzzy quantities→numbers, (2) only 'to taste' allows qty=null, (3) metric units only, (4) cross-references go into refs[] not expanded, (5) intermediate products with independent formula marked as SubRecipe not merged
- CC Lead agent runs with `claude --model opus --agent cc-lead` and is hardcoded to the top largest pane in the tmux layout
- Dashboard panel (scripts/dashboard.py) refreshes every 8 seconds and displays: ce-hub daemon status+uptime, all 9 agent online/offline states, task queue by status, queue pressure (opus/flash/ollama), Claude Code token consumption (last 5 hours + total from ~/.claude/projects/ JSONL), active Claude sessions count, cost tracking (daily/weekly), scheduled tasks, file protocol queue depths (dispatch/inbox/results)
- run_codex_in_tmux function: builds ENV_CONTEXT + prompt + REPORT_INSTRUCTION, creates tmux window, executes codex, polls .done/.fail marker files, reads report JSON, returns summary. Timeout: 14400 seconds (4 hours)
- run_stage4 prompt template: 'Run Stage4 open extraction for book "{book_id}". python3 scripts/stage4_open_extract.py --chunks {chunks_path} --book-id {book_id} --config config/api.yaml --output-dir {output_dir} --resume --phase all'
- L6 translation layer mappings for Query 1: '南方' → [广东, 福建, 浙江, 海南, 东南亚华南圈]; '酸辣' → sour(pH 3.2-3.8) + spicy(Scoville 1000-5000); '冷前菜' → serving_temp ≤ 12°C, course=starter, portion=60-80g; '春天' → peak_months [3,4,5]; '海鲜' → category in [seafood_crustacean, seafood_mollusk, seafood_fish]
- L3 reasoning engine output for Query 1: selected ingredient = 白虾 (广东湛江, March-May, live shrimp), acidifier = 青柠汁 + 少量米醋 (pH 3.3-3.5), spice = 小米椒 + 姜, timing = 25-30 min marination (L0 constraint), aromatics = 香茅/鱼露/少许糖, plating = 6-8 shrimp/portion cold plate. Final dish name: 青柠腌白虾 (粤式 Aguachile)
- Researcher agent role: evaluates external tools and data sources, produces research reports with recommendations for pipeline components. Active as of 2026-03.
- The researcher agent conducted both the multi-layer food knowledge modeling research (2026-03-26) and the database availability audit (2026-03-26).
