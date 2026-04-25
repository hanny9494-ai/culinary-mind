# MEMORY.md - 长期记忆

## 🚨 长时间运行任务必须脱离 session (2026-04-17)

**事件**: Skill A resume 任务因 gateway 重启被杀死 3 次，丢失进度。

**规则**: 所有耗时 >1 分钟的任务必须用 `screen -dmS` 或 `nohup + disown` 启动。

**正确做法**:
```bash
screen -dmS {task_name} bash /tmp/run_{task}.sh
# 或
nohup python3 ... > /tmp/task.log 2>&1 & disown
```

---

## 📋 完整运营规则

**1. 进程管理**
- 所有长任务用 nohup/screen
- Opus 并发 ≤3，Flash 并发 ≤5
- 启动前 `ps aux | grep run_skill` 查残留 ⚠️ 2026-04-17 18:08 违反此条，heldman 启动双进程，已纠正

**2. 完成验证 — 不许虚报**
- 检查 `_progress.json`: `done == total` 才算完成
- 检查 `results.jsonl` 有无 `_error` 行
- 检查 `_run.log` 有无 Summary
- `done < total` → 报 `partial` 不报 `done`

**3. 错误处理**
- 403/401 → API key 问题，停所有同 API 任务，写 alert
- 429 → 降并发，等 1 分钟重试
- 500/502/503 → 脚本自动重试，连续 5 次熔断写 alert
- 进程消失无 Summary → 被杀了，resume 重启

**4. 汇报协议**
- JSON 写到 `.ce-hub/results/`
- 格式：`{"from":"openclaw-main", "type":"result|alert", "task":"...", "content":"..."}`
- 必须含具体数字

**5. 环境变量**
- HTTP 请求 `trust_env=False`
- `unset http_proxy https_proxy`, `no_proxy=localhost,127.0.0.1`
- API key: `L0_API_KEY`, `L0_API_ENDPOINT`, `DASHSCOPE_API_KEY`

**6. 文件路径**
- 根目录：`/Users/jeff/culinary-mind`
- 脚本：`pipeline/skills/run_skill.py`
- 输出：`output/{book_id}/skill_{a,b,c,d}/results.jsonl`

**7. 职责边界**
- ✅ 我负责：执行 pipeline 任务（OCR、信号路由、Skill A/B/C/D）
- ❌ 不负责：外部数据采集（Mac Mini）、写代码改脚本

---

## 🧠 Skill 操作手册 (2026-04-17 更新)

| Skill | 模型 | 并发 | 用途 |
|-------|------|------|------|
| A | **GPT-5.4** (lingya) | 3 | 科学参数提取 |
| B | 灵雅 Flash | 5 | 食谱提取 |
| C | 灵雅 Flash | 5 | 食材原子提取 |
| D | **GPT-5.4** (lingya) | 3 | 风味/文化提取 |
| Signal | DashScope qwen3.6-plus | 5 | 信号路由 |
| OCR | PaddleOCR | - | 页面 OCR |

**API 状态**:
- ✅ GPT-5.4 (lingya): Skill A/D 主力 (2026-04-17 起)
- ✅ 灵雅 Flash: Skill B/C
- ✅ DashScope: 信号路由
- ❌ aigocode: 余额耗尽，已弃用

**重要**: Skill A/D 需运行在 `feat/veto-filter` 分支 (commit 1d8cce5+)

---

## ⚠️ 历史踩坑

1. **session 杀子进程** - gateway 重启杀未 nohup 进程 (3 次)
2. **OCR 100 页限制** - PaddleOCR 每次只处理 100 页
3. **403 重试烧钱** - 余额耗尽仍重试，烧大量 tokens
4. **失败页标 done** - API 失败页被记入 done_pages
5. **虚报完成** - 报 8/8 实际 2 本未完成
6. **旧信号路由无效** - cookbook A% 95% 应<10%，全部重跑

---

## 🔍 QC 验证

**信号路由 QC**: cookbook A% <10%，工程书 40-70%

**Skill 提取 QC**: 检查 `results.jsonl` 错误率和 `_run.log` Summary

---

*以上规则永久遵守，知识永久掌握。*
