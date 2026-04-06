# 架构 Briefing：L0-L5 推理引擎如何在现有技术栈上完成

> researcher agent → CC Lead / 架构师
> 2026-03-27
> 基于 5 份调研报告 + roadmap_priorities_v2 + STATUS.md + 当前技术栈

---

## 一、当前全局状态

### 七层架构 × 完成度

| 层 | 名称 | 状态 | 数据量 | 技术栈 |
|---|---|---|---|---|
| **L0** | 科学原理图谱 | 🔄 蒸馏中 | 35,045 条（21/46本） | Opus 提取 → JSONL |
| **L1** | 设备实践参数 | ⏳ 未建 | — | — |
| **L2a** | 天然食材参数库 | 🔄 Pilot 75种 | 75 ingredients | Gemini Search → JSON |
| **L2b** | 食谱校准库 | 🔄 Step A 在跑 | 21,414 recipes（41本书） | flash 提取 → JSONL |
| **L2c** | 商业食材数据库 | ⏳ 未建 | — | — |
| **FT** | 风味目标库 | ⏳ 未建 | — | — |
| **L3** | 推理引擎 | ⏳ 设计中 | — | LangGraph（规划） |
| **L6** | 翻译层 | ⏳ 未建 | — | — |

### 当前技术栈

| 组件 | 选型 | 状态 |
|---|---|---|
| OCR | qwen3.5-flash (DashScope) | ✅ 生产中 |
| 文本切分 | qwen3.5:2b (Ollama) | ✅ 生产中 |
| 标注/筛选 | qwen3.5:9b/27b (Ollama) | ✅ 生产中 |
| L0 蒸馏 | Opus 4.6 (灵雅代理) | ✅ 生产中 |
| 食谱提取 | qwen3.5-flash (DashScope) | ✅ 生产中 |
| L2a 蒸馏 | Gemini 3 Flash + Search Grounding (灵雅代理) | ✅ Pilot 完成 |
| Embedding | qwen3-embedding:8b (Ollama) | ✅ 生产中 |
| Agent 框架 | LangGraph | ⏳ 规划中 |
| 图数据库 | Neo4j 5.x (graph + vector) | ⏳ 规划中 |
| 动态记忆 | Graphiti | ⏳ 规划中 |
| 项目管理 | Dify (本地 Mac Studio) | ✅ 运行中 |

---

## 二、关键调研发现（影响架构的）

### 发现 1：三跳链路是 L2→L0 的最优连接方式

```
Ingredient -[:CONTAINS]-> Compound -[:GOVERNED_BY]-> ScientificPrinciple
                                  (FoodAtlas/FooDB)     (our L0)

ProcessStep -[:TRIGGERS]-> ScientificPrinciple
                          (直接绑定)
```

两套机制并行：
- **静态边**（预计算）：FoodAtlas + FooDB 化合物数据 → Neo4j
- **向量边**（运行时）：Neo4j vector index on L0 embeddings

### 发现 2：L2a 食材种子从 L2b 食谱中来

Stage 5 已提取 21,414 食谱 → 102,227 次食材提及 → 归一化后 ~3,000 canonical ingredients。这比从 USDA 出发更精准（只有厨师真正用的食材）。

### 发现 3：没有外部项目覆盖我们的核心链路

```
外部数据覆盖：Ingredient → Compounds → Generic Sensory Descriptors

我们的护城河：
  Compound × Concentration × Cooking Method
    → Transformed Profile → Cuisine-Specific Evaluation → Aesthetic Judgment
  (L0)                      (FT)                          (L6)
```

### 发现 4：67 个外部数据库可用，32 个可直接下载

核心 ~3GB 数据覆盖 L0 全 17 域 + L2a + FT。最重要的：
- FlavorDB2（25MB）— 化合物→感官描述映射
- FooDB（MySQL dump）— 食材→化合物（含浓度）
- ComBase（60K微生物曲线）— food_safety 参数
- BRENDA（7K酶数据）— enzyme 参数
- FoodLLM-Data（500MB）— 20万中文食谱
- 日本/韩国食品成分表 — USDA 缺的亚洲食材

### 发现 5：风味/审美层是全球没人做过的

- 东亚菜系（含粤菜）倾向「对比配对」（Ahn 2011）
- 质地偏好是文化差异最大的维度
- 没有中文感官本体论（"镬气"、"鲜"、"口感爽滑"无机器可读定义）
- FT + L6 合起来是我们独创的东西

### 发现 6：YouTube 视频可以用 yt-dlp + Gemini API 半自动提取

NotebookLM 无 API 不能自动化，但 yt-dlp 批量抽字幕 + Gemini Flash 筛选 + Gemini Pro 深度提取可以处理 200+ 视频，成本 ¥200-1200。适合补充粤菜食材知识（寻味顺德、老广的味道、Chinese Cooking Demystified）。

---

## 三、架构师需要回答的问题

### Q1：L2a schema 定稿

现有 pilot schema（l2a_pilot_test.py Round 1+2）+ 调研建议的新字段：

```
现有字段（已验证）：
  ingredient_zh/en, category, varieties[], cuisine_context,
  storage_notes, freshness_window_days, key_science,
  latitude/longitude, peak_months, season_reason, sources

需要加的字段：
  + market_regions[]       → 支持"春季广东"查询
  + best_state_description → 食材巅峰状态描述
  + composition{}          → 来自 USDA (protein%/fat%/moisture%)
  + source_books[]         → 从 L2b 食谱溯源
  + wikidata_qid           → 跨系统实体链接
  + usda_fdc_id            → USDA 交叉引用
```

**问题**：这个 schema 是否够用？还是需要进一步讨论后锁定？

### Q2：Neo4j 统一图谱 vs 路线图的 Weaviate 温层

路线图 v2 写了三层存储：
- 热层 Neo4j（graph + 已决定用内置向量索引替代 Weaviate，决策 #26）
- 温层 Weaviate（向量检索）
- 冷层 PostgreSQL/Neo4j 冷实例

但决策 #26 已经说了「Neo4j 内置向量索引替代 Weaviate」。

**问题**：Weaviate 是否还需要？还是 Neo4j 内置向量索引 + 冷层就够了？

### Q3：L2a 建设路线

两条路线需要选：
- **路线 A**：先从 USDA 出发建骨架 → 再 Gemini 蒸馏
- **路线 B**（调研建议）：先从 L2b 食谱提取种子 → USDA 匹配补成分 → 再 Gemini 蒸馏

路线 B 更精准但多一步。Jeff 倾向 B。

**问题**：确认走 B？

### Q4：L2a 多层蒸馏法

Jeff 提出的方法：
1. 通用英文食材骨架（~3,000 canonical ingredients）
2. 问 LLM「这个食材在不同菜系的变种是什么？」→ 展开品种
3. 每个变种再问「最佳产地/季节/在哪些市场可得？」
4. 风味/审美描述留 Jeff 人工校准

**问题**：这个蒸馏顺序是否写入正式流程？

### Q5：外部数据导入时机

32 个可下载数据库，总共 ~3GB。建议分 4 批导入（见 database-availability-audit.md）。

**问题**：Phase 1（FlavorDB2/BitterDB/SuperSweet 等化学数据）现在就开始下载，还是等 Neo4j 搭好再下？

### Q6：FT（风味目标层）的起步方案

调研确认没有外部源能直接提供，需要自建。建议：
- Civille 质地词汇表做可量化底座（~25 个质地属性，0-15 标度）
- 从 40+ 本书里 LLM 提取中文审美词汇
- L6 做桥梁（中文审美词 ↔ Civille 可量化参数）
- FlavorDB2 + FooDB 提供化学骨架

**问题**：FT 层是 P5 之后再启动，还是跟 L2a 并行开始？

### Q7：YouTube 视频提取是否纳入 L2a pipeline

200+ 中文烹饪视频（风味人间、老广的味道等）可补充粤菜食材知识。

**问题**：现在启动还是等 L2a schema 定了再做？

### Q8：L1（设备实践参数层）的优先级

目前完全未建。YouTube 视频（尤其是技法演示类）对 L1 最有价值。

**问题**：L1 排在什么位置？是否跟 L2a 并行，还是等 P5 之后？

---

## 四、建议的整体数据流（供架构师确认）

```
书籍 PDF                  YouTube 视频              外部数据库
   │                          │                        │
   ├─ Stage1 切分              ├─ yt-dlp 抽字幕          ├─ USDA API
   ├─ Stage4 L0 蒸馏           ├─ Gemini 提取             ├─ FooDB dump
   ├─ Stage5 L2b 食谱提取      └─ L2a 补充                ├─ FlavorDB2
   │                                                     ├─ ComBase
   │                                                     └─ BRENDA
   ▼                                                        │
┌─────────────────────────────────────────────────────────────┐
│                    Neo4j 统一图谱                            │
│                                                             │
│  (:ScientificPrinciple)  ← L0 (35K+ 节点)                  │
│       ↑ GOVERNED_BY                                         │
│  (:Compound)             ← FooDB + FlavorDB2                │
│       ↑ CONTAINS                                            │
│  (:Ingredient)           ← L2a (~3K canonical)              │
│       ↑ USES                                                │
│  (:ProcessStep)          ← L2b recipes (21K+)               │
│       ↑ HAS_STEP                                            │
│  (:Recipe)               ← L2b (ISA-88 SubRecipe/Recipe)    │
│                                                             │
│  (:FlavorCompound)       ← FlavorDB2                        │
│  (:SensoryDescriptor)    ← FT（自建）                        │
│  (:CuisinePreference)    ← FT × L6（自建）                  │
│                                                             │
│  Vector Index: L0 embeddings + L2a embeddings               │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌──────────────────────┐
              │    L3 推理引擎        │
              │    (LangGraph)       │
              │                      │
              │  Graph RAG (Neo4j)   │
              │  + Vector Search     │
              │  + Opus/Sonnet 推理   │
              │  + Graphiti 记忆      │
              └──────────────────────┘
                          │
                          ▼
              ┌──────────────────────┐
              │    用户接口           │
              │    "我要春季广东菜单"   │
              │                      │
              │  → L2a: 春季广东食材   │
              │  → L0: 科学原理约束    │
              │  → L2b: 可用食谱模板   │
              │  → FT: 粤菜审美偏好   │
              │  → L6: 粤菜语言翻译   │
              │  → L3: 组合推理生成    │
              └──────────────────────┘
```

---

## 五、调研报告索引

| 报告 | 路径 | 核心内容 |
|------|------|---------|
| L0-L2 链路 | docs/research/l0-l2-linking-research.md | 三跳架构 + Neo4j 模式 |
| 搜索型 LLM | docs/research/search-grounded-llms-for-ingredient-data.md | Gemini/Perplexity 评估 |
| 多层建模 | docs/research/multi-layer-food-knowledge-modeling.md | 风味网络 + 审美层 + 护城河 |
| 数据库全量 | docs/research/exhaustive-food-databases-survey.md | 67 个资源评估 |
| 下载审计 | docs/research/database-availability-audit.md | 32 可下载 / 12 需爬 / 17 不可得 |
| NotebookLM+YouTube | docs/research/notebooklm-youtube-food-extraction.md | 视频提取方案 + 频道清单 |
