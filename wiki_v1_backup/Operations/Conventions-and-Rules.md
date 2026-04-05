---
last_updated: '2026-04-04T16:09:15.088126+00:00'
mention_count: 5.0
related:
- '[[STATUS.md]]'
- '[[api_routing.md]]'
sources:
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
status: active
title: Operations  —  Conventions and Rules
---

# Operations  —  Conventions and Rules


## Updates (2026-04-04)
- STATUS.md is maintained exclusively by the mother/lead conversation; agents are prohibited from modifying it
- Agent environment setup requires: export no_proxy=localhost,127.0.0.1 before running agent-select.sh; zsh compdef errors are non-fatal

## Updates (2026-04-04)
- 所有脚本必须设置 trust_env=False 或清除代理环境变量，因为本机 ~/.zshrc 配置了 SOCKS5 代理 127.0.0.1:7890 会拦截所有 HTTP 请求
- API 路由规则：qwen* 模型走 DashScope，claude* 模型走灵雅代理（L0_API_ENDPOINT+L0_API_KEY），本地模型走 Ollama localhost:11434，gemini* 模型走 Google API 或灵雅代理
