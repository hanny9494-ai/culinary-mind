# PR #1 设计说明：wiki-curator + Wiki Write Lockdown

**PR**: feat/wiki-curator-agent  
**日期**: 2026-04-07  
**作者**: coder agent

## 问题陈述

1. `raw→wiki` 管道完全无效：`curate-wiki` 系统任务跑的 `ingest-all.py` 只读 `.md` 报告，从不处理 JSONL 数据
2. 多个 wiki writer 并存：`compile-wiki.py` 写 `.ce-hub/wiki/`，`tmux-manager.ts` PROTOCOL_PROMPT 指向 `.ce-hub/wiki/`，wiki 目录分叉
3. daemon `libsimdjson` 崩溃导致今天 08:00 cron 静默失败

## 架构决策

### Wiki Write Invariant（P0）
- **只有 `wiki-curator` agent** 可写 `/Users/jeff/culinary-mind/wiki/`
- `raw/` 是唯一输入，wiki-curator 是唯一输出
- `intent=log` dispatch 机制让 cc-lead 可以即时记录重要事件

### raw/ 输出目录扩展
- `raw/research/` ← researcher 输出
- `raw/architecture/` ← architect 输出  
- `raw/coder/` ← coder PR 设计说明（本文件）
- `raw/log/` ← cc-lead intent=log dispatch 落盘

## 修改清单

| 文件 | 修改 |
|---|---|
| `.claude/agents/wiki-curator.md` | 新建 → 全量 LLM wiki 编译 agent |
| `.ce-hub/schedules.json` | curate-wiki → dispatch wiki-curator |
| `ce-hub/scripts/compile-wiki.py` | 删除 → `_archived/compile-wiki.py.bak` |
| `ce-hub/src/tmux-manager.ts` | PROTOCOL_PROMPT：Wiki Write Invariant + 输出存放规则 |
| `ce-hub/src/resume-builder.ts` | `.ce-hub/wiki/` → `/Users/jeff/culinary-mind/wiki/` |
| `ce-hub/src/api.ts` | wiki 路由指向正确目录 |
| `CLAUDE.md` | 新增 §3.5 Wiki Write Invariant + §3.6 CC Lead wiki 记录方式 |
| `.claude/agents/researcher.md` | 输出路径 `docs/research/` → `raw/research/` |
| `.claude/agents/architect.md` | 输出路径 `reports/` → `raw/architecture/` |
| `.claude/agents/coder.md` | 新增 §7 输出存放规则 |
| `wiki/STATUS.md` | 合并 `.ce-hub/wiki/STATUS.md` + 旧版本，更新至 2026-04-07 |
| `wiki/_conflicts.md` | 新建（conflicts 跟踪文件） |
| `raw/{research,architecture,coder,log}/README.md` | 新建（目录说明） |

## 验证

- `wiki/STATUS.md` mtime 14:33 > `raw/conversations.jsonl` mtime 14:32 ✅
- `.ce-hub/wiki/` 目录已删除 ✅
- `compile-wiki.py` 已归档 ✅
- PROTOCOL_PROMPT 包含 Wiki Write Invariant ✅
- CLAUDE.md §3.5 + §3.6 存在 ✅
- `raw/{research,architecture,coder,log}/` 目录存在 ✅
