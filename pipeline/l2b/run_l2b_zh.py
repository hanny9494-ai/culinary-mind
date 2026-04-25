#!/usr/bin/env python3
"""run_l2b_zh.py — 批量跑中文书 L2b 食谱提取 (Stage5, DashScope qwen3.5-flash)

Standalone runner — does NOT import extract.py (Python 3.14 importlib compat issue).
Replicates process_book() logic inline.

用法: caffeinate -s nohup python3 -u pipeline/l2b/run_l2b_zh.py > logs/run_l2b_zh.log 2>&1 &
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from openai import OpenAI

REPO = Path(__file__).resolve().parents[2]
os.chdir(REPO)

# No proxy
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)

# ── Prompt (copied from pipeline/l2b/extract.py COMBINED_PROMPT) ──────────────
COMBINED_PROMPT = """你是专业烹饪文本分析和配方提取专家。完成两个任务：

### 任务1：标注chunk_type和topics

chunk_type（必选其一）：
- science: 科学原理、机制解释、实验数据、参数讨论
- recipe: 配方、食材表、步骤说明
- mixed: 同时包含科学内容和配方
- narrative: 叙事、历史、个人故事、目录、前言、版权页

topics（从以下17域中选0-3个，如果内容不属于任何域则为空）：
protein_science, carbohydrate, lipid_science, fermentation,
food_safety, water_activity, enzyme, color_pigment,
equipment_physics, maillard_caramelization, oxidation_reduction,
salt_acid_chemistry, taste_perception, aroma_volatiles,
thermal_dynamics, mass_transfer, texture_rheology

### 任务2：如果chunk_type是recipe或mixed，提取结构化配方

食材提取规则：
- item: 食材名称（保留原文语言）
- qty: 数字（"to taste"或无量 → null）
- unit: 单位（g/mL/oz/lb/tsp/tbsp/cup，无单位 → null）
- note: 额外说明（如"drained", "38% milkfat"）

步骤提取规则：
- order: 序号
- text: 完整步骤文字（保留原文）
- action: 核心动作词（mix/bake/ferment/fold/chill/fry/boil/steam等）
- duration_min: 时间分钟（没有 → null）
- temp_c: 温度摄氏度（华氏自动转换，没有 → null）

子配方引用规则：
- 模式A页码引用："Classic Puff Pastry (p. 318)" → ref_type: "page_ref", ref_page: 318
- 模式B同文内联："CARDAMOM OIL"段独立定义 → ref_type: "inline_def"
- 模式C名称引用："use the chicken stock" → ref_type: "name_ref"

主配方 vs 子配方：有"TO PLATE"/"ASSEMBLY"段 → 主配方；被引用的独立配方 → 子配方

### 输出格式（严格JSON）

{
  "chunk_type": "recipe",
  "topics": ["fermentation", "protein_science"],
  "recipes": [
    {
      "recipe_type": "main",
      "name": "食谱名称",
      "yield_text": "产量原文",
      "ingredients": [
        {"item": "bread flour", "qty": 1000, "unit": "g", "note": null}
      ],
      "steps": [
        {"order": 1, "text": "步骤原文", "action": "mix", "duration_min": 20, "temp_c": null}
      ],
      "equipment": ["stand mixer"],
      "sub_recipe_refs": [
        {"ref_name": "Classic Puff Pastry", "ref_type": "page_ref", "ref_page": 318}
      ],
      "notes": null
    }
  ]
}

即使chunk_type是science或narrative，如果文本中包含配方、食谱、配料表、操作步骤，也必须提取到recipes数组中。只有确实没有任何食谱内容时才返回空数组。

### 关键约束
- 华氏温度必须转为摄氏度
- 一段文本可能包含多个食谱（主+子），全部提取
- 不要编造文本中没有的信息
- 只输出JSON"""

# ── 17 本中文书 ───────────────────────────────────────────────────────────────
ZH_BOOKS = [
    "shijing",
    "hk_yuecan_yanxi",
    "zhujixiaoguan_v6b",
    "zhongguo_caipu_guangdong",
    "guangdong_pengtiao_quanshu",
    "zhujixiaoguan_dimsim2",
    "zhongguo_yinshi_meixueshi",
    "chuantong_yc",
    "yuecan_zhenwei_meat",
    "zhujixiaoguan_4",
    "fenbuxiangjiena_yc",
    "zhujixiaoguan_3",
    "gufa_yc",
    "zhujixiaoguan_2",
    "zhujixiaoguan_6",
    "yuecan_wangliang",
    "xidage_xunwei_hk",
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def find_chunks_path(book_id: str) -> Path | None:
    """Find chunks_smart.json — check nested path prep/prep/ from previous run."""
    candidates = [
        REPO / f"output/{book_id}/prep/prep/chunks_smart.json",
        REPO / f"output/{book_id}/prep/chunks_smart.json",
        REPO / f"output/{book_id}/stage1/chunks_smart.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def extract_json_block(raw: str):
    """Extract JSON from LLM response (may have ```json ... ``` wrapper)."""
    # Try ```json block
    m = re.search(r"```json\s*([\s\S]+?)\s*```", raw)
    if m:
        return m.group(1), None
    # Try bare { ... }
    m = re.search(r"\{[\s\S]+\}", raw)
    if m:
        return m.group(0), None
    return None, f"No JSON found in: {raw[:100]}"


def process_book_inline(
    book_id: str,
    chunks_path: Path,
    output_dir: Path,
    model: str = "qwen3.5-flash",
) -> dict:
    """Process a single book: extract recipes from all chunks."""
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(chunks_path, encoding="utf-8") as fh:
        chunks = json.load(fh)

    log(f"  {book_id}: {len(chunks)} chunks")

    progress_file = output_dir / "progress.json"
    done_ids: set = set()
    if progress_file.exists():
        done_ids = set(json.loads(progress_file.read_text()))
        log(f"  Resuming: {len(done_ids)} already done")

    result_file = output_dir / "stage5_results.jsonl"

    client = OpenAI(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        http_client=httpx.Client(trust_env=False),
    )

    stats = {"total": 0, "recipe": 0, "science": 0, "mixed": 0, "narrative": 0,
             "recipes_found": 0, "errors": 0}

    with open(result_file, "a", encoding="utf-8") as out_fh:
        for i, chunk in enumerate(chunks):
            chunk_id = chunk.get("chunk_idx", i)
            if str(chunk_id) in done_ids:
                continue

            text = chunk.get("full_text", "")
            if len(text.strip()) < 20:
                continue

            stats["total"] += 1

            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": COMBINED_PROMPT},
                        {"role": "user", "content": f"分析以下文本：\n\n{text}"},
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                    extra_body={"enable_thinking": False},
                )
                raw = resp.choices[0].message.content or ""
                json_str, error = extract_json_block(raw)

                if json_str is not None:
                    data = json.loads(json_str)
                else:
                    data = {"chunk_type": "narrative", "topics": [], "recipes": []}
                    stats["errors"] += 1
                    if i < 5 or i % 50 == 0:
                        log(f"  [{i+1}/{len(chunks)}] WARN: {error}")

                chunk_type = data.get("chunk_type", "narrative")
                stats[chunk_type] = stats.get(chunk_type, 0) + 1
                n_recipes = len(data.get("recipes", []))
                stats["recipes_found"] += n_recipes

                result = {
                    "book_id": book_id,
                    "chunk_idx": chunk_id,
                    "chunk_type": chunk_type,
                    "topics": data.get("topics", []),
                    "recipes": data.get("recipes", []),
                }
                out_fh.write(json.dumps(result, ensure_ascii=False) + "\n")
                out_fh.flush()

                done_ids.add(str(chunk_id))
                progress_file.write_text(json.dumps(list(done_ids)))

                if (i + 1) % 20 == 0:
                    log(f"  [{i+1}/{len(chunks)}] recipes={stats['recipes_found']} errors={stats['errors']}")

            except Exception as e:
                stats["errors"] += 1
                log(f"  [{i+1}/{len(chunks)}] ERROR: {e}")
                time.sleep(2)

    return stats


def run_l2b(book_id: str) -> bool:
    chunks_path = find_chunks_path(book_id)
    if chunks_path is None:
        log(f"SKIP {book_id}: no chunks_smart.json")
        return False

    output_dir = REPO / f"output/{book_id}/l2b"
    progress_file = output_dir / "progress.json"

    n_chunks = len(json.loads(chunks_path.read_text()))

    # Resume check: if >99% done, skip
    if progress_file.exists():
        done_ids = json.loads(progress_file.read_text())
        if len(done_ids) >= n_chunks * 0.99:
            log(f"SKIP {book_id}: already done ({len(done_ids)}/{n_chunks})")
            return True

    log(f"START L2b: {book_id}")
    t0 = time.time()

    try:
        stats = process_book_inline(book_id, chunks_path, output_dir)
        elapsed = time.time() - t0
        log(f"DONE {book_id}: {stats['total']} processed, {stats['recipes_found']} recipes "
            f"(recipe={stats['recipe']} mixed={stats['mixed']} errors={stats['errors']}) "
            f"— {elapsed/60:.1f} min")
        return True
    except Exception as e:
        log(f"FAILED {book_id}: {e}")
        return False


if __name__ == "__main__":
    log(f"=== L2b recipe extraction for {len(ZH_BOOKS)} Chinese books ===")
    ok, skip, fail = 0, 0, 0
    for book_id in ZH_BOOKS:
        try:
            success = run_l2b(book_id)
        except Exception as e:
            log(f"ERROR {book_id}: {e}")
            success = False
        if success:
            ok += 1
        else:
            fail += 1
    log(f"=== Done: {ok} OK, {fail} failed ===")
