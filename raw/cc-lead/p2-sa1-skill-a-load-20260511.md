# P2-Sa1 Skill A → MF Value Database — Completion Report

**Date**: 2026-05-11
**Owner**: cc-lead (direct execution; architect unavailable per Jeff)
**Trigger**: Jeff "全部直接推进，arch 不可用，你直接开干"
**Status**: ✅ DONE — 11,004 records mapped (41.2% of 26,727)

## Pipeline (3 phases, all cc-lead direct)

### Phase 1: P2-Sa1 ETL — base 9,153 records
- `scripts/skill_a/etl/build_mf_value_database.py`
- Reads `param_ontology_map_v2.json` + 94 books × Skill A `results.jsonl`
- Output: `output/skill_a/mf_parameter_value_database.yaml` (28 MF × 128 fields with distribution stats)

### Phase 2: 6 MF schema extensions
- `scripts/skill_a/etl/extend_mf_schemas.py`
- Modified: `config/solver_bounds.yaml` (+12 fields) + `config/mother_formulas.yaml` (+12 units) + `config/mf_fingerprints.json` (+65 keywords/params)
- Schema updates:
  - **MF-T03** + `observed_k` (s⁻¹, [1e-12, 1e3]) + `reaction_order` (dimensionless, [0, 3])
  - **MF-T02** + `composition.{salt,sugar,alcohol}` (mass fraction)
  - **MF-K01** + `pH_opt` (pH) + `T_opt` (°C)
  - **MF-M02** + `Q_iso` (J/mol)
  - **MF-K02** + `D_radiation_kGy` (kGy)
  - **MF-M04** + `pKa1/pKa2/pKa3` (dimensionless)
- pytest baseline: 400 passed, no regression

### Phase 3: Rule-based backlog rescue
- `scripts/skill_a/etl/rescue_backlog_to_new_fields.py`
- 13,080 backlog records scanned, 1,358 pairs / **1,851 records rescued** by keyword pattern matching
- Re-ran ETL with v3 mapping → `mf_parameter_value_database.yaml` updated

## Final Coverage

| Phase | Mapped Records | % of 26,727 |
|-------|----------------|-------------|
| v1 within-MF (P1-21c-D v1) | 4,394 | 16.4% |
| v1 + v2 cross-MF | 9,153 | 34.2% |
| **+ v3 rule-based rescue to new fields** | **11,004** | **41.2%** |

**+1,851 records 救回** to new schema slots (MF-T03.observed_k 主导)

## Top 10 (MF, field) by Record Count

| Rank | MF.Field | n | SI range | Median | Unit |
|------|----------|---|----------|--------|------|
| 1 | MF-T03.Ea | 1,540 | [4.47, 150.0] | 18.53 | kcal/mol |
| 2 | **MF-T03.observed_k** ⭐NEW | 1,393 | [1.8e-6, 21,600] | 0.0056 | min⁻¹ |
| 3 | MF-T01.k | 819 | [0.028, 202.0] | 0.488 | W/(m·K) |
| 4 | MF-M02.a_w | 592 | [0.20, 0.98] | 0.79 | a_w |
| 5 | MF-T01.Cp | 553 | [0.4, 4000] | 3.78 | kJ/(kg·°C) |
| 6 | MF-T02.T_C | 425 | [-12, 202] | 42.5 | °C |
| 7 | MF-M04.pKa | 285 | [1.76, 11.4] | 4.8 | dimensionless |
| 8 | MF-T01.rho | 279 | [0.65, 7849] | 967.0 | kg/m³ |
| 9 | MF-T05.T_m | 254 | [-41.1, 263] | 34.0 | °C |
| 10 | MF-R05.Tg | 250 | [-93, 265.9] | 30.85 | °C |

**总 28 MF × 136 (MF, field) pairs covered**

## 12 New MF Candidates Backlog

Written to `config/new_mf_candidates_backlog.yaml` (P3-P4 phase implementation):

| Tier | MF | Records | Use case |
|------|----|---------| ---------|
| 1 | **MF-T06 Protein_Denaturation** | 271 | Sous-vide / 蛋白加工 |
| 1 | **MF-K06 Growth_Limit** | 170 | 食品安全 hurdle technology |
| 1 | MF-T07 Dielectric_Properties | 211 | 微波/RF 加热设计 |
| 1 | MF-T10 Starch_Gelatinization | 156 | 淀粉加工 |
| 2 | MF-M07 Solubility_Partition | 198 | 香精/营养溶解 |
| 2 | MF-M08 Gas_Permeability | 181 | 包装设计 |
| 2 | MF-T08 Ohmic_Heating | 134 | 欧姆加热 |
| 2 | MF-K07 Binding_Equilibrium | 110 | 香气保留 |
| 3 | MF-T09 Respiration_Heat | 87 | 冷链物流 |
| 3 | MF-M09 Osmotic_Pressure | 60 | 渗透脱水 |
| 3 | MF-M11 SCFE_Solubility | 55 | 超临界萃取 |
| 3 | MF-M10 Membrane_Transport | 41 | 膜分离 |

Tier 1 优先级最高（4 个核心食品工程主题）。Per MF 实施约 1-2 天（solver + bounds + fingerprint + tests）。

## QC Notes (`output/skill_a/p2_sa1_qc_report.yaml`)

- value_parse_failed: 929 records（值无法转 SI scalar，留待 P2-Sa2 人审）
- 异常值警告：
  - MF-M01.D_eff 含 -11.09 m²/s（负值显然 LLM 蒸馏 log scale 没标好）
  - MF-T01.k max=202 W/(m·K)（金属容器 conductivity 错塞）
  - MF-T01.rho max=7849 kg/m³（金属密度错塞）
- 这些 outliers 在 P2-Sa2 抽审（architect + Jeff）时清洗

## Files Produced

### Scripts
- `scripts/skill_a/etl/build_mf_value_database.py` (~210 LOC)
- `scripts/skill_a/etl/extend_mf_schemas.py` (~150 LOC)
- `scripts/skill_a/etl/rescue_backlog_to_new_fields.py` (~130 LOC)

### Config (modified)
- `config/solver_bounds.yaml` (+12 fields)
- `config/mother_formulas.yaml` (+12 unit entries)
- `config/mf_fingerprints.json` (+65 keyword/param entries)

### New Config
- `config/new_mf_candidates_backlog.yaml` (12 new MF specs for P3-P4)

### Output (gitignored)
- `output/skill_a/mf_parameter_value_database.yaml` (28 MF × 136 fields)
- `output/skill_a/mf_parameter_records.jsonl` (11,004 record-level)
- `output/skill_a/p2_sa1_qc_report.yaml`
- `output/skill_a/param_ontology_map_v3.json` (mapping with v3 rescue)

### Reports
- `raw/cc-lead/p2-sa1-skill-a-load-20260511.md` (本报告)

## Tests
- pytest tests/l2a + engine/solver/tests: **400 passed**, no regression

## Unblocks

| Downstream | Status |
|-----------|--------|
| LangGraph Tool routing (28 MF physical params real) | ✅ Ready |
| P4-Be2 28 MF tool benchmark (real bounds) | ✅ Ready |
| P2-Sa2 抽样 ≥95% 验证 (architect + Jeff) | ⭐ Next |
| P2-Sa-eval close-loop validation | After P2-Sa2 |
| 12 New MF Tier 1 implementation | P3 backlog |

## Next Steps

1. wiki-curator log P2-Sa1 + MF schema extensions + new MF backlog
2. repo-curator PR + merge
3. **Jeff/architect**: review `config/new_mf_candidates_backlog.yaml` Tier 1（蛋白变性 / 生长极限 / 介电 / 淀粉糊化）— 这 4 个 MF 是 P3 优先实施
4. P2-Sa2 抽样验证（架构师 50 条 + Jeff 30 条 sanity）
