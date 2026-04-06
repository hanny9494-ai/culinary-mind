# ce-hub v2 — 完整技术方案

## 架构总览

```
Jeff (tmux attach / SSH from Mac Mini)
  └── tmux session "cehub"
       ├── window 0: cc-lead (claude --model opus)
       ├── window 1: coder (codex / sonnet)      [按需弹出]
       ├── window 2: researcher (gemini)          [按需弹出]
       ├── window 3: pipeline-runner (sonnet)     [按需弹出]
       └── window N: ...

ce-hub daemon (Node.js, 常驻后台)
  ├── FileWatcher    → 监控 .ce-hub/dispatch/ inbox/ results/
  ├── TmuxManager    → 动态创建/销毁 tmux window
  ├── TaskEngine     → DAG 任务队列 + auto-pilot
  ├── MemoryManager  → 每个 agent 独立记忆
  ├── QualityGate    → 任务完成后自动 QC
  ├── CostTracker    → token/cost 记录 + 预算告警
  ├── Scheduler      → cron 定时调度
  ├── ResumeBuilder  → CC Lead session 自动恢复
  └── SQLite         → 持久化一切

文件协议 (.ce-hub/):
  ├── dispatch/      → agent 写 dispatch 请求
  ├── inbox/{agent}/ → 每个 agent 的收件箱
  ├── results/       → 任务结果归档
  ├── memory/{agent}/→ 每个 agent 的长期记忆
  ├── quality-gates.json → QC 规则定义
  └── status.json    → 系统全局状态
```

## 1. 文件协议

### dispatch 请求
Agent 写文件到 `.ce-hub/dispatch/`:
```json
{
  "id": "uuid",
  "from": "cc-lead",
  "to": "coder",
  "task": "写 L2a Gemini 蒸馏脚本",
  "context": "canonical_map_v2.json 有 24,578 atoms，需要批量调 Gemini 补充品种/产地/季节",
  "priority": 1,
  "depends_on": [],
  "created_at": "2026-04-02T00:00:00Z"
}
```

### inbox 消息
ce-hub 写文件到 `.ce-hub/inbox/{agent}/`:
```json
{
  "id": "uuid",
  "from": "cc-lead",
  "type": "task",
  "content": "写 L2a Gemini 蒸馏脚本...",
  "task_id": "uuid",
  "created_at": "2026-04-02T00:00:00Z"
}
```

### results 回传
Agent 写文件到 `.ce-hub/results/`:
```json
{
  "id": "uuid",
  "from": "coder",
  "task_id": "uuid",
  "status": "done",
  "summary": "脚本在 scripts/l2a_gemini_distill.py，已测试通过",
  "output_files": ["scripts/l2a_gemini_distill.py"],
  "metrics": {"lines_of_code": 245},
  "created_at": "2026-04-02T00:30:00Z"
}
```

## 2. TmuxManager

```typescript
class TmuxManager {
  // 动态启动 agent，根据 model 字段决定命令
  startAgent(agentName: string, def: AgentDefinition): void;

  // 命令解析
  resolveCommand(def: AgentDefinition): string;
  // model: "opus"/"sonnet" → claude --model xxx --dangerously-skip-permissions
  // model: "codex" → codex exec --dangerously-bypass-approvals-and-sandbox
  // model: "gemini-*" → python3 scripts/gemini_agent.py
  // model: "sonnet" + agent=pipeline-runner → claude --model sonnet (跑 .py 脚本)

  // 检测 agent 完成（tmux window 进程退出）
  watchExit(agentName: string, callback: () => void): void;

  // 列出活跃 agent
  listWindows(): { name: string; alive: boolean }[];

  // 杀掉 agent
  killAgent(agentName: string): void;
}
```

tmux session 名: `cehub`
window 命名: agent name (cc-lead, coder, researcher, ...)

## 3. Auto-pilot (TaskEngine 升级)

```typescript
class TaskEngine {
  // 自动模式：持续从队列取任务执行
  startAutoPilot(): void;

  // 流程：
  // 1. 取 priority 最高的 pending task
  // 2. 检查 depends_on 是否全部 done
  // 3. 启动 target agent（tmux window）
  // 4. 写任务到 agent inbox
  // 5. 等待 result 文件出现
  // 6. 跑 QualityGate
  // 7. 通过 → 标记 done，触发下游
  //    不通过 → retry 或 dead_letter

  // DAG 示例：
  // L2a Round 2 (Opus merge)
  //   → L2a Round 3 (Flash remap)
  //     → L2a Gemini 蒸馏
  //       → Neo4j 导入
}
```

## 4. Agent 独立记忆

每个 agent 的记忆存在 `.ce-hub/memory/{agent}/`:

```
.ce-hub/memory/
├── cc-lead/
│   ├── decisions.md      → 重大决策记录
│   └── context.md        → 最近工作上下文
├── coder/
│   ├── scripts.md        → 写过的脚本清单
│   ├── bugs.md           → 踩过的坑
│   └── patterns.md       → 代码模式偏好
├── researcher/
│   ├── sources.md        → 查过的数据源
│   └── findings.md       → 研究结论
└── pipeline-runner/
    ├── runs.md           → 跑过的 pipeline 记录
    └── issues.md         → 常见问题和解决方案
```

Agent 启动时，ce-hub 把 memory 文件内容注入 system prompt：
```bash
claude --model sonnet --append-system-prompt "$(cat .ce-hub/memory/coder/*.md)"
```

Agent 完成任务后，ce-hub 从结果中提取关键信息更新 memory 文件。

## 5. 质量门禁

`.ce-hub/quality-gates.json`:
```json
{
  "l2a_normalize": {
    "check": "python3 scripts/l2a_qc.py --input output/l2a/canonical_map_v2.json",
    "pass_criteria": {
      "coverage_min": 0.8,
      "duplicate_max": 0.02,
      "garbage_max": 0.01
    },
    "on_fail": "retry",
    "max_retries": 2
  },
  "stage4_extract": {
    "check": "python3 scripts/stage4_quality.py --input {output_file}",
    "pass_criteria": {
      "pass_rate_min": 0.7
    },
    "on_fail": "flag_for_review"
  },
  "code_review": {
    "check": "@code-reviewer: review {output_files}",
    "on_fail": "send_back_to_coder"
  }
}
```

## 6. 成本追踪

SQLite 表:
```sql
CREATE TABLE cost_log (
  id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cost_usd REAL,
  task_id TEXT,
  created_at INTEGER
);

CREATE TABLE budget (
  id TEXT PRIMARY KEY,
  period TEXT NOT NULL,        -- 'daily' | 'weekly' | 'monthly'
  limit_usd REAL NOT NULL,
  current_usd REAL DEFAULT 0,
  action TEXT DEFAULT 'warn'   -- 'warn' | 'downgrade' | 'pause'
);
```

自动降级逻辑：
- 日预算 80% → 通知 CC Lead
- 日预算 95% → opus 自动降级为 sonnet
- 日预算 100% → 暂停非 P0 任务

## 7. 定时调度

```json
// .ce-hub/schedules.json
[
  { "cron": "0 23 * * *", "task": "日报生成", "agent": "cc-lead" },
  { "cron": "0 2 * * *", "task": "Stage4 批量蒸馏", "agent": "pipeline-runner" },
  { "cron": "*/30 * * * *", "task": "健康检查", "agent": "ops" }
]
```

## 8. CC Lead 自动恢复

检测 CC Lead 的 claude 进程退出（tmux window 进程结束）：
1. 从 SQLite + .ce-hub/memory/cc-lead/ 生成 resume prompt
2. 在同一个 tmux window 重启 claude
3. 注入 resume prompt 作为第一条消息

## 9. Mac Mini 远程 Worker

Mac Mini 上跑 ce-hub worker 模式：
```bash
# Mac Mini 上
ce-hub worker --master ssh://mac-studio --role data-collector
```

Worker 通过 SSH/rsync 同步 `.ce-hub/` 目录：
- 主机写 dispatch → rsync 到 Mini → Mini 执行 → 结果 rsync 回来
- 或者 Mini 上跑 openssh + 直接访问 NFS 共享目录

## 10. 文件结构

```
ce-hub/
├── src/
│   ├── index.ts           → daemon 入口
│   ├── tmux-manager.ts    → tmux session/window 管理
│   ├── file-watcher.ts    → .ce-hub/ 目录监控
│   ├── task-engine.ts     → DAG + auto-pilot
│   ├── memory-manager.ts  → agent 记忆管理
│   ├── quality-gate.ts    → QC 自动检查
│   ├── cost-tracker.ts    → 成本追踪 + 预算
│   ├── scheduler.ts       → cron 定时调度
│   ├── resume-builder.ts  → CC Lead 恢复
│   ├── state-store.ts     → SQLite CRUD
│   └── types.ts           → 类型定义
├── migrations/
│   └── 001_init.sql       → 完整 schema
└── package.json
```

## 11. 启动方式

```bash
# 启动 daemon（后台）
cd ~/culinary-engine/ce-hub && npm run daemon

# 打开 tmux 会议室
tmux attach -t cehub

# 或者一键启动
ce-hub start  → daemon + tmux session + cc-lead
```

## 12. CLAUDE.md 协议注入

每个 agent 的 system prompt 需要包含文件协议说明：

```markdown
## ce-hub 通信协议

你通过文件系统与其他 agent 通信：

### 收消息
检查 .ce-hub/inbox/{your-name}/ 目录，读取 JSON 文件获取任务。

### 派任务
写 JSON 到 .ce-hub/dispatch/:
{"from":"your-name","to":"target-agent","task":"描述"}

### 报告结果
写 JSON 到 .ce-hub/results/:
{"from":"your-name","task_id":"xxx","status":"done","summary":"...","output_files":[]}

### 你的记忆
你的长期记忆在 .ce-hub/memory/{your-name}/，启动时已加载。
完成重要工作后，更新你的记忆文件。
```
