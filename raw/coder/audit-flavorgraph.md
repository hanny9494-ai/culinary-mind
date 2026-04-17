# FlavorGraph 审计报告

**日期**: 2026-04-10  
**数据路径**: `data/external/flavorgraph/`  
**数据版本**: FlavorGraph (Teng et al. 2021)  
**总大小**: ~140 MB  

---

## 1. 文件结构

| 文件 | 大小 | 说明 |
|---|---|---|
| `nodes_191120.csv` | ~2.3 MB | 所有节点（食材 + 化合物） |
| `edges_191120.csv` | ~12 MB | 所有边（关联关系） |
| `kitchenette_embeddings.pkl` | ~4.1 MB | 食材嵌入向量（300-dim） |

---

## 2. 节点统计

| 节点类型 | 数量 | 说明 |
|---|---|---|
| ingredient | **6,653** | 食材节点（可配对） |
| compound | **1,645** | 香气化合物节点 |
| **合计** | **8,298** | 总节点数 |

**关键字段（nodes）**: node_id, name, node_type (ingredient/compound)

---

## 3. 边统计

| 边类型 | 数量 | 说明 |
|---|---|---|
| ingredient–ingredient | **111,355** | 食材配对关系（有 pairing score） |
| ingredient–compound（flavordb） | **35,440** | 食材→香气化合物（来自 FlavorDB） |
| ingredient–compound（drinksflavors） | **384** | 食材→香气化合物（饮品来源） |
| **合计** | **147,179** | 总边数 |

**关键字段（edges）**: source_node, target_node, edge_type, weight/score

---

## 4. 食材嵌入（kitchenette_embeddings.pkl）

| 指标 | 值 |
|---|---|
| 嵌入食材数量 | **3,567** |
| 向量维度 | **300-dim**（numpy float32） |
| 覆盖率 | 3,567 / 6,653 ≈ **53.6%** 的食材有嵌入 |
| 嵌入方法 | Kitchenette word2vec（语义烹饪向量） |

**注意**：约 46.4% 的食材节点无嵌入向量，主要是生僻食材或非英语词条。

---

## 5. 中餐/粤菜核心食材覆盖

| 食材 | 英文搜索词 | 存在 | 节点名称 | 备注 |
|---|---|---|---|---|
| 姜 | ginger | ✅ | ginger, crystallized ginger, candied ginger | 多个 ginger 变体 |
| 酱油 | soy sauce | ❌ | 未找到 | "Soy sauce" 不在 ingredient 节点中 |
| 豆腐 | tofu | ✅ | tofu, baked tofu, firm tofu, extra-firm tofu | 多个豆腐形态 |
| 猪肉 | pork | ✅ | pork, pork belly, pork shoulder, barbecued pork | 完整覆盖 |
| 虾 | shrimp | ✅ | shrimp, baby shrimp, bay shrimp, canned shrimp | 多种形态 |
| 大豆 | soybean | ✅ | soybean | 单节点 |
| 大米 | rice | ✅ | rice, brown rice, white rice | 多个变体 |
| 鲍鱼 | abalone | ✅ | abalone | 单节点 |
| 冬菇 | shiitake | ✅ | shiitake | 单节点 |
| 蚝 | oyster | ✅ | oyster | 单节点 |
| 良姜/南姜 | galangal | ✅ | galangal | 单节点 |
| 蚝油 | oyster sauce | ❌ | 未找到 | 酱料类普遍缺失 |
| 叉烧 | char siu | ❌ | 未找到 | 成品菜式不收录 |
| 八角 | star anise | ❌ | 未找到 | 香料类缺失较多 |
| 桂皮 | cassia bark | ❌ | 未找到 | — |
| 陈皮 | dried tangerine peel | ❌ | 未找到 | — |

**小结**：核心食材（蛋白质、蔬菜类）覆盖较好，**酱料/腌制品/香料缺失明显**（酱油、蚝油、陈皮、八角等粤菜常用调料均无）。

---

## 6. 与 FooDB 的化合物交集

| 指标 | 数据 |
|---|---|
| FlavorGraph compound 节点数 | **1,645** |
| FooDB compound 总数 | 85,593 |
| 按名称精确匹配的交集 | **498 条（占 FlavorGraph 的 30.3%）** |
| 交集样本 | tridecanal, perillaldehyde, gamma-eudesmol, 4-vinylphenol, sabinene |

**分析**：FlavorGraph 专注于香气化合物子集（约 1,600 种），是 FooDB 85K 化合物中的高价值子集。FooDB 覆盖更广但含大量非香气化合物。

---

## 7. 数据质量评估

| 维度 | 评估 |
|---|---|
| 食材名称语言 | 纯英文（无多语言支持） |
| 化合物名称 | IUPAC 标准名（与 FooDB/FlavorDB2 可对齐） |
| 配对权重 | 有 weight 字段，但部分边无权重（需检验） |
| 嵌入覆盖率 | 53.6%，中等覆盖 |
| 数据更新时间 | 2019-11-20（文件名 191120），较旧 |

---

## 8. 与 culinary-mind 架构的对接价值

| 用途 | 价值 | 接入层 |
|---|---|---|
| 食材配对分数（ingredient pairing） | **高** — ingredient-ingredient edges 直接提供配对权重 | L2a / FT 层 |
| 香气化合物关联 | **高** — 1,645 香气化合物 + 食材关联，FT 层核心 | FT 层 |
| 食材语义嵌入 | **中** — 300-dim Kitchenette，可用于相似食材检索 | L2a 检索 |
| 替换建议支撑 | **高** — 配对分数可为 L3 推理引擎的食材替换建议提供依据 | L3 层 |

**关键局限**：
1. 酱料/香料类食材缺失，中餐调味体系覆盖不完整
2. 嵌入仅覆盖 53.6% 食材
3. 数据较旧（2019），未含近年新增食材

---

## 综合评分

| 维度 | 评分 | 说明 |
|---|---|---|
| 数据量 | ★★★★☆ | 147K 边，8K 节点，够用 |
| 数据质量 | ★★★★☆ | 结构清晰，权重有意义 |
| 中餐覆盖 | ★★★☆☆ | 基础食材有，酱料香料缺 |
| 粤菜覆盖 | ★★★☆☆ | 6种粤菜食材4种有，调味料缺 |
| 互联互通性 | ★★★★☆ | 化合物名称可与 FooDB/FlavorDB2 对齐 |

**优先用途**：食材配对分数、香气化合物关联网络、FT 风味目标层构建的基础数据来源。
