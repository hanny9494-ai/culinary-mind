# ce-hub v2 TUI 交接记录

## 本次实现内容（2026-04-02 ~ 04-03）

### 1. tmux TUI 布局

实现了 tmux 3 pane 布局，一行命令启动：

```bash
CE_HUB_CWD=~/culinary-engine bash ~/culinary-engine/ce-hub/scripts/layout.sh --attach
```

布局：
```
┌──────────────────────────────────────────────────┐
│           CC Lead (固定, opus, ~65% 高度)          │
├───────────────────────┬──────────────────────────┤
│   Dashboard           │   Agent Slot             │
│   (实时状态, 35%)     │   (可切换 subagent)      │
└───────────────────────┴──────────────────────────┘
```

- CC Lead 写死在顶部最大 pane，用 `claude --model opus --agent cc-lead`
- Dashboard 用 `scripts/dashboard.py` 实时显示状态
- Agent Slot 支持右键切换不同 agent

### 2. Dashboard 面板（scripts/dashboard.py）

每 8 秒刷新，显示：
- ce-hub daemon 状态 + uptime
- 所有 9 个 agent 的在线/离线状态
- Task 队列（按 status 分组）+ 队列压力（opus/flash/ollama）
- Claude Code token 消耗：最近 5 小时 + 全量（从 `~/.claude/projects/` JSONL 解析）
- 活跃 Claude sessions 数量
- 成本追踪（daily/weekly）
- 定时任务列表
- 文件协议状态（dispatch/inbox/results 队列深度）

### 3. 鼠标操作

全鼠标交互，不需要记快捷键：
- **点击 pane** → 切换焦点
- **拖拽边框** → 调整大小
- **右键 Agent Slot** → 弹出 agent 切换菜单 + "Add Agent Pane" + "Close This Pane"
- **右键 Dashboard** → 弹出操作菜单（查看 costs/tasks/health，添加 agent pane）
- **右键 CC Lead** → zoom/restart 菜单
- **点击 status bar 右侧** → 弹出 agent 切换菜单

实现方式：tmux `display-menu`（tmux 3.2+）+ `right-click-handler.sh` 根据 pane index 分发不同菜单。

### 4. 动态 Agent Pane 管理

通过 `scripts/pane-manager.sh` 支持：
- `pane-manager.sh add [agent]` — 动态添加 agent pane（split from bottom-right）
- `pane-manager.sh close [pane-id]` — 关闭 agent pane（保护 CC Lead 和 Dashboard 不可关闭）
- `pane-manager.sh switch <pane-id> <agent>` — 切换 pane 里的 agent
- `pane-manager.sh list` — 列出所有 pane

### 5. CC Lead → Agent 通信（Dispatch 桥梁）

**文件协议通信流**：
```
CC Lead 写 .ce-hub/dispatch/{task}.json
  → FileWatcher 检测到
  → 创建 task 记录到 SQLite
  → 写 inbox 文件到 .ce-hub/inbox/{agent}/
  → TmuxManager.startAgent()（如果 agent 没在跑就启动）
  → TmuxManager.sendMessage()（tmux send-keys 把消息打到 agent pane）
  → Agent 处理任务
  → Agent 写 .ce-hub/results/{result}.json
  → FileWatcher 检测到
  → 更新 task 状态
  → 通知 CC Lead（写 inbox + send-keys）
```

已测试通过：dispatch 文件写入后，researcher pane 3 秒内收到消息并开始执行。

### 6. Bug 修复

- **403 认证错误**：layout.sh 清空了 `http_proxy` 导致 Claude Code 无法通过代理访问 API。修复：只设 `no_proxy=localhost,127.0.0.1`，保留代理。
- **ESM import hoisting**：file-watcher.ts 的 `const CWD` 在模块顶层，由于 ESM import 先于 .env 加载执行，导致 CWD 取到 `process.cwd()`（ce-hub/）而不是 `.env` 里的值。修复：改为 lazy getter `getCwd()`。
- **macOS sed 兼容**：`sed -n '/^---$/,/^---$/{ ... }'` 在 macOS 上不支持。全部替换为 `grep + sed` 组合。
- **tmux pane title 覆盖**：Claude Code 启动后会把 pane title 改为 `✳ agent-name`。TmuxManager 的 `findAgentTarget` 和 `isAlive` 改为模糊匹配（`includes`）。

## 文件清单

### 新增文件

| 文件 | 用途 |
|---|---|
| `scripts/dashboard.py` | 实时 TUI dashboard（Python，轮询 API + 解析 session JSONL）|
| `scripts/layout.sh` | tmux session 布局设置（3 pane + 鼠标绑定）|
| `scripts/agent-select.sh` | 交互式 agent 选择菜单（用于 pane 内选择）|
| `scripts/switch-agent.sh` | 切换 agent（pane-manager 的 wrapper）|
| `scripts/pane-manager.sh` | 动态 pane 管理（add/close/switch/list）|
| `scripts/mouse-bindings.sh` | tmux 鼠标绑定 + status bar + pane border 样式 |
| `scripts/right-click-handler.sh` | 右键菜单分发（根据 pane index 显示不同菜单）|

### 修改文件

| 文件 | 改动 |
|---|---|
| `package.json` | 添加 layout/dashboard npm scripts，dev/daemon 命令加 CE_HUB_CWD |
| `src/file-watcher.ts` | 添加 writeFileSync import，CWD 改为 lazy getter |
| `src/tmux-manager.ts` | sendMessage/isAlive/listWindows 支持 pane 查找 + 模糊匹配 |

## 已知限制

1. **Agent pane 里的 claude 进程是独立 session** — 不会自动读 inbox，需要 daemon 用 `tmux send-keys` 发消息提示
2. **CC Lead 内置 Agent tool（subprocess）** 和 **tmux pane agent** 是两个独立通道 — subprocess 不可见，pane agent 可见
3. **task-engine.executeTask()** 仍是 mock — 真实的 task 执行走 file protocol，不走 task-engine
4. **Quality gate** 还没有定义规则
5. **Cost tracker** 基础设施就绪但没有真实 API 调用数据

## 启动命令汇总

```bash
# 一键启动（daemon 已在跑的情况下）
CE_HUB_CWD=~/culinary-engine bash ~/culinary-engine/ce-hub/scripts/layout.sh --attach

# 完整启动（含 daemon）
cd ~/culinary-engine/ce-hub
CE_HUB_CWD=~/culinary-engine npm run dev &
sleep 3
CE_HUB_CWD=~/culinary-engine bash scripts/layout.sh --attach

# 重置
CE_HUB_CWD=~/culinary-engine bash scripts/layout.sh --reset

# 预装 researcher 到 agent slot
CE_HUB_CWD=~/culinary-engine bash scripts/layout.sh researcher
```
