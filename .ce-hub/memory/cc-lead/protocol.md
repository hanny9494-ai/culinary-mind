## 重要：任务派发方式

你不要使用 Agent tool 派发任务给 subagent。

当你需要让其他 agent 做事时，用 Bash 工具写一个 JSON 文件到 .ce-hub/dispatch/ 目录：

```bash
cat > .ce-hub/dispatch/$(date +%s).json << 'DISPATCH'
{
  "id": "task_xxx",
  "from": "cc-lead",
  "to": "目标agent名称",
  "task": "任务描述",
  "context": "相关上下文",
  "priority": 1
}
DISPATCH
```

可用的 agent：researcher, coder, architect, pipeline-runner, code-reviewer, ops

这样做的原因：目标 agent 在独立的终端窗口运行，Jeff 可以同时看到所有 agent 的工作过程。如果你用 Agent tool，任务在你内部执行，Jeff 在其他窗口看不到。

等 agent 完成后，检查 .ce-hub/inbox/cc-lead/ 目录获取结果。
