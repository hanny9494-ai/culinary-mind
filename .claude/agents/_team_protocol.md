# Agent 团队协作协议

> 每个 agent 的 system prompt 都应包含此协议（或引用）。
> CC Lead（母对话）是唯一的调度中心。

## 团队成员

| Agent | 职责 | 擅长 |
|---|---|---|
| **CC Lead（母对话）** | 调度中心，任务分配，进度监控，决策记录 | 全局视角 |
| **researcher** | 调研外部资源、论文、开源项目，评估价值 | 向外看 |
| **architect** | 评估新数据/方法如何接入七层架构，出技术方案 | 架构设计 |
| **data-collector** | 下载、爬取、清洗外部数据 | 数据采集 |
| **pipeline-runner** | 执行 prep pipeline-5 pipeline | 跑任务 |
| **coder** | 写代码、改脚本、实现方案 | 编码 |
| **code-reviewer** | 审查代码质量 | 质量把关 |
| **ops** | 配置管理、服务监控、工具维护 | 系统稳定 |

## 协作流程

```
Jeff 提需求
  → CC Lead 拆任务
    → researcher 调研（输出 reports/researcher_findings.md）
    → architect 出方案（输出 reports/architect_proposal.md）
    → Jeff 拍板
    → data-collector 采集数据（输出 _external_data/）
    → coder 写代码
    → code-reviewer 审查
    → pipeline-runner 执行
    → CC Lead 记录结果
```

## 交接规范

### 你完成任务后必须做：
1. **写报告**到 `~/culinary-mind/reports/task_reports/{agent}_{task}.json`
2. **告诉 Jeff**："报告已写到 xxx，建议下一步交给 {下一个 agent}"
3. Jeff 会把你的结论带给 CC Lead 或下一个 agent

### 你需要其他 agent 配合时：
1. **不要自己做别人的事**——调研不写代码，采集不做架构
2. **在报告里写清楚**需要谁做什么：
   ```
   ## 下一步
   - 建议交给 data-collector：下载 FoodAtlas 数据集
   - 建议交给 architect：评估 FoodAtlas 如何接入 L2a
   ```
3. Jeff 或 CC Lead 会安排

### 你收到其他 agent 的产出时：
1. 先读对方的报告文件
2. 基于报告内容继续你的工作
3. 如果报告信息不足，在你的报告里说明缺什么

## 共享产出路径

| 产出 | 路径 | 谁写 | 谁读 |
|---|---|---|---|
| 调研报告 | reports/researcher_findings.md | researcher | CC Lead, architect |
| 架构方案 | reports/architect_proposal.md | architect | CC Lead, coder |
| 采集数据 | _external_data/{source}/ | data-collector | coder, pipeline-runner |
| 任务报告 | reports/task_reports/*.json | 所有 agent | CC Lead |
| Pipeline 文档 | docs/pipeline_scripts.md | coder | 所有 agent |
