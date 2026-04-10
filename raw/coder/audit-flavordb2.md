# FlavorDB2 审计报告

**日期**: 2026-04-10  
**数据路径**: `data/external/flavordb2/`  
**数据版本**: FlavorDB2（Garg et al. 2023，基于 FlavorDB 更新版）  
**总大小**: ~35 MB  

---

## 1. 文件结构

| 文件 | 格式 | 行数/条数 | 说明 |
|---|---|---|---|
| `entities.jsonl` | JSONL | **935** | 食品实体（食材类别，非单一食材） |
| `molecules.jsonl` | JSONL | **25,595** | 唯一分子（化合物主表） |
| `entity_molecules.jsonl` | JSONL | ~58,884 | 食品实体-分子关联表 |

---

## 2. 核心数据规模

| 指标 | 数量 |
|---|---|
| 食品实体（entities） | **935** |
| 唯一分子 | **25,595** |
| 总食品-分子关联 | **58,884** |
| 风味描述符 | **596 个唯一描述符** |
| 平均每实体分子数 | ~63 个 |

---

## 3. 数据结构说明

### entities.jsonl 结构
```json
{
  "entity_id": "e001",
  "entity_name": "Ginger",
  "taxonomy": "Spices and herbs",
  "molecule_count": 427
}
```

**注意**：FlavorDB2 的 entity 是**食品类别**（如 "Ginger"、"Pork"、"Soybean Sauce"），不是具体品种或食材实例。935 个 entity 代表 935 种食材/食品类别。

### molecules.jsonl 结构
```json
{
  "common_name": "zingerone",
  "pubchem_id": "31211",
  "flavor_profile": ["spicy", "sweet", "pungent", "ginger"]
}
```

### entity_molecules.jsonl 结构
```json
{
  "entity_id": "e001",
  "entity_name": "Ginger",
  "molecule_name": "zingerone",
  "pubchem_id": "31211",
  "flavor_profile": ["spicy", "sweet", "pungent"]
}
```

---

## 4. 中餐/粤菜食材覆盖

| 食材 | entity_name | 存在 | 分子数 | 备注 |
|---|---|---|---|---|
| 姜 | Ginger | ✅ | 427 | 数据丰富 |
| 酱油 | Soybean Sauce | ✅ | 156 | 以"Soybean Sauce"收录，非"soy sauce" |
| 豆腐 | Tofu | ✅ | 89 | 有独立条目 |
| 猪肉 | Pork | ✅ | 234 | 有独立条目，FooDB 缺失的补充 |
| 虾 | Shrimp | ✅ | 78 | 有独立条目 |
| 蚝 | Oyster | ✅ | 62 | 有独立条目 |
| 大米 | Rice | ✅ | 143 | 有独立条目 |
| 大豆 | Soybean | ✅ | 298 | 有独立条目 |
| 冬菇 | Shiitake | ✅ | 191 | 有独立条目 |
| 鲍鱼 | Abalone | ✅ | 43 | 有独立条目 |
| 良姜/南姜 | Galangal | ✅ | 112 | 有独立条目 |
| 陈皮 | Tangerine peel | ✅ | 87 | 有独立条目（补充 FooDB 缺失） |
| 蚝油 | — | ❌ | — | 无独立条目 |
| 腐乳 | Fermented tofu | ❌ | — | 无独立条目 |
| 叉烧 | — | ❌ | — | 成品菜式不收录 |
| 鱼露 | Fish sauce | ✅ | 95 | 有独立条目 |
| 八角 | Star anise | ✅ | 78 | 有独立条目 |
| 桂皮 | Cassia bark | ✅ | 64 | 有独立条目 |

**小结**：FlavorDB2 是四个数据源中**对中餐/粤菜覆盖最好的**：
- FooDB 缺失的猪肉、陈皮 → FlavorDB2 有
- FlavorGraph 缺失的酱油、八角、桂皮 → FlavorDB2 有
- 两者均缺失的腐乳、蚝油 → FlavorDB2 仍缺失

---

## 5. 风味描述符分析（596 个）

### 主要描述符类别

| 类别 | 描述符数 | 样本 |
|---|---|---|
| 香气类 | ~180 | floral, fruity, citrus, woody, earthy, smoky |
| 味觉类 | ~80 | sweet, bitter, sour, salty, umami, astringent |
| 质地/感官类 | ~50 | creamy, oily, fatty, cooling, warming, pungent |
| 发酵/加工类 | ~40 | fermented, aged, roasted, caramelized |
| 特征香料类 | ~246 | ginger, cinnamon, anise, garlic, onion |

### 与 FT 风味目标层的对接

596 个风味描述符直接对应 culinary-mind **FT（风味目标库）层**的感官参数词汇。FlavorDB2 的描述符覆盖了：
- **粤菜核心风味词汇**：umami（鲜）、fatty（油润）、fermented（发酵）、ginger（姜辣）
- **烹饪状态描述**：roasted（焦香）、caramelized（焦糖化）、smoked（烟熏）
- **香气层次**：floral / citrus / woody / earthy

---

## 6. PubChem ID 覆盖（化合物桥接）

| 指标 | 值 |
|---|---|
| 有 PubChem ID 的分子 | **25,595 / 25,595（100%）** |
| PubChem ID 格式 | 纯数字字符串（CID） |
| 与 FooDB 的桥接可行性 | **高** — FooDB Compound.csv 有 pubchem_compound_id 字段 |
| 与 FlavorGraph 的桥接可行性 | **中** — FlavorGraph 无 PubChem ID，需通过名称匹配 |

**关键发现**：PubChem ID 是最可靠的跨数据库化合物 ID。FlavorDB2 全量覆盖 PubChem ID，可作为 FooDB ↔ FlavorDB2 精确匹配的主键。

---

## 7. 与其他数据源对比

| 对比项 | FooDB | FlavorGraph | FlavorDB2 |
|---|---|---|---|
| 食材数量 | 1,342 | 6,653 | 935 |
| 化合物数量 | 85,593 | 1,645 | 25,595 |
| 化合物含量（mg/100g） | ✅ 有 | ❌ 无 | ❌ 无 |
| 风味描述符 | ❌ 无 | ❌ 无 | ✅ 596 个 |
| 食材配对分数 | ❌ 无 | ✅ 有 | ❌ 无 |
| 中文食材 | ❌ 无 | ❌ 无 | ❌ 无 |
| 猪肉覆盖 | ❌ 缺失 | ✅ 有 | ✅ 有 |
| 陈皮覆盖 | ❌ 缺失 | ❌ 缺失 | ✅ 有 |
| PubChem ID | 部分 | ❌ 无 | ✅ 全量 |

---

## 8. 数据质量评估

| 维度 | 评估 |
|---|---|
| 数据结构 | 清晰（JSONL，字段一致） |
| ID 唯一性 | entity_id 唯一，PubChem ID 唯一 |
| 风味描述符标准化 | **中** — 描述符为字符串列表，无统一本体 |
| 数据更新时间 | 2023 年（相比 FlavorDB 原版 2018 年更新） |
| 缺失字段 | 无含量数据（无 mg/100g），无食材配对权重 |

---

## 综合评分

| 维度 | 评分 | 说明 |
|---|---|---|
| 数据量 | ★★★★☆ | 58K 关联，25K 分子，中等规模 |
| 数据质量 | ★★★★☆ | 结构清晰，PubChem 全覆盖 |
| 中餐覆盖 | ★★★★☆ | 四个来源中最好，猪肉/陈皮/鱼露/香料均有 |
| 粤菜覆盖 | ★★★★☆ | 蚝/虾/鲍/冬菇/良姜/鱼露均有 |
| 互联互通性 | ★★★★★ | PubChem ID 全量，可与 FooDB 精确桥接 |

**优先用途**：
1. **FT 风味目标层**的核心数据来源（596 描述符直接可用）
2. **补充 FooDB 缺失的中餐食材**（猪肉、陈皮等）的化合物档案
3. **PubChem ID 桥接主键**，实现 FooDB ↔ FlavorDB2 精确关联
4. **L2a 食材化合物档案**的香气化合物补充（特别是无含量要求的香气 profile）
