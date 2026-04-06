# L2a 食材原子 Schema v2 — 设计推敲文档

> 角色：researcher + architect 联合推敲
> 日期：2026-03-26
> 状态：待 Jeff 拍板 7 个决策点

---

## 0. 执行摘要

L2a 是整个系统里粒度最敏感的层。它不是 USDA 的营养表，也不是菜谱的食材列表——它是一个**有地域维度、有季节维度、有工艺状态的参数化食材节点**，同时充当 L2b 食谱和 L0 科学原理之间的桥梁。

核心结论先列：
1. 原子粒度 = **烹饪功能粒度**，不是生物分类粒度，也不是部位粒度
2. Variety 单独拆节点（不内嵌 JSON 数组），是图谱遍历的基本单位
3. `processing_states` 是必需字段，它是同一原子在不同物理状态下的参数集
4. L0 绑定走 `l0_domain_tags[]` + 运行时向量搜索双轨，不在 schema 里硬编码 principle_ids
5. Wikidata QID 是主锚，USDA fdcId + FooDB food_id 挂在同一节点上，三库可联查
6. 全量 3,000 原子蒸馏估算：两轮，约 ¥800-1,200，6-8 天

---

## 1. Researcher 视角：外部数据兼容性分析

### 1a. USDA FoodData Central — 数据结构与对接方式

**USDA FDC 有四个子库，对 L2a 的价值不同：**

| 子库 | 描述 | L2a 价值 |
|------|------|---------|
| Foundation Foods | 每种食物最完整的营养+化学成分，含多项分析方法 | **最高** — 用这个 |
| SR Legacy | 8,789 种食材，USDA 历史标准参考 | 高 — 补充覆盖 |
| FNDDS | 美国居民实际消费食物，含混合食物 | 低 — L2c 范畴 |
| Branded | 品牌包装食品 | L2c，不是 L2a |

**FDC API 核心字段结构（一个 food 条目）：**
```json
{
  "fdcId": 171077,
  "description": "Chicken, broilers or fryers, breast, meat only, raw",
  "foodClass": "FinalFood",
  "foodNutrients": [
    {
      "nutrient": {"id": 1003, "name": "Protein", "unitName": "g"},
      "amount": 23.2,
      "min": 20.1,
      "max": 26.4,
      "median": 23.0
    }
  ],
  "foodCategory": {"description": "Poultry Products"},
  "scientificName": "Gallus domesticus",
  "dataType": "Foundation"
}
```

**关键洞察：**
- USDA fdcId 是精确到**部位+处理状态**的（鸡胸生肉 vs 鸡腿熟肉 是两个 fdcId）
- 这意味着一个 L2a 原子（"鸡"）会对应**多个** fdcId，需要映射表而不是 1:1 绑定
- Foundation Foods 有 min/max/median，适合做边界条件校准（和 L0 boundary_conditions 对齐）
- 下载 CSV 文件：food.csv + nutrient.csv + food_nutrient.csv，三表关联，JOIN 键是 fdc_id

**对接设计：**
```
(:Ingredient {atom_id: "chicken"})
  -[:HAS_USDA_ENTRY {part: "breast", state: "raw"}]->
(:UsdaFood {fdcId: 171077, description: "..."})
```
不把 USDA 数据内嵌进原子节点，而是用关系边指向独立 UsdaFood 节点。这样 L2c（商业食材）也能用同一模式挂 USDA Branded。

---

### 1b. FoodAtlas — food-compound 关系格式与链接方式

FoodAtlas（2024, ScienceDirect）是目前最适合 L2a→L0 桥接的外部资源：
- 1,430 种食材 × 3,610 种化学物质 × 48,474 条 food-chemical edges
- 通过文本挖掘（transformer NLP）从 125,723 篇文献自动抽取
- 还包含 3,645 条 chemical-flavor 关系（覆盖 958 种风味描述词）

**数据格式（GitHub TSV）：**
```
food_id   food_name     compound_id   compound_name   confidence   source_pmid
F001      chicken       C0023419      L-carnitine     0.92         12345678
```

**链接到 L2a 原子的方式：**
```
(:Ingredient {atom_id: "chicken"})
  -[:CONTAINS {confidence: 0.92, source: "foodatlas"}]->
(:Compound {compound_id: "C0023419", name: "L-carnitine"})
  -[:GOVERNED_BY {domain: "protein_science"}]->
(:ScientificPrinciple {principle_id: "..."})
```

**关键问题**：FoodAtlas 的粒度是食材类（"chicken"），不区分部位和地域品种。这正好和我们"原子"粒度对齐，不是品种粒度。Variety 层的化学差异需要靠 FooDB + 文献补充。

---

### 1c. FoodOn 分类层次 — 是否适合做 L2a category？

FoodOn 结构：
- 27,000+ classes，基于 BFO（Basic Formal Ontology）
- 顶层分类：food material → food product → processed food
- 核心层级：`FOODON:food_source`（来源，动植物分类） + `FOODON:product_type`（产品类型，加工方式）

**能用的：**
- 顶层类别：poultry / seafood / legume / allium / brassica 等——和我们的 category 字段对齐
- FoodOn class ID 可以作为标准化锚点（比自造 category 字符串更稳定）

**不能照搬的：**
- FoodOn 的层级是食品安全/溯源导向的，粒度过粗（不区分清远鸡和文昌鸡）
- 它的中文支持很弱（有 "Multilingual Labels for FoodOn" 项目但尚不完整）
- OWL 本体导入 Neo4j 需要 neosemantics 插件，有维护成本

**建议**：用 FoodOn class ID 作为 `foodon_class_id` 附属字段，但不用 FoodOn 的层次结构作为 L2a 的主分类树。主 category 用项目自定义词表（15-20个类别），稳定可控。

---

### 1d. FooDB — food-compound 浓度数据

FooDB（foodb.ca）是化学成分最详细的食物数据库：
- 797 种食物，70,926 种化合物（含浓度范围）
- 每条记录包含：food_name, compound_name, orig_content（浓度值）, orig_unit, min/max
- 关键：直接提供香气化合物（aroma_volatiles 域）、色素（color_pigment 域）的浓度数据

**对 L2a 的价值**：补充 USDA 没有的微量化合物（风味分子、色素、多酚）

**schema 对接**：FooDB 的 food_id 可以加进原子节点，ETL 时建 CONTAINS 边指向 Compound 节点（和 FoodAtlas 同样的 pattern）

---

### 1e. 中英双语名称标准化 — Wikidata QID 够不够？

**结论：Wikidata QID 是必要条件，但不够充分。**

Wikidata 的优势：
- QID 是稳定 URI，机器可读，桥接 Wikipedia / FoodOn / USDA
- 支持多语言 label 和 aliases（包括繁简中文、粤语、日文）
- WikiProject Food 有专门的食物属性集（P5930 = Open Food Facts ID 等）

Wikidata 的局限：
- 中国地区性品种（清远鸡、马蹄、莲藕品种）Wikidata 条目质量差，有的根本没有
- 粤菜专业术语和市场名（"走地鸡"、"豉香"）没有 QID
- 不能完全依赖 Wikidata 做中文规范化

**推荐标准化策略（三层）：**
1. **规范名（首选）**：中文简体 + 英文 snake_case（`name_zh` + `name_en`）
2. **别名列表**：`aliases[]` 收录粤语名、繁体、地方称谓、市场名
3. **外部 ID 锚点**：`wikidata_qid`（主锚）+ `usda_fdc_id`（成分锚）+ `foodb_id`（化合物锚）+ `foodon_class_id`（分类锚）

---

## 2. Architect 视角：Schema 设计审查

### 2a. 粒度问题 — 原子应该在哪个层次？

**核心判据：烹饪功能替代性**

> 一个"原子"= 在食谱中**不可直接互换**、需要独立参数描述的最小食材单元

**鸡的粒度分析：**

| 候选原子 | 独立参数？ | 功能可替代？ | 结论 |
|---------|-----------|------------|------|
| 鸡（整体） | 共同原理，但部位完全不同 | 鸡胸 ≠ 鸡腿 在食谱里 | ❌ 太粗 |
| 鸡胸 | 蛋白质含量/纤维走向/最优熟成温度独立 | 不能替换鸡腿 | ✅ 合适 |
| 鸡腿 | 肌红蛋白高/脂肪多/最优温度不同 | 不能替换鸡胸 | ✅ 合适 |
| 清远鸡胸 | 和普通鸡胸原理相同，只是参数值不同 | 参数有差异但功能相同 | ❌ 这是 variety |

**结论：鸡 → 拆分为 `chicken_breast`、`chicken_thigh`、`chicken_wing`、`chicken_skin`、`chicken_liver` 等部位原子。** 整体的 "chicken" 可保留为父节点做分组，但不是独立原子。

**酱油的粒度分析：**

| 候选原子 | 独立参数？ | 功能可替代？ | 结论 |
|---------|-----------|------------|------|
| 酱油（整体） | 盐度/色度/鲜味强度差异极大 | 不同类型在食谱里不可换 | ❌ 太粗 |
| 生抽 | 浅色/高鲜/低盐（相对） | 不能替换老抽上色 | ✅ 合适 |
| 老抽 | 深色/低鲜/着色功能 | 不能替换生抽提鲜 | ✅ 合适 |
| 日本浓口酱油 | 低盐/甜/不同微生物群 | 功能接近生抽但参数不同 | ✅ 合适 |
| 白酱油 | 极浅色/特殊用途 | 独特功能 | ✅ 合适 |

**结论：酱油 → 拆分为功能性子类型原子。** 父节点 "soy_sauce" 做分组。

**粒度规则（见第 4 节完整版）**

---

### 2b. Variety 膨胀问题

大宗食材（rice、flour、apple）有几百个品种，必须控制膨胀。

**控制策略：**

**策略 A — 重要度过滤**：只收录满足以下任一条件的 variety：
1. L2b 食谱里实际出现过（出现频次 ≥ 3）
2. 粤菜/广东餐饮体系中有显著地位
3. 有明确区别性的参数（淀粉结构、蛋白含量、风味分子显著不同）

**策略 B — 优先级评分字段**：给每个 variety 加 `importance_score: 1-5`
- 5 = 粤菜核心品种，必须精确描述
- 3 = 常见品种，需基本参数
- 1 = 稀有/存档，只记录名称

**对 rice 的实际限制**：全球水稻品种 40,000+，我们只收：
- 广东在地：丝苗米、增城丝苗、象牙香占、泰国香米（进口）
- 烹饪功能显著不同：糯米、粳米、籼米（基础分类）
- 出现在食谱库里的：扫描 L2b 29,085 条食谱自动提取

**预估 rice 原子下的 variety 数量**：15-20 个（不是 40,000）

---

### 2c. Neo4j 节点设计

**结论：Variety 必须拆成独立节点，不能内嵌 JSON 数组。**

内嵌数组的问题：
- 无法做 `MATCH (v:Variety {region: "广东"})` 这样的过滤
- 无法给 variety 单独挂 USDA 节点或 FooDB 节点
- 无法做 variety 之间的 `[:COMPARED_TO]` 关系

**推荐节点模型：**

```cypher
// 核心节点
(:Ingredient {atom_id, name_zh, name_en, category, ...})
(:Variety {variety_id, name_zh, name_en, region, ...})
(:ProcessingState {state_id, state_type, description, ...})
(:Compound {compound_id, name, cas_number, ...})
(:ScientificPrinciple {principle_id, domain, ...})  // 已有 L0
(:UsdaFood {fdcId, description, ...})

// 关系
(:Ingredient)-[:HAS_VARIETY {importance_score}]->(:Variety)
(:Ingredient)-[:HAS_STATE]->(:ProcessingState)
(:Ingredient)-[:CONTAINS {confidence, source}]->(:Compound)
(:Ingredient)-[:LINKED_USDA {part, state}]->(:UsdaFood)
(:Ingredient)-[:RELATED_TO {relation_type: "substitute"|"complement"|"variant"}]->(:Ingredient)
(:Variety)-[:BEST_FOR {technique}]->(:Technique)  // 可选，第二期
(:Ingredient)-[:BRIDGES_TO {domain, confidence}]->(:ScientificPrinciple)  // 运行时向量推断后写入
```

**关键设计决策**：L0 绑定不在 ETL 时硬写。先靠向量搜索在运行时发现，积累一定置信度后再固化为图谱边。这样避免 ETL 阶段 LLM hallucination 污染图谱。

---

### 2d. 缺失字段评估

| 字段 | 专业厨房需要？ | 评估结论 |
|------|-------------|---------|
| `allergens[]` | **必须** — 过敏原是法律合规要求，专业厨房刚需 | ✅ 加入 |
| `substitutes[]` | 重要 — 缺货时推理引擎的第一步 | ✅ 加入（作为 Neo4j 关系，不是数组） |
| `flavor_profile{}` | 重要 — FT 层的前置，但和 FT 层重叠 | ⚠️ 加入简化版（5 基础维度），精细版留 FT 层 |
| `price_tier` | 重要 — 成本控制是餐饮老板核心需求 | ✅ 加入（1-5 分级，不用实际价格） |
| `processing_states[]` | **关键** — 同一食材不同状态完全不同参数 | ✅ 加入（独立节点） |

**`processing_states` 是最重要的补充。** 以鸡胸为例：
- `fresh_raw`：pH 5.8-6.2，Aw 0.99，适合 sauté
- `cold_aged_24h`：pH 略降，肌肉松弛，适合 poach
- `frozen_thawed`：细胞壁破损，失水率更高，调整烹饪参数
- `smoked`：Maillard 产物沉积，水活性降低，新的风味前体

不加这个字段，L2b 食谱里的冷冻鸡胸和新鲜鸡胸就没法区分参数。

**`substitutes` 的正确实现：**
```cypher
// 不要在 schema 里硬编码字符串数组
// 要用 Neo4j 关系
(:Ingredient {atom_id: "chicken_thigh"})
  -[:SUBSTITUTABLE_WITH {context: "braising", confidence: 0.85, notes: "需调整烹饪时间"}]->
(:Ingredient {atom_id: "duck_thigh"})
```

---

### 2e. 蒸馏效率

**字段来源分类：**

| 字段类型 | 来源方式 | 工具 |
|---------|---------|------|
| 基础识别（name_zh/en, category, aliases） | Gemini 蒸馏 Round 1 | Gemini 2.5 Pro |
| 科学参数（composition, key_science, domains） | Gemini 蒸馏 Round 2 | Gemini 2.5 Pro |
| 地域 variety（region, peak_months, quality_markers） | Gemini 蒸馏 Round 2 | Gemini 2.5 Pro |
| USDA fdcId | 自动化匹配 | USDA API |
| Wikidata QID | 自动化匹配 | Wikidata SPARQL |
| FooDB food_id | 自动化匹配 | FooDB 下载 CSV |
| processing_states | Gemini 蒸馏 Round 2 | Gemini 2.5 Pro |
| allergens | 自动化 + 人工校验 | USDA + FoodOn |
| price_tier | 人工校准（一次性） | Jeff 决策 |
| importance_score（variety） | Gemini 初始 + 人工确认 | 半自动 |

**两轮够吗？**

两轮是合理的：
- **Round 1（快速扫描）**：给定食材名，提取 name_zh/en/aliases/category/basic_composition/domain_tags/wikidata_qid_guess。每个原子约 200 tokens in + 300 tokens out。
- **Round 2（深度蒸馏）**：给定 Round 1 结果 + 背景书目（我们有 63 本书），填充 varieties/peak_months/quality_markers/processing_states/key_science。每个原子约 500 tokens in + 800 tokens out。

不建议三轮——Round 2 之后的增量回报递减，剩余精化靠 L2b 食谱实际使用中的反馈校正。

---

### 2f. L0 绑定策略

**`key_science` 文本字段如何连接到 44,692 条 L0 原理？**

**双轨策略（已在 STATUS.md 决策#29 和 l0-l2-linking-research.md 中确认）：**

**轨道 1 — 静态域标签（ETL 时填充）：**
蒸馏时同步标注 `l0_domain_tags: ["protein_science", "thermal_dynamics"]`
这是粗粒度绑定，每个原子绑到 1-3 个 L0 域，不绑到具体 principle_id

**轨道 2 — 向量运行时搜索（推理时执行）：**
```cypher
CALL db.index.vector.queryNodes('l0_embedding', 10, $ingredient_embedding)
YIELD node AS principle, score
WHERE score > 0.72
RETURN principle.principle_id, score
```
将 key_science 文本做 embedding，和 L0 全量向量库最近邻搜索，运行时发现具体 principle。

**不建议在 schema 里加 `l0_principle_ids[]` 字段，原因：**
1. ETL 时 LLM 填这个字段准确率低（44,692条要对上，错配率高）
2. 维护成本高（L0 更新后需重新同步）
3. 向量搜索的覆盖率更高，且支持 fuzzy match
4. 积累置信度后可以逐步固化为图谱边（更可信，可溯源）

**在 schema 里保留的 L0 相关字段**：`l0_domain_tags[]`（只绑域，不绑具体条目）

---

## 3. 最终 Schema — 定稿版

### 3.1 Ingredient 节点（原子）

```json
{
  "atom_id": "chicken_breast",
  "name_zh": "鸡胸",
  "name_en": "Chicken breast",
  "name_cantonese": "鸡胸肉",
  "aliases": ["鸡胸肉", "breast meat", "poulet blanc"],
  "category": "poultry",
  "subcategory": "muscle_meat",
  "parent_atom": "chicken",

  "composition": {
    "protein_pct": 23.2,
    "fat_pct": 2.6,
    "moisture_pct": 74.0,
    "carb_pct": 0.0,
    "water_activity": 0.99,
    "ph_range": [5.8, 6.2]
  },

  "flavor_profile": {
    "umami": 3,
    "sweetness": 1,
    "bitterness": 0,
    "sourness": 0,
    "saltiness": 0,
    "richness": 2
  },

  "best_state": "活杀后4°C排酸12-24小时，按压回弹，无异味",
  "storage": {
    "fresh_days": 3,
    "fridge_temp_c": [0, 4],
    "frozen_months": 6,
    "frozen_temp_c": -18
  },

  "allergens": ["poultry"],
  "price_tier": 2,

  "l0_domain_tags": ["protein_science", "thermal_dynamics", "maillard_caramelization"],
  "key_science": "慢速纤维（Type I）+ 快速纤维（Type II）混合结构；肌苷酸（IMP）在宰杀后12-24h达到峰值；胶原蛋白含量低，不适合长时间炖煮；超过72°C快速失水变柴",

  "external_ids": {
    "wikidata_qid": "Q1129858",
    "usda_fdc_ids": [
      {"fdcId": 171077, "description": "Chicken breast, raw, meat only", "state": "raw"},
      {"fdcId": 171116, "description": "Chicken breast, roasted", "state": "cooked_roasted"}
    ],
    "foodb_id": "FOOD00060",
    "foodon_class_id": "FOODON:03301789"
  },

  "source_books": ["professional_chef", "food_lab", "mouthfeel"],
  "confidence": "high",
  "last_updated": "2026-03-26"
}
```

### 3.2 Variety 节点

```json
{
  "variety_id": "chicken_breast_qingyuan",
  "parent_atom_id": "chicken_breast",
  "name_zh": "清远鸡胸",
  "name_en": "Qingyuan Chicken breast",
  "region": "广东清远",
  "coordinates": [23.7, 112.5],
  "importance_score": 5,

  "peak_months": [10, 11, 12, 1, 2],
  "season_reason": "秋冬走地鸡运动量大，肌红蛋白积累充分，风味更浓",

  "quality_markers": {
    "ideal_age_days": 180,
    "ideal_weight_g": 250,
    "fat_pct_delta": "+1.5% vs standard",
    "distinguishing_feature": "皮薄脂黄，肉呈微红，纹理细密"
  },

  "composition_delta": {
    "protein_pct": 24.1,
    "fat_pct": 4.2,
    "inosinic_acid_mg_per_100g": 320
  },

  "best_for": ["白切", "清蒸", "盐焗"],
  "not_ideal_for": ["长时间红焖"],
  "vs_others": "比普通肉鸡鲜味高约30%（IMP），比文昌鸡肉质更紧，比三黄鸡运动风味更显著",

  "procurement": {
    "availability": "regional_seasonal",
    "price_tier": 4,
    "min_order_notes": "清远直供或南方农产品中心"
  },

  "source_books": ["phoenix_claws_and_jade_trees"],
  "external_ids": {
    "wikidata_qid": "Q16971829"
  }
}
```

### 3.3 ProcessingState 节点

```json
{
  "state_id": "chicken_breast_frozen_thawed",
  "parent_atom_id": "chicken_breast",
  "state_type": "frozen_thawed",

  "parameter_changes": {
    "water_activity_delta": -0.01,
    "ph_delta": -0.1,
    "drip_loss_pct": 5.0,
    "texture_change": "细胞壁破损，失水率+5-8%",
    "flavor_change": "IMP 轻微降解"
  },

  "adjusted_cooking_params": {
    "note": "表面比内部解冻不均匀，低温慢煮更适合；若高温烹饪需缩短时间5-10%防过熟"
  },

  "l0_domain_tags": ["water_activity", "thermal_dynamics", "protein_science"],
  "source_books": ["food_lab", "science_good_cooking"]
}
```

---

## 4. 粒度规则 — 完整版

**规则 1：烹饪功能不可互换 = 不同原子**
- chicken_breast vs chicken_thigh：蛋白结构、脂肪含量、最优烹饪温度不同 → 不同原子
- light_soy_sauce vs dark_soy_sauce：功能完全不同（提鲜 vs 上色）→ 不同原子

**规则 2：地域/品种差异 = 同一原子的 Variety，不是新原子**
- 清远鸡胸 vs 文昌鸡胸：都是鸡胸，参数不同但功能相同 → chicken_breast 的 variety

**规则 3：物理/化学处理状态 = ProcessingState，不是新原子**
- 新鲜鸡胸 vs 冷冻解冻鸡胸 → chicken_breast 的不同 ProcessingState

**规则 4：父节点是分组，不是独立原子**
- "chicken"、"soy_sauce" 是分组父节点，用于 UI 导航和搜索
- 不参与 L2b 食谱的具体绑定

**规则 5：加工品有自己的原子**
- 鸡胸 vs 鸡高汤 vs 鸡油 — 三个独立原子（化学成分完全不同）
- 豆浆 vs 豆腐 vs 豆腐干 — 三个独立原子

**规则 6：边界案例判定标准**
问：这两个食材在食谱里能直接替换（1:1，不调整参数）吗？
- 能 → 同一原子的 variety
- 不能 → 不同原子

---

## 5. Neo4j 节点/边完整设计

### 5.1 节点标签汇总

| 标签 | 主键 | 描述 |
|------|------|------|
| `Ingredient` | `atom_id` | L2a 原子，烹饪功能粒度 |
| `Variety` | `variety_id` | 地域品种，Ingredient 的子节点 |
| `ProcessingState` | `state_id` | 物理/化学处理状态 |
| `Compound` | `compound_id` | 化学成分（FoodAtlas/FooDB 来源） |
| `UsdaFood` | `fdcId` | USDA 原始条目（导入时保留） |
| `ScientificPrinciple` | `principle_id` | L0 节点（已有） |
| `Recipe` | `recipe_id` | L2b 食谱节点（已有） |

### 5.2 关系汇总

```cypher
// L2a 内部关系
(i:Ingredient)-[:HAS_VARIETY {importance_score}]->(v:Variety)
(i:Ingredient)-[:HAS_STATE]->(ps:ProcessingState)
(i:Ingredient)-[:CHILD_OF]->(parent:Ingredient)  // chicken_breast → chicken
(i:Ingredient)-[:SUBSTITUTABLE_WITH {context, confidence, notes}]->(i2:Ingredient)
(i:Ingredient)-[:COMPLEMENTS {context}]->(i2:Ingredient)

// L2a → 外部数据
(i:Ingredient)-[:LINKED_USDA {part, state}]->(uf:UsdaFood)
(i:Ingredient)-[:CONTAINS {concentration_mg_per_100g, confidence, source}]->(c:Compound)
(v:Variety)-[:HAS_SPECIFIC_COMPOUND {delta_vs_base}]->(c:Compound)

// L2a → L0（双轨）
// 静态轨道（ETL 时写入，域级别）：
(i:Ingredient)-[:DOMAIN_OVERLAP {domains: ["protein_science"]}]->(domain_group)
// 动态轨道（运行时推断后固化）：
(i:Ingredient)-[:BRIDGES_TO {confidence, method: "vector_sim", score}]->(p:ScientificPrinciple)

// L2a → L2b
(r:Recipe)-[:USES_INGREDIENT {quantity_g, role, state}]->(i:Ingredient)
(r:Recipe)-[:USES_VARIETY {notes}]->(v:Variety)
```

### 5.3 索引策略

```cypher
CREATE INDEX ingredient_atom_id FOR (i:Ingredient) ON (i.atom_id);
CREATE INDEX ingredient_category FOR (i:Ingredient) ON (i.category);
CREATE INDEX variety_region FOR (v:Variety) ON (v.region);
CREATE INDEX variety_peak_months FOR (v:Variety) ON (v.peak_months);
CREATE VECTOR INDEX ingredient_embedding IF NOT EXISTS
  FOR (i:Ingredient) ON (i.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}};
```

---

## 6. 蒸馏 Pipeline 设计

### 6.1 原子来源（种子列表）

**来源 1（主力）**：扫描 L2b 29,085 条食谱的 `formula.ingredients[].item` 字段
- 预计唯一食材词条：8,000-12,000 条（含大量重复、模糊词）
- 去重 + 规范化后目标：~3,000 原子

**来源 2（补充）**：USDA SR Legacy 8,789 条 + Foundation Foods 扫描
**来源 3（粤菜专项）**：phoenix_claws、japanese_cooking_tsuji 等亚洲来源食谱里的特殊食材

**种子提取脚本**：扫描所有 stage5 JSONL，提取 item 字段，统计频次，按频次降序排列，频次 ≥ 2 的全部进入候选列表。

### 6.2 两轮蒸馏架构

**Round 1：快速识别（flash API）**
- 输入：食材名（中/英）
- 产出：name_zh, name_en, aliases, category, subcategory, parent_atom, l0_domain_tags, allergens, wikidata_qid（尽力而为）
- 模型：qwen3.5-flash（成本低，速度快）
- 每原子 token 消耗：~200 in / ~300 out
- 目标：3,000 原子，单批 50，并发 3-5

**Round 2：深度蒸馏（Gemini 2.5 Pro 或 Opus）**
- 输入：Round 1 结果 + 该食材在食谱库中出现的所有上下文片段（从 L2b 里检索）
- 产出：composition, flavor_profile, best_state, storage, key_science, varieties（前 3-5 个最重要的）, processing_states, quality_markers
- 模型：Gemini 2.5 Pro（推荐）或 Opus 4.6（贵但中文更好）
- 每原子 token 消耗：~800 in / ~1,200 out

**Round 3（仅针对高重要度原子，可选）**：
- 对 importance_score = 5 的约 200 个核心食材（粤菜主食材），第三轮专项深化 variety 覆盖
- 配合人工校对

### 6.3 自动化补充（ETL 脚本）

Round 2 完成后，自动化脚本处理：
1. USDA API 查询：`GET /v1/foods/search?query={name_en}` → 写入 usda_fdc_ids[]
2. Wikidata SPARQL：按 name_en 查 QID → 写入 wikidata_qid（覆盖 Round 1 的猜测值）
3. FooDB CSV 匹配：food_name 模糊匹配 → 写入 foodb_id
4. FoodAtlas TSV 匹配：建立 CONTAINS 关系边

---

## 7. 成本估算

### 7.1 蒸馏成本

| 阶段 | 模型 | 原子数 | Token/原子 | 单价 | 小计 |
|------|------|--------|-----------|------|------|
| Round 1（flash） | qwen3.5-flash | 3,000 | 200in+300out | ¥0.0003/K-token | ≈ ¥0.5 |
| Round 2（Gemini Pro） | Gemini 2.5 Pro | 3,000 | 800in+1200out | $0.00125/K-token | ≈ ¥50 |
| Round 2（Opus 替代方案） | Opus 4.6 via 代理 | 3,000 | 800in+1200out | 代理价 ~¥20/M | ≈ ¥120 |
| Round 3（可选，Gemini） | Gemini 2.5 Pro | 200 | 1500in+2000out | $0.00125/K-token | ≈ ¥5 |

**推荐方案（Gemini 2.5 Pro）总计：约 ¥60**

**备选方案（全用 Opus 代理）总计：约 ¥150**

注：以上不含 USDA / Wikidata / FooDB 匹配（均为免费 API 或免费下载）

### 7.2 时间估算

| 阶段 | 耗时 |
|------|------|
| 种子列表提取脚本 | 0.5 天 |
| Round 1 蒸馏（3,000原子，5并发） | 约 4-6 小时 |
| Round 2 蒸馏（串行，Gemini API 限速） | 约 2-3 天 |
| 自动化 ETL 匹配（USDA/Wikidata/FooDB） | 1 天 |
| Round 3 高优原子专项（可选） | 0.5 天 |
| 人工校对（price_tier + 关键 variety） | 1 天 |
| **合计** | **约 6-8 天** |

---

## 8. 风险和待 Jeff 拍板的决策点

### 决策 A — 部位粒度 [高优先]
**问题**：鸡 → 是分 `chicken_breast` / `chicken_thigh` / `chicken_wing` 等部位原子，还是保持 `chicken` 一个原子（在 ProcessingState 里区分部位）？

- **方案 A1（推荐）**：部位 = 原子。鸡有 6-8 个原子。优点：和 L2b 食谱用料严格对应，参数精确。缺点：原子数量增加约 3-4 倍（从 ~800 食材增到 ~2,500 原子）。
- **方案 A2**：整体 = 原子，部位在 ProcessingState 里区分。优点：简单，原子数少。缺点：ProcessingState 会非常臃肿，查询复杂。

**Architect 建议：A1**

---

### 决策 B — variety 覆盖策略 [高优先]
**问题**：每个原子最多收多少个 variety？有没有上限？

- **方案 B1**：每原子最多 10 个 variety（硬上限）
- **方案 B2**：按 importance_score 过滤，只收 score ≥ 3 的
- **方案 B3**：自由增长，不设上限，靠重要度评分排序

**Architect 建议：B2**（score ≥ 3 的自然上限约 5-8 个/原子，避免 rice 爆炸）

---

### 决策 C — L0 绑定时机 [中优先]
**问题**：`BRIDGES_TO` 关系什么时候写入图谱？

- **方案 C1**：蒸馏时由 LLM 直接输出 principle_ids，ETL 时写入
- **方案 C2（推荐）**：ETL 时只写 domain_tags，运行时向量搜索，积累后固化
- **方案 C3**：完全运行时，不在 ETL 时预处理任何 L0 绑定

**Architect 建议：C2**

---

### 决策 D — Gemini vs Opus for Round 2 [低优先]
**问题**：Round 2 蒸馏用 Gemini 2.5 Pro（便宜 5x）还是 Opus 4.6（中文+粤菜更好）？

- Gemini 2.5 Pro：¥50 全量，速度快，英文食材处理好
- Opus 4.6（代理）：¥120 全量，中文细节更丰富，粤菜 variety 描述更准确

**Architect 建议**：Round 1 全用 flash，Round 2 大批用 Gemini，Round 3 高优粤菜原子用 Opus

---

### 决策 E — 原子总规模估算 [中优先]
**问题**：3,000 是目标还是上限？L2b 29,085 条食谱扫描后实际会出多少原子？

**预估**：
- 食谱原料词条去重后约 8,000-12,000 条（含变体和模糊词）
- 规范化 + 合并变体后约 2,500-4,000 个原子
- 含父节点（分组）约 3,500-5,000 个节点

建议设 **3,500 为目标，5,000 为上限**。超出上限说明粒度过细，需审查。

---

### 决策 F — processing_states 深度 [低优先]
**问题**：ProcessingState 需要多详细？每个原子平均几个状态？

**最小集**（推荐先做）：
- `fresh_raw`（新鲜生）
- `frozen_thawed`（冷冻解冻）
- `cooked_standard`（标准烹熟）
- `dried`（干燥，如果适用）
- `fermented`（发酵，如果适用）

**扩展集**（第二阶段）：
- `smoked`、`cured`、`marinated_24h`、`sous_vide_65c_1h` 等

**Architect 建议**：先做最小集（3-5 个状态/原子），第二阶段按 L2b 实际使用扩展

---

### 决策 G — `flavor_profile` 维度 [低优先]
**问题**：flavor_profile 用 5 维（甜/酸/苦/咸/鲜）还是 7 维（加脂感/辛辣）还是直接对接 FT 层？

- 5 维：够用于 L3 基础推理，简单
- 7 维：加 richness（脂感）和 heat（辛辣），对粤菜重要
- 纯 FT 层：等 FT 建完再填，现在先空着

**Architect 建议**：用 6 维（基础 5 + richness），辛辣归入独立的 `pungency` 字段，FT 层建好后做对齐

---

## 9. 字段来源映射表（完整版）

| 字段 | 来源方式 | 工具/API | 质量保证 |
|------|---------|---------|---------|
| atom_id | 自动生成（snake_case） | 脚本 | 人工确认无重复 |
| name_zh / name_en | Round 1 蒸馏 | flash | 人工抽查 5% |
| aliases | Round 1 蒸馏 | flash | — |
| category / subcategory | Round 1 蒸馏 | flash | 校验词表 |
| parent_atom | Round 1 蒸馏 | flash | — |
| composition.* | Round 2 蒸馏 + USDA 校正 | Gemini + USDA API | USDA 数据优先覆盖 |
| flavor_profile.* | Round 2 蒸馏 | Gemini | 人工校对核心品类 |
| best_state | Round 2 蒸馏 | Gemini | — |
| storage.* | Round 2 蒸馏 + USDA | Gemini | — |
| allergens | Round 2 + USDA + FoodOn | 多源交叉 | 必须人工确认 |
| price_tier | 人工填写（一次性） | Jeff + 市场数据 | — |
| l0_domain_tags | Round 2 蒸馏 | Gemini | 校验 17 域词表 |
| key_science | Round 2 蒸馏 | Gemini | — |
| wikidata_qid | SPARQL 自动查询 → 人工确认 | Python sparql | 关键原子必须人工确认 |
| usda_fdc_ids | USDA API 自动匹配 | USDA search API | 置信度评分 |
| foodb_id | FooDB CSV 模糊匹配 | pandas fuzzy | — |
| foodon_class_id | FoodOn OWL 匹配 | owlready2 | — |
| varieties.* | Round 2 蒸馏 | Gemini（粤菜 Opus） | 重要度 5 人工校对 |
| processing_states.* | Round 2 蒸馏 | Gemini | — |
| source_books | L2b 反查 | 脚本 | — |
| confidence | 系统自动评分 | 脚本 | — |

---

*文档结束。待 Jeff 确认 7 个决策点后进入实施阶段。*
