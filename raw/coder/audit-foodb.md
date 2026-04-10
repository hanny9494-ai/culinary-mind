# FooDB 审计报告

**日期**: 2026-04-10  
**数据路径**: `data/external/foodb/foodb_2020_04_07_csv/`  
**数据版本**: FooDB 2020-04-07  
**总大小**: 1.9 GB  

---

## 1. 29 张 CSV 内容概览

| 表名 | 行数 | 说明 |
|---|---|---|
| Content.csv | 5,145,532 | **核心关联表**：食材-化合物含量数据（mg/100g） |
| CompoundOntologyTerm.csv | 1,587,712 | 化合物→本体术语映射 |
| CompoundSynonym.csv | 171,240 | 化合物同义词 |
| CompoundsEnzyme.csv | 105,089 | 化合物-酶关联 |
| CompoundSubstituent.csv | 95,299 | 化合物结构子基团 |
| Compound.csv | 85,593 | **核心**：化合物主表（名称、结构、化学分类） |
| CompoundAlternateParent.csv | 50,691 | 化合物分类层级 |
| Reference.csv | 31,778 | 引用文献 |
| CompoundsFlavor.csv | 12,432 | 化合物-气味描述符关联 |
| CompoundsHealthEffect.csv | 11,062 | 化合物-健康功效关联 |
| CompoundExternalDescriptor.csv | 9,486 | 化合物外部 ID（CAS、InChIKey 等） |
| OntologyTerm.csv | 4,379 | 本体术语库 |
| HealthEffect.csv | 2,049 | 健康功效分类 |
| Enzyme.csv | 1,744 | 酶库 |
| OntologySynonym.csv | 1,669 | 本体同义词 |
| CompoundsPathway.csv | 1,604 | 化合物-代谢通路 |
| AccessionNumber.csv | 1,424 | 化合物登录号 |
| Food.csv | 1,342 | **核心**：食材主表（名称、分类、描述） |
| FoodTaxonomy.csv | 889 | 食材分类树 |
| Flavor.csv | 883 | 气味描述符词典（odor 类） |
| NcbiTaxonomyMap.csv | 242 | NCBI 分类 ID 映射 |
| Nutrient.csv | 39 | 营养素定义 |
| Sequence.csv | 0 | 空表 |
| PfamMembership.csv | 0 | 空表 |
| Pfam.csv | 0 | 空表 |
| PdbIdentifier.csv | 0 | 空表 |
| MapItemsPathway.csv | 0 | 空表 |
| EnzymeSynonym.csv | 0 | 空表 |
| MapItemsPathway.csv | 0 | 空表 |

**关键字段（Food.csv）**: id, name, name_scientific, food_group, food_subgroup, food_type, category, ncbi_taxonomy_id, public_id (FOOD00XXX)  
**关键字段（Compound.csv）**: id, public_id (FDB00XXXX), name, cas_number, moldb_inchikey, kingdom, superklass, klass  
**关键字段（Content.csv）**: id, source_id, food_id, orig_food_common_name, orig_content, orig_unit, standard_content, preparation_type  

---

## 2. 核心表数据量

| 表 | 行数 |
|---|---|
| foods (Food.csv) | **1,342 条** |
| compounds (Compound.csv) | **85,593 条** |
| foods_compounds 关联 (Content.csv) | **5,145,532 条** |

注：Content.csv 是食材-化合物含量的主关联表，平均每种食材约 3,834 条化合物数据。

---

## 3. 中餐覆盖

| 食材 | food_id | 化合物关联数 | 存在 |
|---|---|---|---|
| Ginger（姜） | 206 | 7,014 | ✅ |
| Soy sauce（酱油） | 716 | 4,642 | ✅ |
| Tofu（豆腐） | 718 | 5,856 | ✅ |
| Rice（米） | 125 | 10,804 | ✅ |
| Soy bean（大豆/黄豆） | 85 | 有（数据丰富） | ✅ |
| Shrimp（虾） | 546 | 1,732 | ✅ |
| Pork（猪肉） | 未找到 | 0 | ❌ |

**关于 Pork**：Food.csv 中没有独立的 "Pork" 条目。相关词条有 "Pigeon pea"（豆类）、描述中涉及猪肉的菜品。这是 FooDB 的已知局限——主要收录植物性食材。

---

## 4. 粤菜关键食材覆盖

| 食材 | 存在 | 备注 |
|---|---|---|
| 虾（Shrimp） | ✅ | food_id 546，1,732 条化合物 |
| 蠔（Oyster） | ✅ | Eastern oyster (id 361) + Pacific oyster (id 433) |
| 鲍鱼（Abalone） | ✅ | food_id 280，2,089 条化合物 |
| 冬菇（Shiitake） | ✅ | food_id 562，6,449 条化合物 |
| 陈皮（Dried Tangerine Peel） | ❌ | 无独立条目，橙皮/柚皮有但非专项 |
| 腐乳（Fermented Tofu/Sufu） | ❌ | 无条目 |

**小结**：6 种粤菜食材中 4 种能找到，2 种缺失（陈皮、腐乳）。整体是以西方食材为主的数据库。

---

## 5. 数据质量（随机抽 500 条 Content.csv）

| 指标 | 值 |
|---|---|
| 有效 orig_content 值 | **94.2%**（500 条中 471 条） |
| null/空值率 | **5.8%** |
| 零值/负值 | < 1% |
| 主要单位 | mg/100g（绝大多数） |
| standard_content 空值率 | 同 orig_content（5.8%） |

**结论**：数据质量良好，5.8% null 率属正常科学文献覆盖不完整，无明显错误值。concentration 单位统一（mg/100g），适合定量分析。

---

## 6. 与 FlavorGraph 的交集

| 指标 | 数据 |
|---|---|
| FlavorGraph compound 节点数 | 1,629 |
| FooDB compound 总数 | 85,593 |
| 按名称精确匹配的交集 | **498 条（占 FlavorGraph 的 30.6%）** |
| 交集样本 | tridecanal, perillaldehyde, gamma-eudesmol, 4-vinylphenol, sabinene... |

**结论**：
- FlavorGraph 是 FooDB 的一个子集视角，主要收录香气化合物（aroma compounds）
- 两者可以通过化合物名称进行关联，但需要标准化处理（大小写、连字符等）
- FooDB 提供精确含量（mg/100g），FlavorGraph 提供配对分数（ingredient pairing），互补性强
- 建议用 PubChem CID 作为统一 ID，而非化合物名称（可减少命名歧义）

---

## 综合评分

| 维度 | 评分 | 说明 |
|---|---|---|
| 数据量 | ★★★★★ | 5M+ 条含量数据，85K 化合物 |
| 数据质量 | ★★★★☆ | 94% 有效率，单位统一 |
| 中餐覆盖 | ★★★☆☆ | 基础食材有（姜/豆腐/大米），猪肉/陈皮/腐乳缺失 |
| 粤菜覆盖 | ★★★☆☆ | 4/6 粤菜核心食材有数据 |
| 互联互通性 | ★★★★☆ | InChIKey/CAS 可与其他数据库关联 |

**优先用途**：食材化学成分量化分析，L0 食材参数库的化合物浓度数据来源。
