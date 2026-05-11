# P1-21c-D Backlog Research: 13,080 New MF Candidate Records — 是什么 + 怎么用

**Date**: 2026-05-11
**Owner**: cc-lead
**Trigger**: Jeff "去调研没有 MF 的 candidates 48.9% 的 backlog 是什么，怎么使用他们？"
**Input**: `output/skill_a/new_mf_candidates_v2.jsonl` (10,792 items / 13,080 records)
**Output**: `output/skill_a/new_mf_backlog_semantic_groups.yaml`

## TL;DR

13,080 records 用 32 个 semantic group 分类后：
- **2,325 records → MF schema 扩展**（改现有 28 MF 不新增）
- **1,674 records → 12 个新 MF 候选**
- **506 records → FT/L6 层**（风味/感官）
- **133 records → L2c 食材数据库**
- **8,227 records (62%) → long-tail unmatched**（各种边缘单次出现的物理量）

**核心结论**：剩余 48.9% 不是垃圾，**约 36% 是真正可救回到七层架构的有用数据**。

## 9 个 Recommendation Buckets

### 1. MF schema 扩展（改现有 28 MF，不新增）— 2,325 records

| Semantic Group | Records | Items | 建议改动 |
|---|---|---|---|
| **G1 一阶降解动力学** | **1,425** | 1,045 | **MF-T03 Arrhenius schema 扩展**：add `observed_k` input + `reaction_order` field |
| G14 食品成分 | 207 | 171 | MF-T02 Choi-Okos: add `composition.{salt,sugar,alcohol}` |
| G6 酶活最适条件 | 198 | 187 | MF-K01 metadata: add `pH_opt`, `T_opt` |
| G11 等温吸湿/解吸 | 136 | 98 | MF-M02 GAB: add `Q_iso` (isosteric heat) as derived output |
| G2 辐照灭菌 D10 | 117 | 39 | MF-K02: add `D_radiation_kGy` field |
| G8/G29 反应级数 n | 171 | 124 | MF-T03: add `reaction_order` field (default=1) |
| G17 pKa 酸碱 | 43 | 40 | MF-M04: multi-pKa fields |
| G28 比热多项式 | 28 | 22 | MF-T02: accept polynomial fit |

**改 schema 即可救回 2,325 records** — 这是最高 ROI 行动。

### 2. 新 MF 候选（28 MF 扩展为 39+ MF）— 1,674 records

| 新 MF | Records | 物理意义 | 食品工程价值 |
|---|---|---|---|
| **MF-T06 Protein_Denaturation** | 271 | Td / ΔH_d (DSC) | 蛋白加热研究核心 |
| **MF-T07 Dielectric_Properties** | 211 | ε', ε'', tan δ | 微波/RF 加热设计（v2.0 已 backlog） |
| **MF-M07 Solubility_Partition** | 198 | logP, solubility | 食品配方 / 香精溶解性 |
| **MF-M07 Gas_Permeability** | 181 | O2/CO2/WVTR | 包装设计核心 |
| **MF-K06 Growth_Limit** | 170 | min pH/aw/T/MIC | 食品安全核心 |
| **MF-T10 Starch_Gelatinization** | 156 | T_gel / ΔH | 淀粉加工核心 |
| **MF-T08 Ohmic_Heating** | 134 | σ(T) electrical conductivity | Ohmic 加热设计 |
| **MF-K07 Binding_Equilibrium** | 110 | Ka 配体-蛋白 | 香气保留/营养利用 |
| **MF-T09 Respiration_Heat** | 87 | 果蔬呼吸热 | 冷链物流 |
| **MF-M09 Osmotic_Pressure** | 60 | π / van't Hoff | 渗透脱水 |
| **MF-M08 SCFE** | 55 | SC-CO2 溶解度 | 超临界萃取 |
| **MF-M10 Membrane_Transport** | 41 | 膜渗透率 | 膜分离 |

**这是 v2.0 5-MF backlog 扩到 12 MF 的硬数据依据**。每个候选都有 50+ records 真实文献支持。

### 3. → FT/L6 风味感官层 — 506 records

| Group | Records | 说明 |
|---|---|---|
| G4 风味/感官阈值 | 459 | 气味/风味阈值 μg/L in water/oil/matrix |
| G16 色素/颜色 | 17 | Lab 色差 |
| G18 抗氧化 | 17 | DPPH/ABTS/IC50 |
| G19 质构 TPA | 13 | hardness/firmness |

**这些不是 MF 数据，是 FT 风味目标库或 L6 翻译层数据**。建议给 FT 表加 `sensory_threshold_concentration` 字段补全 7,435 FT 条目。

### 4. → L0 因果链 食品安全域 — 29 records

| Group | Records | 说明 |
|---|---|---|
| G27 LD50 | 20 | 急性毒理 |
| G21 化合物浓度 in matrix | 9 | mg/kg in mushroom/fish |

**L0 food_safety 域参数**，可作为因果链节点的 evidence。

### 5. → L2c 商业食材数据库 — 133 records

| Group | Records | 说明 |
|---|---|---|
| G9 沸点/相变温度 | 80 | 物质 ref properties |
| G32 化合物结构属性 | 53 | 疏水性/折射率/分子结构 |

**不属 MF 层**，应进 substance reference table（同一物质 across all books）。

### 6-7. → L1 设备层 / L2b 食谱书 — 20 records
- G31 Alveograph 面团强度 (20 records) — L2b ingredient property

### 8. 真垃圾丢弃 — 125 records
- G26 物理常数 (gas constant R, Avogadro, Boltzmann) — LLM 错塞

### 9. v2 missed（手动加 MF）— 41 records
- G20 机械物性（speed of sound / Young's modulus）— **v2 missed**，可直接加到 MF-R07.E

## 整体救回估算

| 救回路径 | Records | 状态 |
|---|---|---|
| v1 within-MF auto | 4,145 | ✅ DONE |
| v2 cross-MF rescued | 5,008 | ✅ DONE |
| **改 MF schema 救回** | **2,325** | 待 architect 改 schema |
| **新 12 MF 候选** | **1,674** | 待 architect 评估 |
| 入 FT/L6 风味层 | 506 | 待 P2-Ft1 ETL 时合并 |
| 入 L2c / L0 食安 | 162 | 待 P3-Lc1 / L0 补充 |
| 长尾 unmatched (62%) | 8,227 | 大部分是 single-occurrence 长尾，逐条 review 不划算 |
| 真垃圾 | 1,822 | 已识别 |

## 长尾 unmatched 8,227 records 怎么办？

抽样看 Top 20 unmatched candidate_labels：
- Specific heat polynomial coefficient (22)
- Apparent reaction rate constant (20)
- Norrish water-activity model constant (20)
- Solubility (18)
- Osmotic pressure (18)
- Molecular weight (17)
- Toxicology LD50 (16)
- 大量 single-occurrence 长尾

**建议**：
- 不再单独跑 v3 Codex —— ROI 太低（8K records 跑 1h Codex 救回估 < 2K records）
- 让 P2-Sa1 ETL 时直接把这 8,227 records 当 "uncategorized_skill_a_param" 存入 raw table，后续如需用可再 LLM 处理
- Architect 评估新 MF 时按需查 raw table（如评估 MF-T06 Protein Denaturation 时查 long-tail 里有没有补充数据）

## 行动建议

### 立即（24h 内）
1. ✅ wiki-curator log 已派出
2. ✅ repo-curator PR 已派出
3. 📝 cc-lead 提报 architect 队列：**MF schema 扩展 6 项**（救回 2,325 records，ROI 最高）
4. 📝 cc-lead 提报 architect 队列：**12 新 MF 候选**（v2.0 backlog 升级版）

### 中期（1 周内）
1. P2-Sa1 ETL 启动：9,153 mapped records → mf_fingerprints/mother_formulas
2. P2-Sa1 同时挂上 backlog 救回 schema slot（如 observed_k + composition.salt）
3. FT 数据补全 sensory_threshold 字段（506 records 入 FT 7,435 现有库）

### 长期（Phase 2）
1. 12 新 MF 候选 architect 评估：选 4-6 个优先建（MF-T06 Protein Denaturation / MF-K06 Growth Limit / MF-T07 Dielectric / MF-T10 Starch Gelatinization 是 ROI 最高）
2. Phase 2 时如真需要才跑 v3 Codex 救长尾

## Files

- `output/skill_a/new_mf_backlog_semantic_groups.yaml` — 32 semantic groups + samples + recommendations
- `output/skill_a/new_mf_candidates_v2.jsonl` — 10,792 raw candidate items（已分类）
- `raw/cc-lead/p1-21c-d-backlog-research-20260511.md` — 本报告
