# TUI Rebuild v1 设计文档

**分支**: tui/rebuild-dashboard-window-nav  
**日期**: 2026-04-07  
**屏幕**: 149 cols × 117 rows

## 架构设计

### 布局变化

**旧版**：单 `main` window，3-4 个 pane（cc-lead + 2 agent slots + task board）  
**新版**：9 个独立 window，每个 window 内 2 个 pane（dashboard 上 + agent 下）

```
Window: cc-lead (0)          Window: coder (1)
┌─────────────────────────┐  ┌─────────────────────────┐
│ dashboard (~20 rows)    │  │ dashboard (~20 rows)    │
├─────────────────────────┤  ├─────────────────────────┤
│ cc-lead agent (~96 rows)│  │ coder agent (~96 rows)  │
└─────────────────────────┘  └─────────────────────────┘
[cc-lead][coder][research][arch][pipeline][reviewer][ops][datacol][wiki]
```

### Window 列表
```
0: cc-lead
1: coder
2: researcher
3: architect
4: pipeline-runner
5: code-reviewer
6: ops
7: open-data-collector
8: wiki-curator
```

### 底部导航栏

使用 tmux `window-status-format` 实现大号色块：
- inactive: `#[bg=colour237,fg=colour245]`（深灰底）
- active: `#[bg=colour214,fg=colour234,bold]`（橙底）
- attention: `#[bg=colour196,fg=colour231,bold]`（红底，1s 交替闪烁）
- 每个 cell ≥ 14 列（使用 %-14s 格式填充）

### Attention 机制

**状态文件**: `.ce-hub/state/attention.json`
```json
{"cc-lead": false, "coder": true, "researcher": false, ...}
```

**写入时机**: file-watcher.ts 处理 dispatch 时 → 设置 attention[to]=true

**清除时机**: `after-select-window` hook → `clear-attention.sh #{window_name}`

**闪烁**: statusbar.sh 读 attention.json，attention=true 时用 `$(( $(date +%s) % 2 ))` 交替 red/orange

**status-interval**: 有任何 attention=true 时 set to 1，否则 8

### Dashboard 5 个 Section

```
① 记忆固化 ─ 对话捕获 / raw 最近入库 / wiki 最近更新 / _conflicts 条目
② Agents ── 9 个 agent 状态（online/idle）+ 最近 dispatch/result
③ Mac Mini ─ placeholder（OpenClaw running / 下一步接 ssh push）
④ 服务健康 ─ daemon/newapi/taskqueue/ollama 端口状态
⑤ Alerts ── daemon down / dispatch stuck / conflicts>0
```

### Dispatch 精确定位

**旧版**: `sendMessage` 找 pane_title 匹配 agentName → 可能命中 dashboard pane  
**新版**: `findAgentTarget` 直接返回 `SESSION:agentName.1`（每个 window 的 pane 1 = agent pane）

### 文件清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `tui-layout.sh` | NEW | 9-window 布局脚本，替代 layout.sh |
| `dashboard.sh` | NEW | 5-section 20 行输出 |
| `statusbar.sh` | REWRITE | window nav bar + attention 颜色 |
| `mouse-bindings.sh` | UPDATE | 加 after-select-window hook |
| `clear-attention.sh` | NEW | 清除指定 window 的 attention |
| `tmux-manager.ts` | UPDATE | startAgent/isAlive/findAgentTarget 改为 window-based |
| `file-watcher.ts` | UPDATE | handleDispatch 写 attention.json |
