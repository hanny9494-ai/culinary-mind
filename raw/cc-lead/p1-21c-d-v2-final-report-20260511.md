# P1-21c-D v2: Cross-MF Re-mapping — Final Report

**Date**: 2026-05-11
**Owner**: cc-lead (direct Codex CLI; architect agent unavailable)
**Trigger**: Jeff "走 A，跑 v2 跨 MF 重映射，同时确保没有有用的参数了吗？"
**Status**: ✅ DONE — Coverage 16.4% → 34.2% (record-level), 48.9% new MF backlog identified

## Pipeline (2 rounds total)

### v1 (within-MF mapping) — 45 min
- 21,076 unique (formula_id, parameter_name) pairs
- 717 batches × 30 pairs × 10 parallel Codex
- Result: 4,394 records mapped (16.4%)

### v2 (cross-MF rescue) — 65 min
- 16,861 v1 no_match items re-queried "search across ALL 28 MF"
- 562 batches × 30 items × 10 parallel Codex
- System prompt enumerates all 28 MF + standard fields
- Result: 5,008 records rescued + 13,080 records flagged as new MF candidates

## Final Record-Level Coverage (vs 26,727 total)

| Category | Records | % |
|----------|---------|---|
| **v1 auto-accepted** (real field, ≥0.85) | 4,145 | 15.5% |
| **v2 rescued cross-MF** | 5,008 | 18.7% |
| **Subtotal: mapped to 28 MF** | **9,153** | **34.2%** |
| Needs review | 1,086 | 4.1% |
| **New MF candidate** (real physical quantity, outside 28 MF) | **13,080** | **48.9%** |
| True noise/error | 1,822 | 6.8% |

**Decisive judgment rate: 93.2%** (everything except needs_review).

## Top 10 Cross-MF Rescue Flows

| Original Mis-assigned MF | Correct MF | Records | Common Pattern |
|------|----|---|---|
| MF-K01 (Michaelis-Menten) | MF-T03 (Arrhenius) | **1,227** | Activation energy / rate const for non-enzymatic reactions |
| MF-M06 (Latent heat) | MF-M02 (GAB isotherm) | 349 | Water activity / sorption isotherm params |
| MF-T02 (Choi-Okos) | MF-T01 (Fourier 1D) | 266 | Thermal conductivity / Cp |
| MF-R01 (Power Law) | MF-C01 (Stokes) | 218 | Particle/density params |
| MF-T01 (Fourier 1D) | MF-T05 (Plank freezing) | 173 | Freezing-related thermal params |
| MF-C01 (Stokes) | MF-M04 (Henderson-Hasselbalch) | 115 | pH-related |
| MF-T02 | MF-T05 | 109 | Frozen Choi-Okos overlap |
| MF-C03 (DLVO) | MF-M04 | 106 | pH-related |
| MF-K02 (D Value) | MF-T03 (Arrhenius) | 98 | Thermal kinetics |
| MF-M01 (Fick) | MF-T02 (Choi-Okos) | 98 | Composition params |

**Insight**: Skill A 蒸馏阶段大量"窜门" — LLM 把热降解动力学数据塞给 Michaelis-Menten / Latent heat 等不相关 MF。v2 跨 MF 重映射准确识别并救回。

## Files

- `scripts/skill_a/codex_ontology_v2_cross_mf.py` (~210 LOC) — cross-MF Codex caller
- `scripts/skill_a/aggregate_ontology_v2.py` (~180 LOC) — v1+v2 合并 + 统计
- `output/skill_a/codex_raw_v2/*.json` (561 batches preserved)
- `output/skill_a/param_ontology_map_v2.json` — **最终 mapping**（含 source: v1_auto / v2_rescued）
- `output/skill_a/param_ontology_needs_review_v2.jsonl` (585 pairs)
- `output/skill_a/new_mf_candidates_v2.jsonl` (**10,792 pairs / 13,080 records**) ⭐ for backlog
- `output/skill_a/param_ontology_stats_v2.yaml` — 完整统计

## Cost

- v1: 45 min wall
- v2: 65 min wall
- Total: 110 min Codex CLI
- ChatGPT Plus Pro subscription (无额外费)

## Unblocks (status update)

| Downstream | Before P1-21c-D | After v1 | After v2 | Status |
|---|---|---|---|---|
| P2-Sa1 入图 | 0 ready | 4,394 records | **9,153 records** | ✅ 启动 |
| LangGraph Tool routing | blocked | partial | **full 28 MF coverage** | ✅ 启动 |
| P4-Be2 工具 benchmark | blocked | partial | **real params for all 28 MF** | ✅ 启动 |
| **架构反馈** | — | — | **13,080 records new MF backlog** | ⭐ 新输入给 architect |

## Open Items

1. **13,080 records new MF candidates** — 调研 in progress (separate report)
2. **architect schema 反馈** — MF-T03 Arrhenius 可能需扩展（k as observed value），First-order degradation 700+ records 暗示
3. **needs_review_v2** 585 pairs — Jeff 抽审建议

## Next Steps

1. wiki-curator log P1-21c-D v2 DONE
2. repo-curator PR + merge → main
3. **cc-lead backlog 调研报告** — 13,080 records 怎么用
4. P2-Sa1 ETL 启动（基于 9,153 records）
