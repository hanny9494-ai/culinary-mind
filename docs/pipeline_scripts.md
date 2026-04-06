# Pipeline 脚本清单

> CC Lead 维护，2026-03-26
> 所有脚本在 ~/culinary-engine/scripts/

---

## 当前在用

### L0 蒸馏 Pipeline（新书标准流程）

```
PDF → flash_ocr_dashscope.py → raw_merged.md
    → stage1_pipeline.py --start-step 4 (2b切分)
    → stage1_pipeline.py Step5 (9b标注 chunk_type+topics)
    → stage4_open_extract.py (Phase A 过滤 + Phase B Opus提取)
    → stage4_dedup.py (embedding去重)
    → stage4_quality.py (质控)
```

| 脚本 | 功能 | 参数 | 输入 | 输出 |
|---|---|---|---|---|
| `flash_ocr_dashscope.py` | flash OCR (DashScope qwen3.5-flash) | `--pdf PDF --pages-json OUT` | source_converted.pdf | ocr/vlm_ocr_pages.json, vlm_ocr_merged.md |
| `stage1_pipeline.py` | Stage1 完整流程 (Step0-5) | `--book-id ID --config api.yaml --books books.yaml --toc mc_toc.json --output-dir DIR [--start-step N]` | raw_merged.md 或 PDF | chunks_raw.json, chunks_smart.json |
| `stage4_open_extract.py` | Stage4 开放提取 | `--book-id ID --config api.yaml [--phase all/a-only/b-only] --resume` | chunks_smart.json | stage4_filter.jsonl, stage4_raw.jsonl |
| `stage4_dedup.py` | Stage4 去重 | `--open-principles FILE` | stage4_raw.jsonl | l0_principles_dedup.jsonl |
| `stage4_quality.py` | Stage4 质控 | `--input FILE --chunks FILE --output FILE` | dedup后的 JSONL | l0_principles_open.jsonl |

### Stage1 步骤详解

| Step | 功能 | 工具 | 可跳过 |
|---|---|---|---|
| 0 | epub → PDF (Calibre) | ebook-convert | PDF书跳过 |
| 1 | MinerU OCR | MinerU API | **新书不用，用 flash OCR 替代** |
| 2 | flash Vision 补充 | DashScope qwen-vl | **新书不用** |
| 3 | Merge (MinerU + Vision) | 本地 | **新书不用，直接用 OCR md** |
| 4 | 2b 切分 | Ollama qwen3.5:2b | 必跑 |
| 5 | 9b 标注 (chunk_type + topics) | Ollama qwen3.5:9b | 必跑 |

**新书直接 `--start-step 4`，跳过 Step 0-3。**

### 其他在用脚本

| 脚本 | 功能 | 用途 |
|---|---|---|
| `stage2_match.py` | 题目-Chunk 语义匹配 | 薄弱域定向补题（L0全量完成后用） |
| `stage3_distill.py` | 306题蒸馏 | 薄弱域定向补题（L0全量完成后用） |
| `stage3b_causal.py` | 因果链拆分 | Stage3 后处理 |
| `stage5_recipe_extract.py` | 食谱结构提取 (L2b) | qwen3.5-flash 提取 ISA-88 JSON |
| `scan_low_hit.py` | 薄弱域扫描 | 找 17 域中命中率低的域 |
| `l2a_pilot_test.py` | L2a 食材采集 | Gemini search grounding |
| `run_book.py` | 单本书完整 pipeline | 封装 stage1→stage4 |

### 基础设施脚本

| 脚本 | 功能 |
|---|---|
| `ccs_web.py` | CC Switch Web UI (port 7777) |
| `reorganize_output.py` | 整理 output 目录结构 |

---

## 废弃/待确认

| 脚本 | 状态 | 原因 |
|---|---|---|
| `stage1_serial_runner.py` | ⚠️ 不可靠 | 多本书串行，经常跑完一本就断，不能自动接下一本 |
| `stage1_parallel_annotate.py` | ⚠️ 可能废弃 | 并行标注，被 stage1_pipeline.py Step5 替代？ |
| `fill_pending_parts_with_paddle.py` | ❓ 待确认 | 用 PaddleOCR 补缺失页面？ |

---

## 新书 vs 旧书 Pipeline 对比

| 阶段 | 旧书（MinerU 流程） | 新书（flash OCR 流程） |
|---|---|---|
| OCR | MinerU API (Step1) + Vision补充 (Step2) + Merge (Step3) | flash_ocr_dashscope.py → vlm_ocr_merged.md |
| 入口 | stage1_pipeline.py --start-step 0 | 复制 OCR md 到 raw_merged.md，然后 --start-step 4 |
| 切分 | Step4 (2b) | 同 |
| 标注 | Step5 (9b) | 同 |
| L0提取 | stage4_open_extract.py | 同 |

---

## config 文件

| 文件 | 用途 |
|---|---|
| `config/api.yaml` | API 端点和模型配置 |
| `config/books.yaml` | 书目注册表（所有书必须注册） |
| `config/mc_toc.json` | TOC 章节配置（Stage1 Step4 强制检查） |
| `config/domains_v2.json` | 17 域定义 |
