---
last_updated: '2026-04-04T16:09:15.089905+00:00'
mention_count: 7.0
related:
- '[[l0-l2-linking-research.md]]'
- '[[l2a_atom_schema_v2.md]]'
sources:
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
status: active
title: Architecture  —  L0-L2 Linking Graph
---

# Architecture  —  L0-L2 Linking Graph


## Updates (2026-04-04)
- L0-L2 linking architecture uses three-hop graph path: (Ingredient)-[:CONTAINS {concentration}]->(Compound)-[:GOVERNED_BY]->(ScientificPrinciple), with parallel paths via ProcessStep
- Two parallel L0-L2 linking mechanisms: A) Pre-computed static edges from FoodAtlas+USDA (reliable, deterministic) and B) Vector similarity via Neo4j vector index on L0 embeddings (broad coverage, supports novel combinations)

## Updates (2026-04-04)
- L0-L2 三跳链接架构：(Ingredient)-[:CONTAINS]->(Compound)-[:GOVERNED_BY]->(ScientificPrinciple)，同时支持预计算静态边（FoodAtlas+USDA）和向量相似度两种机制并行
- L2a 原子粒度定义为烹饪功能粒度（非生物分类粒度，非部位粒度）；Variety 单独拆节点不内嵌 JSON 数组；processing_states 是必需字段
- L2a 的 L0 绑定策略：使用 l0_domain_tags[] + 运行时向量搜索双轨机制，不在 schema 里硬编码 principle_ids
- L2a 实体标识锚定策略：Wikidata QID 为主锚，USDA fdcId 和 FooDB food_id 挂在同一节点，实现三库联查
