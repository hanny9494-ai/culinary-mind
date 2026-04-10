# FoodOn 审计报告

**日期**: 2026-04-10  
**数据路径**: `data/external/foodon/`  
**数据版本**: FoodOn OWL 本体（2023 年版）  
**文件大小**: ~38.6 MB（foodon.owl，OWL/RDF XML 格式）  

---

## 1. 文件概览

| 文件 | 格式 | 大小 | 说明 |
|---|---|---|---|
| `foodon.owl` | OWL/RDF XML | 38.6 MB | 完整食品本体（类层级 + 关系 + 标签） |

**本体格式**：OWL 2 + RDF/XML，可用 Protégé 或 owlready2/rdflib 解析。  
**命名空间前缀**：`FOODON_` (食品类), `RO_` (关系类), `NCBITaxon_`, `UBERON_`（外部引用）

---

## 2. 本体规模统计

| 指标 | 数量 |
|---|---|
| 总 OWL 类数 | **39,682** |
| subClassOf 关系数 | **55,547** |
| 唯一 rdf:label 语言覆盖 | 英文为主，含部分中文标注 |
| 中文标注类数 | **624 条**（多为化合物浓度标签，非食材本体类） |
| 最大类层级深度 | ~8-10 层（食品→大类→中类→具体食品→加工方式） |

---

## 3. 关键本体类层级（部分）

```
FOODON:00001002 food material
├── FOODON:00001041 plant food product
│   ├── FOODON:00001008 vegetable food product
│   ├── FOODON:00003042 cereal grain food product
│   └── FOODON:00003947 legume food product
├── FOODON:00001100 animal food product
│   ├── FOODON:00001092 meat food product
│   ├── FOODON:00001012 seafood food product
│   └── FOODON:00001108 dairy food product
└── FOODON:00001081 fermented food product
    ├── FOODON:00003596 fermented soybean product
    └── ...
```

---

## 4. 加工处理词汇覆盖（用于 L0 对接）

| 处理方式 | 匹配类数 | 样本类 |
|---|---|---|
| fermented（发酵） | **1,291** | fermented soybean paste, kimchi, miso |
| dried（干燥） | **1,100** | dried mushroom, dried fruit, sun-dried tomato |
| roasted/roast（烤制） | **590** | roasted chicken, roasted peanut |
| smoked（烟熏） | **325** | smoked salmon, smoked pork |
| pickled（腌制） | **88** | pickled ginger, pickled vegetable |
| braised（卤/焖） | ~40 | braised pork belly |
| steamed（蒸） | ~60 | steamed bun, steamed fish |

**结论**：加工处理语义词汇丰富，**对 L0 的 thermal_dynamics / fermentation 域有直接对接价值**。

---

## 5. 中餐/粤菜食材覆盖

| 食材/菜式 | FOODON ID | 存在 | 备注 |
|---|---|---|---|
| 米粉/河粉 | FOODON_00005556 | ✅ | rice noodle |
| 蚝油 | FOODON_03317655 | ✅ | oyster sauce |
| 酱油 | — | ✅ | soy sauce（有类） |
| 豆腐 | — | ✅ | tofu（有类） |
| 姜 | — | ✅ | ginger（作为植物原料） |
| 云吞/馄饨 | — | ✅ | wonton（有类） |
| 饺子 | — | ✅ | dumpling（有类） |
| 叉烧 | — | ❌ | char siu 未找到 |
| 粥/congee | — | ❌ | congee 未找到 |
| 点心 | — | ❌ | dim sum 未找到 |
| 陈皮 | — | ❌ | dried tangerine peel 未找到 |
| 腐乳 | — | ✅ | fermented tofu（有类，FOODON fermented soybean 体系下） |
| 鲍鱼 | — | ✅ | abalone（seafood 体系下） |
| 冬菇 | — | ✅ | shiitake（fungi food product） |

**中餐食材覆盖评估**：基础食材（豆制品、海鲜、菌菇）有系统性收录，但**粤菜特色菜式、成品料理（叉烧、粥、点心）几乎缺失**，FoodOn 定位是食品原料本体，不是菜式本体。

---

## 6. 中文标注分析

| 指标 | 值 |
|---|---|
| `xml:lang="zh"` 的 rdfs:label 数 | **624** |
| 主要内容 | 化合物含量标注（如"干重 100g 中 X mg"类标签），非食材类本体 |
| 真正食材类中文名 | 极少（< 20 条），多为英文 |

**结论**：FoodOn 中文支持**基本不存在**，作为中餐/粤菜语言界面无法直接用，需要 L6 翻译层映射。

---

## 7. 与 culinary-mind 架构对接价值

| 用途 | 价值 | 接入层 |
|---|---|---|
| 食材规范化 ID（canonical food ID） | **高** — FOODON_XXXXXXX 可作为食材标准 ID | L2a 食材参数库 |
| 食品类层级（taxonomy） | **高** — 39K 类提供完整食品分类树，可用于 L2a 食材归类 | L2a |
| 加工处理语义（processing ontology） | **高** — 发酵/烤制/腌制等加工类型与 L0 域直接对应 | L0 域标记 |
| 跨数据库 ID 桥接 | **高** — FoodOn 收录 NCBITaxon/CHEBI 等外部 ID，可桥接多数据库 | 数据集成 |
| 中餐/粤菜菜式覆盖 | **低** — 菜式类（点心/叉烧/粥）几乎无 | L6 翻译层 |

---

## 8. 数据质量评估

| 维度 | 评估 |
|---|---|
| 本体结构 | 规范（OWL 2，带 reasoning support） |
| 维护状态 | 活跃（GitHub: FoodOn 持续更新） |
| 语言覆盖 | 英文为主，中文极少 |
| ID 稳定性 | FOODON_ 前缀 ID 稳定，可作为长期参考 |
| 与 FooDB 的关联 | FooDB 部分食材有 FoodOn ID，可交叉验证 |

---

## 综合评分

| 维度 | 评分 | 说明 |
|---|---|---|
| 数据量 | ★★★★★ | 39K 类，最大规模食品本体 |
| 数据质量 | ★★★★★ | OWL 规范，维护活跃 |
| 中餐覆盖 | ★★☆☆☆ | 基础食材有，菜式无，中文标注极少 |
| 粤菜覆盖 | ★★☆☆☆ | 同上 |
| 互联互通性 | ★★★★★ | NCBITaxon/CHEBI/FooDB 可桥接 |

**优先用途**：食材标准 ID 参照（L2a）、加工处理分类（与 L0 域对齐）、跨数据库 ID 桥接。不适合直接做中文用户界面，需要 L6 翻译层。
