## 2026-04-04
- [KEEP_SEPARATE] Project identity: Culinary Engine is a cooking science reasoning engine with cor
- [KEEP_SEPARATE] L0 layer (科学原理图谱): Scientific principles graph, causal chains + parameter bounda
- [KEEP_SEPARATE] L1 layer (设备实践参数层): Equipment practice parameters — how to adjust the same princ
- [KEEP_SEPARATE] L2a layer (天然食材参数库): Natural ingredient parameter library — variety/cut/season/o
- [KEEP_SEPARATE] L2b layer (食谱校准库): Recipe calibration library — validated parameter combinations
- [KEEP_SEPARATE] L2c layer (商业食材数据库): Commercial ingredient database — brand/model → component br
- [KEEP_SEPARATE] FT layer (风味目标库): Flavor target library — aesthetic terms → quantifiable sensory
- [KEEP_SEPARATE] L3 layer (推理引擎): Reasoning engine — pre-computation + real-time inference. Statu
- [KEEP_SEPARATE] L6 layer (翻译层): Translation layer — Cantonese cuisine language ↔ system language
- [KEEP_SEPARATE] 17 scientific domains in L0: protein_science, carbohydrate, lipid_science, ferme
- [KEEP_SEPARATE] CC Lead role: Command center (mother conversation). Responsibilities: receive Je
- [KEEP_SEPARATE] CC Lead constraints: Does NOT write code (coder does), does NOT run pipeline scr
- [KEEP_SEPARATE] Agent: pipeline-supervisor — Type: manager. Responsibility: overall pipeline man
- [KEEP_SEPARATE] Agent: pipeline-runner — Type: executor. Responsibility: runs Stage1-5 full pipe
- [KEEP_SEPARATE] Agent: architect — Type: architecture. Responsibility: evaluates how new data so
- ...+662 more

## 2026-04-04
- [UPDATE] 所有脚本必须设置 trust_env=False 或清除代理环境变量，因为本机 ~/.zshrc 配置了 SOCKS5 代理 127.0.0.1:7890 会拦
- [UPDATE] API 路由规则：qwen* 模型走 DashScope，claude* 模型走灵雅代理（L0_API_ENDPOINT+L0_API_KEY），本地模型走 O
- [UPDATE] L2a Gemini 蒸馏进度 76%，当前阻塞原因是 Gemini API 账户需要充值，无 pipeline 在运行
- [UPDATE] L0 数据规模：QC 通过 51,924 条（46 本书），raw 提取 74,391 条，Stage3 骨架 690 条，L0 总计 52,614 条
- [UPDATE] Pipeline 整体状态（2026-04-04）：总书 69 本，Stage4 完成 46 本，Stage1 完成 61 本，OCR 完成 22 本，Stag
- [UPDATE] 18 本书就绪可进入 Stage4 队列，包括 Alinea、Bouchon、French Laundry、Eleven Madison Park 等顶级餐厅食
- [UPDATE] L0-L2 三跳链接架构：(Ingredient)-[:CONTAINS]->(Compound)-[:GOVERNED_BY]->(ScientificPri
- [UPDATE] FoodAtlas（230K 食物-化合物关系，MIT 许可）是关键桥接层：提供 Ingredient→Compound 链接，配合 L0 的 Compound
- [UPDATE] 目前没有任何现有系统实现自动的菜谱步骤→科学原理链接（recipe-step-to-scientific-principle），这是 culinary-engi
- [UPDATE] L2a 原子粒度定义为烹饪功能粒度（非生物分类粒度，非部位粒度）；Variety 单独拆节点不内嵌 JSON 数组；processing_states 是必需字
- [UPDATE] L2a 的 L0 绑定策略：使用 l0_domain_tags[] + 运行时向量搜索双轨机制，不在 schema 里硬编码 principle_ids
- [UPDATE] L2a 实体标识锚定策略：Wikidata QID 为主锚，USDA fdcId 和 FooDB food_id 挂在同一节点，实现三库联查
- [UPDATE] L2a 全量 3,000 原子蒸馏成本估算：两轮，约 ¥800-1,200，耗时 6-8 天
- [UPDATE] Wikidata SPARQL 端点（CC0）可用于 L6 翻译层和通用实体链接器（QID 桥接 FoodOn、USDA、FooDB）
- [UPDATE] FlavorGraph（Sony AI，6,653 种食材，1,525 种风味化合物）对 FT（风味）层价值高
- ...+1 more

## 2026-04-04
- [KEEP_SEPARATE] L0 knowledge base has 52,614 total entries: 51,924 QC-passed entries from 46 boo
- [MERGE] Pipeline stages: Stage1 (chunking/chunks_smart), Stage4 (L0 extraction/QC), Stag
- [MERGE] 18 books are queued and ready for Stage4 processing including major titles: Alin
- [KEEP_SEPARATE] L2a pipeline is actively producing output: canonical_map_v2.json (9.7M), normali
- [MERGE] L2 Gemini distillation (L2a) was at 76% completion and blocked on account top-up
- [KEEP_SEPARATE] L0-L2 linking architecture uses three-hop graph path: (Ingredient)-[:CONTAINS {c
- [MERGE] Two parallel L0-L2 linking mechanisms: A) Pre-computed static edges from FoodAtl
- [KEEP_SEPARATE] FoodAtlas (gjorgjinac/foodatlas) selected as CRITICAL bridge layer: 230K food-co
- [MERGE] USDA FoodData Central rated CRITICAL for L2a: 380K+ foods, free API, public doma
- [MERGE] Wikidata SPARQL endpoint (CC0) rated CRITICAL for L6 translation layer: QIDs ser
- [MERGE] FlavorGraph (Sony AI): 6,653 ingredients, 1,525 flavor compounds — rated HIGH va
- [MERGE] FoodOn Ontology (30K classes, OWL, CC BY 3.0) rated HIGH for L2a ingredient taxo
- [KEEP_SEPARATE] Literature gap identified: no existing system performs automatic recipe-step-to-
- [MERGE] Project growth from 2026-03-25 to 2026-04-01: L0 QC-passed entries grew from 34,
- [KEEP_SEPARATE] STATUS.md is maintained exclusively by the mother/lead conversation; agents are 
- ...+2 more

