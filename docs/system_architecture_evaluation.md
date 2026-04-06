# 用户端系统架构评估报告

> 版本：v1.0
> 日期：2026-03-26
> 作者：architect agent
> 范围：数据导入层、推理引擎(L3)、用户界面、API层

---

## 执行摘要

**推荐方案：方案C（混合）**

- 数据导入层：Python 脚本自建（现成轮子不适配 JSONL + 自定义 schema）
- 推理引擎：`neo4j-graphrag-python` + LangGraph 自建 agent 图（轮子覆盖核心，业务逻辑自建）
- API层：FastAPI 自建（LangServe 已停止新功能，LangGraph Platform 有云依赖风险）
- 用户界面：**Chainlit**（对话式 AI 前端，原生支持 LangGraph streaming，中文无障碍）

---

## 1. 数据导入层

### 背景数据量

| 数据集 | 条数 | 格式 |
|--------|------|------|
| L0 科学原理 | 44,692 条（目标 51,924） | JSONL |
| L2b 食谱 | 29,085 条 | JSONL |
| 外部数据（FoodAtlas/FooDB/FoodKG等） | 数十万—数千万 | CSV / TSV / JSON |

### 方案对比

#### 方案A：完全自建（Python ETL 脚本）

**技术栈**：Python + `neo4j` driver + `pandas` / `ijson`（流式读 JSONL）

**工作量**：3-5 天

- L0/L2b 导入脚本：2 天
- 外部数据 ETL（FoodAtlas/FooDB/FoodKG）：1-2 天
- Schema 设计 + 索引创建：1 天

**优势**：
- 完全控制 schema，L0/L2b 字段直接映射为 Neo4j 节点属性和关系
- 可分批导入，支持断点续传
- 不依赖任何额外工具
- JSONL 格式可用 `ijson` 流式处理，内存友好

**劣势**：
- 需要手写节点/关系定义
- 关系建立（L0 ↔ Recipe 映射边）需要两次扫描

#### 方案B：现成轮子

主要候选：
1. **`neo4j-admin database import`（内置工具）**：官方批量导入工具，速度极快（60亿节点/2-3小时），但**仅支持 CSV 格式**，JSONL 需先转 CSV，且要求数据库离线状态。
2. **APOC `apoc.load.jsonl`**：支持 JSONL 直接加载，但通过 Cypher 调用，速度比 admin import 慢 5-10 倍，适合增量小批次更新。
3. **Neo4j LLM Graph Builder（Labs）**：从非结构化文本自动建图，不适用——我们的数据已结构化。
4. **py2neo / neomodel**：ORM 层，增加复杂度，不必要。

**结论**：现成轮子不直接支持我们的 JSONL + 自定义 schema 场景，`neo4j-admin` 需要 CSV 转换层，反而增加步骤。

#### 方案C：混合（推荐）

**分两阶段**：

**阶段1 — 初始全量导入（`neo4j-admin` + 转换脚本）**：
- 写一个 Python 转换脚本：JSONL → CSV（nodes 文件 + relationships 文件）
- 用 `neo4j-admin database import full` 批量导入
- 预计速度：80,000 条在 Mac Studio 上 < 2 分钟
- 工作量：2 天

**阶段2 — 增量更新（Python driver + Cypher `MERGE`）**：
- 后续新书、外部数据用 Python 批量 `MERGE`，每次数千条
- APOC `apoc.load.jsonl` 作为辅助工具，调试用

**Schema 设计要点**：

```cypher
// L0 节点
(:Principle {
  id: String,
  domain: String,       // 17域之一
  proposition: String,
  confidence: String,   // high/medium/inferred
  source_book: String,
  causal_chain: Boolean
})

// L2b 食谱节点
(:Recipe {
  id: String,
  name: String,
  name_zh: String,
  book: String,
  cuisine: String
})

// 食谱 ↔ 原理 关系
(:Recipe)-[:GOVERNED_BY {
  confidence: String,
  decision_point: String
}]->(:Principle)

// 食材节点
(:Ingredient {
  name: String,
  name_zh: String,
  foodon_id: String    // FoodOn 对齐
})

// 域节点（17个，预建）
(:Domain {name: String})
(:Principle)-[:BELONGS_TO]->(:Domain)
```

**推荐方案C工作量**：2-3 天

---

## 2. 推理引擎（L3）

### 方案对比

#### 方案A：完全自建（LangGraph + Neo4j Python Driver）

**技术栈**：LangGraph StateGraph + neo4j driver + 自写 Cypher 查询

**工作量**：2-3 周

**优势**：完全控制查询逻辑，无额外依赖
**劣势**：需要自写向量检索、混合搜索、Cypher 生成等所有功能

#### 方案B：现成轮子（`neo4j-graphrag-python` 官方包）

**GitHub**：https://github.com/neo4j/neo4j-graphrag-python

**功能覆盖**：
| 功能 | 支持情况 |
|------|----------|
| VectorRetriever（向量检索） | ✅ |
| HybridRetriever（向量+全文检索） | ✅ |
| Text2CypherRetriever（自然语言→Cypher） | ✅ |
| ToolsRetriever（多检索器路由） | ✅ |
| GraphRAG Pipeline（端到端） | ✅ |
| Anthropic Claude 支持 | ✅（`pip install neo4j-graphrag[anthropic]`） |
| LangChain/LangGraph 集成 | ✅ |

**安装**：`pip install neo4j-graphrag[anthropic]`

**优势**：Neo4j 官方维护，长期支持，已包含我们需要的所有检索器
**劣势**：检索器是积木，业务逻辑（多步推理、烹饪科学解释）仍需自建

#### 方案C：混合（推荐）

**`neo4j-graphrag-python` 做检索层 + LangGraph 做推理 agent 图**

```
用户查询
    ↓
LangGraph StateGraph（L3推理引擎）
    ├── [工具1] VectorRetriever → L0 语义相似原理
    ├── [工具2] HybridRetriever → L2b 食谱+全文
    ├── [工具3] Text2CypherRetriever → 图结构查询（食材替换路径）
    ├── [工具4] DomainRouter → 判断查询属于哪个域
    └── [工具5] Graphiti → 用户历史偏好（个性化记忆）
    ↓
Claude Opus/Sonnet（合成推理结果）
    ↓
L6翻译层（粤菜语言转换）
    ↓
结构化响应
```

**参考实现**：
- Neo4j 官方博客：[Neo4j GraphRAG Workflow with LangChain and LangGraph](https://neo4j.com/blog/developer/neo4j-graphrag-workflow-langchain-langgraph/)
- GitHub 参考：https://github.com/FlorentB974/graphrag（LangGraph + Neo4j）
- agent-service-toolkit：https://github.com/JoshuaC215/agent-service-toolkit（LangGraph + FastAPI + Streamlit 完整套件）

**Graphiti 集成**：
- 已确认原生 Neo4j 支持
- LangGraph + Graphiti 长期记忆已有成熟教程
- 用于 L3-personal：记录用户的口味偏好、历史查询、食材黑名单

**推荐方案C工作量**：1-2 周（检索器接入 3 天，LangGraph agent 图 4-5 天，端到端测试 2 天）

---

## 3. API 层

### 方案对比

| 方案 | 工具 | 优势 | 劣势 | 推荐 |
|------|------|------|------|------|
| A | FastAPI（纯自建） | 完全控制，无外部依赖，Python 生态一致 | 需要自写流式响应、WebSocket | ✅ 推荐 |
| B | LangServe | 自动生成端点，内置 playground | 已停止新功能开发，LangChain 推荐迁移到 LangGraph Platform | ❌ |
| B2 | LangGraph Platform（云托管） | 托管部署，内置持久化 | 有云依赖，本地 Mac Studio 部署不适合，成本不可控 | ❌ |
| B3 | Aegra（开源 LangGraph Platform 替代） | 自托管，PostgreSQL 持久化，FastAPI 底层，5分钟 Docker 部署 | 项目较新，不如 FastAPI 灵活 | 可选 |
| C | FastAPI + LangGraph Server | 标准 REST，流式支持，本地部署 | — | ✅ 推荐 |

**推荐：FastAPI 自建**

理由：
1. LangServe 已进入维护模式，不建议新项目使用
2. 项目在 Mac Studio 本地部署，LangGraph Platform 云托管不适合
3. FastAPI 轻量，SSE 流式响应 5 行代码，与 Chainlit 前端配合无缝
4. Pydantic v2 数据验证，自动 OpenAPI 文档

**API 端点设计**：
```
POST /api/query          — 查询推理（SSE流式）
POST /api/recipe/search  — 食谱搜索
POST /api/ingredient/substitute  — 食材替换
GET  /api/principle/{id} — L0原理详情
POST /api/session        — 会话管理（Graphiti）
GET  /health             — 健康检查
```

**工作量**：3-4 天（含 SSE 流式、会话管理、错误处理）

---

## 4. 用户界面

### 目标用户特征
- 专业厨师 / 餐饮老板 / 研发团队
- 主要用中文操作
- 需要对话式交互（"这道菜怎么让肉更嫩"）
- 不需要复杂的图谱可视化（那是内部工具）
- 要简洁实用，不要 "很技术"

### 方案对比

#### Chainlit（推荐）

**官网**：https://chainlit.io/
**GitHub**：https://github.com/Chainlit/chainlit

| 维度 | 评估 |
|------|------|
| LangGraph 集成 | ✅ 官方支持，有 cookbook 示例（langgraph-memory） |
| 中文显示 | ✅ Unicode 全支持，无需额外配置 |
| 流式响应 | ✅ 原生 token streaming |
| 对话历史 | ✅ 内置 message history |
| 用户认证 | ✅ 可选，内置 OAuth/密码 |
| 文件上传 | ✅ 图片、PDF 上传支持 |
| 自定义 CSS | ✅ 可定制主题 |
| 部署方式 | 本地 / Docker，无云依赖 |
| 学习成本 | 低，Python 装饰器模式，1天上手 |
| 生产就绪 | 中等，适合内部工具和小团队 |

**示例代码**（5行接入 LangGraph）：
```python
import chainlit as cl
from langchain_core.messages import HumanMessage

@cl.on_message
async def main(message: cl.Message):
    graph = cl.user_session.get("graph")
    async for event in graph.astream_events(
        {"messages": [HumanMessage(content=message.content)]},
        version="v2"
    ):
        if event["event"] == "on_chat_model_stream":
            await cl.Message(content=event["data"]["chunk"].content).stream_token(event["data"]["chunk"].content)
```

#### Streamlit（备选）

| 维度 | 评估 |
|------|------|
| LangGraph 集成 | 需要自建 WebSocket 桥接 |
| 中文显示 | ✅ |
| 流式响应 | 需要 `st.write_stream` hack |
| 对话历史 | 需要自建 session state |
| 部署 | 简单，`streamlit run` |
| 适合场景 | 数据看板、分析工具，不是对话 AI |

**缺点**：不是为对话式 AI 设计的，流式体验较差，LangGraph 集成需要额外工作。

#### Gradio（不推荐）

适合 ML 模型演示，对话式 AI 体验不如 Chainlit。

#### Open WebUI（备选，功能最强但最重）

| 维度 | 评估 |
|------|------|
| LangGraph 集成 | 通过 Pipeline 接入，有社区案例 |
| 中文界面 | ✅ 内置多语言 |
| 功能 | 最丰富：模型选择、对话历史、图片、文档 |
| 部署 | Docker，比较重 |
| 适合场景 | 需要完整 ChatGPT 体验时 |

**缺点**：对于专属烹饪引擎，功能过于通用，定制成本高。

#### Next.js 完全自建（不推荐，当前阶段）

完整自定义 UI，工作量 2-3 周，当前阶段不值得投入。终局架构（P6）可考虑。

### 图谱可视化（内部工具）

用户端不需要图谱可视化。如果内部调试需要：
- **Neo4j Bloom**：免费，内置于 Neo4j Desktop，直接可用，零开发
- **Neo4j Browser**：内置于 Neo4j，执行 Cypher 查询并可视化

**推荐**：Chainlit（用户端对话 UI）+ Neo4j Bloom（内部图谱调试）

**工作量**：
- Chainlit 基础接入：1 天
- 中文 prompt 适配、主题定制：1 天
- 多轮对话、会话持久化：1 天

---

## 5. 推荐方案总览（方案C混合）

| 层 | 选型 | 是否自建 | 工作量 |
|----|------|----------|--------|
| 数据导入 | Python ETL + `neo4j-admin` CSV | 自建（轻量） | 2-3 天 |
| Neo4j Schema | 手工设计 Cypher | 自建 | 1 天（含导入脚本） |
| 检索层 | `neo4j-graphrag-python` | **用轮子** | 1 天接入 |
| 推理 agent | LangGraph StateGraph + 5工具 | 自建（业务逻辑） | 1 周 |
| 个性化记忆 | Graphiti + Neo4j | **用轮子** | 1-2 天接入 |
| API 层 | FastAPI + SSE streaming | 自建 | 3-4 天 |
| 对话前端 | Chainlit | **用轮子** | 2-3 天定制 |
| 内部图谱调试 | Neo4j Bloom（内置） | **用轮子** | 0 天 |

**总计估算：3-4 周**（可并行部分任务压缩到 2.5 周）

---

## 6. 完整技术栈清单

```
数据存储
├── Neo4j 5.x              — 主图谱（L0+L2b+关系网+向量索引）
│   └── APOC 插件          — 增量导入、图算法
└── （可选冷层）PostgreSQL  — FoodKG/FoodAtlas 完整数据集

检索 & RAG
├── neo4j-graphrag-python  — 官方 GraphRAG 包（vector/hybrid/cypher检索器）
│   └── pip install neo4j-graphrag[anthropic]
└── qwen3-embedding:8b     — 本地 Ollama embedding（已在用）

推理 Agent
├── LangGraph              — 推理状态图（已确定）
├── Graphiti               — 用户个性化记忆（LangGraph集成）
└── LLM 路由:
    ├── Claude Opus 4.6    — 深度推理（关键决策）
    ├── Claude Sonnet 4.6  — 日常对话响应
    └── Ollama qwen3.5 9b  — 本地快速分类/路由

API 层
├── FastAPI                — REST + SSE 流式
├── Pydantic v2            — 数据验证
└── uvicorn                — ASGI server

用户界面
├── Chainlit               — 对话式 AI 前端（LangGraph原生支持）
└── Neo4j Bloom            — 内部图谱可视化（零配置）

基础设施（已有）
├── Mac Studio M4 Max 128G — 本地部署
├── Ollama                 — 本地 LLM 服务
└── DashScope              — qwen flash API（OCR + 辅助）
```

**安装依赖（核心）**：
```bash
pip install neo4j-graphrag[anthropic] langgraph graphiti-core chainlit fastapi uvicorn
```

---

## 7. 实施路线图

### 第一阶段（第1-2周）：存储层就绪

**Week 1**：
- [ ] Neo4j 5.x Docker 启动，APOC 插件安装（0.5天）
- [ ] Schema 设计：Principle/Recipe/Ingredient/Domain 节点 + 关系类型（1天）
- [ ] 编写 JSONL → CSV 转换脚本（1天）
- [ ] `neo4j-admin` 全量导入 L0（44,692条） + L2b（29,085条）（0.5天）
- [ ] 验证：Cypher 查询 + 向量索引建立（0.5天）

**Week 2**：
- [ ] FastAPI 骨架搭建（路由、中间件、错误处理）（1天）
- [ ] `neo4j-graphrag-python` 接入：VectorRetriever + HybridRetriever（1天）
- [ ] 基础 Text2Cypher 接入（食材替换查询）（1天）
- [ ] Chainlit 前端搭建，接通 FastAPI（1天）
- [ ] 端到端测试：中文查询 → 检索 → 响应（1天）

**验收标准**：能用中文提问"猪肉怎么嫩化"，系统返回 L0 相关原理 + 相关食谱

### 第二阶段（第3周）：L3推理引擎

- [ ] LangGraph StateGraph 设计（5工具架构）（2天）
- [ ] 工具实现：DomainRouter + 多检索器（2天）
- [ ] Graphiti 接入：用户偏好记忆（1天）
- [ ] Chainlit 前端优化：中文 prompt 模板、对话历史（1天）
- [ ] 粤菜场景端到端测试（1天）

**验收标准**：多轮对话，系统能记住"我偏好清淡"，下次推荐相应调整

### 第三阶段（第4周）：外部数据 + 精调

- [ ] FoodAtlas/FooDB ETL 导入（L2a + FT层）（2天）
- [ ] L6翻译层接入（粤菜语言映射）（1天）
- [ ] 性能测试：并发查询，响应时间优化（1天）
- [ ] Jeff 实际场景验证：10个真实粤菜研发查询（1天）

**验收标准**：响应时间 < 5秒，10个测试查询通过率 > 80%

---

## 8. 第一步具体指令（给 coder agent）

```
Task: Neo4j 搭建 + L0/L2b 全量导入
Agent: coder
Priority: P1
Branch: feat/neo4j-setup

Objective:
  搭建 Neo4j 5.x，设计 Schema，将 L0（44,692条）和 L2b（29,085条）全量导入，建立向量索引。

Input:
  - L0 数据：~/l0-knowledge-engine/output/stage4/（各书 JSONL）
  - L2b 数据：~/l0-knowledge-engine/output/stage5/（各书 JSONL）
  - Schema 参考：本文档第1节

Expected Output:
  - docker-compose.yml：Neo4j 5.x + APOC
  - scripts/neo4j_setup.sh：创建索引、约束
  - scripts/jsonl_to_csv.py：JSONL → neo4j-admin CSV 转换（nodes + relationships）
  - scripts/import_l0.sh：neo4j-admin 导入命令
  - scripts/verify_import.py：验证导入结果（条数、关系数、向量索引）

Success Criteria:
  1. Neo4j Browser 可访问
  2. L0 节点数 ≥ 44,692，L2b Recipe 节点数 ≥ 29,085
  3. Principle 节点有向量索引（embedding 字段）
  4. 基础 Cypher 查询返回正确结果：
     MATCH (p:Principle {domain: 'protein_science'}) RETURN count(p)
  5. 向量相似度查询返回结果（用 qwen3-embedding:8b 验证）

Context:
  - 当前 embedding 模型：qwen3-embedding:8b（Ollama 本地，已运行）
  - Neo4j 向量索引：内置，不用 Weaviate
  - 数据格式参考：output/stage4/ 下的 JSONL 文件，字段见 STATUS.md

Constraints:
  - Neo4j 用 Docker，不要直接安装
  - 所有脚本放 scripts/ 目录
  - trust_env=False（绕过本机代理 127.0.0.1:7890）
  - 不引入新的 Python 库（除 neo4j driver + neo4j-graphrag）
```

---

## 附录：关键资源链接

- neo4j-graphrag-python 文档：https://neo4j.com/docs/neo4j-graphrag-python/current/
- neo4j-graphrag-python GitHub：https://github.com/neo4j/neo4j-graphrag-python
- LangGraph + Neo4j 参考实现：https://github.com/FlorentB974/graphrag
- Chainlit LangGraph Cookbook：https://github.com/Chainlit/cookbook/tree/main/langgraph-memory
- Graphiti GitHub：https://github.com/getzep/graphiti
- Graphiti + Neo4j 集成：https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/
- Neo4j admin import 文档：https://neo4j.com/docs/operations-manual/current/import/
- agent-service-toolkit（LangGraph + FastAPI + Streamlit 参考）：https://github.com/JoshuaC215/agent-service-toolkit
