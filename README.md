# Culinary Mind

**管理系统** for Culinary Engine — 烹饪科学推理引擎。

Culinary Mind 是项目的知识管理和任务调度基础设施。它不是产品本身，而是让产品能高效迭代的系统。

## 项目关系

```
Culinary Mind (本仓库)
  = 知识管理 + 任务调度 + Pipeline 管理
  ↓ 服务于
Culinary Engine (主线产品)
  = L0-L6 七层架构 + 推理引擎
  ↓ 交付
食谱 R&D Agent (最终产品)
  = 给专业厨师/餐饮老板用的 AI 助手
```

## 核心能力

### 知识系统 (Karpathy LLM Knowledge Base 模式)
```
raw/ (真相源) → LLM 编译 → wiki/ (Obsidian vault)
```
- LLM 写完整百科文章，不是 bullet points
- 每个源文件逐个 ingest，自动创建/更新 wiki 页面
- Obsidian 前端：graph view + backlinks + 搜索

### 任务调度 (ce-hub)
- tmux TUI：CC Lead + Agent Slots + Task Board
- 文件协议通信：dispatch → inbox → result
- 自动调度：cron + agent 管理 + 进程守护

### Pipeline 管理
5 条独立 pipeline，按功能命名：

| Pipeline | 用途 | 脚本目录 |
|---|---|---|
| `prep` | 书籍预处理（OCR + 切分 + 标注）| `pipeline/prep/` |
| `l0` | L0 科学原理提取 + 因果链 + QC | `pipeline/l0/` |
| `l2b` | 食谱提取 + L0 绑定 | `pipeline/l2b/` |
| `l2a` | 食材归一化 + 蒸馏 | `pipeline/l2a/` |
| `graph` | Neo4j 图谱构建 | `pipeline/graph/` |

## 数据基线 (2026-04-06)

| 层 | 数据量 | 状态 |
|---|---|---|
| L0 科学原理 | 51,924 条（44 书）| 收官中 |
| L2a 食材 | 26,434 canonicals, 21,422 R1 atoms | R2 进行中 |
| L2b 食谱 | 41,317 条（43 书）| Step B/C 待做 |
| L2c 商业食材 | 2,730 条 | TDS 待抓 |

## 快速开始

```bash
# 启动调度系统
cd ce-hub && CE_HUB_CWD=~/culinary-mind npm run dev &
bash scripts/layout.sh --attach

# 查看 wiki
open -a Obsidian ~/culinary-mind/wiki

# ingest 新文档到 wiki
python3 mind/ingest-source.py <source-file>

# 批量 ingest
python3 mind/ingest-all.py
```

## 设计原则

- **Karpathy LLM Knowledge Base**: raw 是真相，wiki 是编译产物，LLM 做编辑人做审阅
- **Farzapedia 启发**: index.md 导航，agent 从 wiki 爬取上下文
- **User Sovereignty (Gstack)**: AI 推荐，Jeff 决定
- **Memory 是指南针**: 指向 wiki，不存内容
- **Dreaming**: 长期不提及的知识自然衰减

## License

MIT
