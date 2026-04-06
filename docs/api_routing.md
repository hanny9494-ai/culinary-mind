# API 路由完整参考

> 生成时间: 2026-03-30
> 所有脚本必须 trust_env=False 绕过本机代理 127.0.0.1:7890

## 快速查找表

| 用途 | API | 模型 | 脚本 | 环境变量 |
|------|-----|------|------|--------|
| OCR 识别 | DashScope | qwen3.5-flash | flash_ocr_dashscope.py | DASHSCOPE_API_KEY |
| 文本切分 | Ollama | qwen3.5:2b | stage1_pipeline.py | - |
| 内容标注 | Ollama | qwen3.5:9b | stage1_pipeline.py | - |
| 向量嵌入 | Gemini | gemini-embedding-2 | stage2_match.py | GEMINI_API_KEY |
| 科学蒸馏 | 灵雅→Claude | claude-opus-4-6 | stage3_distill.py | L0_API_* |
| Stage4 预过滤 | Ollama/DashScope | 27b/flash | stage4_open_extract.py | DASHSCOPE_API_KEY |
| Stage4 核心提取 | 灵雅→Claude | claude-opus-4-6 | stage4_open_extract.py | L0_API_* |
| 去重向量化 | Ollama | qwen3-embedding:8b | stage4_dedup.py | - |
| 食谱结构化 | DashScope | qwen3.5-flash | stage5_recipe_extract.py | DASHSCOPE_API_KEY |
| 食材归一化 | DashScope | qwen3.5-flash | l2a_normalize.py | DASHSCOPE_API_KEY |
| L2a Gemini 蒸馏 | Gemini | gemini-3-flash | l2a_pilot_test.py | GEMINI_API_KEY |

## API 提供商

| 提供商 | Base URL | 认证 | 并发 |
|--------|----------|------|------|
| DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` | DASHSCOPE_API_KEY | 3-5 |
| 灵雅代理 | `${L0_API_ENDPOINT}/v1` | L0_API_KEY | 1-3 |
| Ollama | `http://localhost:11434` | 无 | OLLAMA_MAX_LOADED_MODELS=3 |
| Gemini | googleapis 或灵雅代理 | GEMINI_API_KEY | 1(批量) |
| MinerU | `https://mineru.net/api/v4` | MINERU_API_KEY | 1 |

## 路由规则

```
qwen* 模型     → DashScope (DASHSCOPE_API_KEY)
claude* 模型   → 灵雅代理 (L0_API_ENDPOINT + L0_API_KEY)
本地模型        → Ollama localhost:11434
gemini* 模型   → Google API 或灵雅代理 (GEMINI_API_KEY)
```

## 代理注意事项

本机有 SOCKS5 代理 `127.0.0.1:7890`（~/.zshrc 设置），会拦截所有 HTTP 请求。

**必须在所有脚本中：**
```python
# 方法1: requests
session = requests.Session()
session.trust_env = False

# 方法2: 脚本开头清除环境变量
import os
for k in ("http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY","all_proxy","ALL_PROXY"):
    os.environ.pop(k, None)
```

**终端手动运行脚本时：**
```bash
unset http_proxy https_proxy all_proxy
python3 scripts/xxx.py
```

## 环境变量

| 变量 | 说明 | 必需 |
|------|------|------|
| DASHSCOPE_API_KEY | 阿里云 DashScope | ✅ |
| L0_API_ENDPOINT | 灵雅代理 (https://api.lingyaai.cn) | ✅ |
| L0_API_KEY | 灵雅代理密钥 | ✅ |
| GEMINI_API_KEY | Google Gemini | ✅ |
| MINERU_API_KEY | MinerU PDF 解析 | 可选 |

真实值在 ~/.zshrc，不入库。

## 成本参考

| 模型 | 输入 (¥/百万token) | 输出 (¥/百万token) |
|------|---|---|
| qwen3.5-flash | 0.2 | 0.6 |
| qwen3.5-plus | 0.8 | 2.0 |
| claude-opus-4-6 | 5.0 | 25.0 |
| claude-sonnet-4-6 | 1.5 | 7.5 |
| Ollama 本地 | 0 | 0 |
