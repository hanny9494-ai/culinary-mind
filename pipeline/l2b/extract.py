#!/usr/bin/env python3
"""
L2b Recipe Structure Extraction
Uses local qwen3.5 (Ollama) to extract structured recipe JSON from chunk text.
"""
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from pydantic import BaseModel
    from typing import List, Optional
except ImportError:
    print("Installing pydantic...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "pydantic", "--break-system-packages"])
    from pydantic import BaseModel
    from typing import List, Optional

import importlib.util
import requests

# Cross-script import: load pipeline/prep/pipeline.py regardless of how this script is invoked
_REPO_ROOT = Path(__file__).resolve().parents[2]
_stage1_spec = importlib.util.spec_from_file_location("stage1_pipeline", _REPO_ROOT / "pipeline" / "prep" / "pipeline.py")
stage1 = importlib.util.module_from_spec(_stage1_spec)
_stage1_spec.loader.exec_module(stage1)

SESSION = requests.Session()
SESSION.trust_env = False

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "output"

def _resolve_chunks_path(book_subpath: str) -> str:
    """Try new prep/ path first, fall back to stage1/."""
    new = OUTPUT_ROOT / book_subpath.replace("/stage1/", "/prep/").replace("/stage1/stage1/", "/prep/")
    old = OUTPUT_ROOT / book_subpath
    return str(new) if new.exists() else str(old)

BATCH_BOOKS = {
    "ofc": _resolve_chunks_path("ofc/stage1/chunks_smart.json"),
    "mc_vol2": _resolve_chunks_path("mc/vol2/stage1/chunks_smart.json"),
    "mc_vol3": _resolve_chunks_path("mc/vol3/stage1/chunks_smart.json"),
    "mc_vol4": _resolve_chunks_path("mc/vol4/stage1/chunks_smart.json"),
    "neurogastronomy": _resolve_chunks_path("neurogastronomy/stage1/stage1/chunks_smart.json"),
    "mc_vol1": _resolve_chunks_path("mc_vol1/stage1/stage1/chunks_smart.json"),
    "salt_fat_acid_heat": _resolve_chunks_path("salt_fat_acid_heat/stage1/stage1/chunks_smart.json"),
    "ice_cream_flavor": _resolve_chunks_path("ice_cream_flavor/stage1/stage1/chunks_smart.json"),
    "mouthfeel": _resolve_chunks_path("mouthfeel/stage1/stage1/chunks_smart.json"),
    "flavorama": _resolve_chunks_path("flavorama/stage1/stage1/chunks_smart.json"),
    "science_of_spice": _resolve_chunks_path("science_of_spice/stage1/stage1/chunks_smart.json"),
    "professional_baking": _resolve_chunks_path("professional_baking/stage1/stage1/chunks_smart.json"),
}

COMPILED_MD_DIR = Path("/Users/jeff/Documents/厨书数据库（编译）")
L0_OUTPUT_ROOT = OUTPUT_ROOT
COMPILED_MD_FILES = [
    "Crave.md",
    "Eleven Madison Park The Next Chapter 紫色封面 .md",
    "F1749 Manresa.md",
    "F2986 Baltic.md",
    "Meat Illustrated A Foolproof Guide to Understanding and Cooking with Cuts of All Kinds.md",
    "Momofuku.md",
    "Organum Nature Texture Intensity Purity.md",
    "The Hand and Flowers Cookbook.md",
    "_OceanofPDF.com_Alinea_-_Grant_Achatz.md",
    "_OceanofPDF.com_Bouchon_-_Thomas_Keller.md",
    "_OceanofPDF.com_Core_-_Clare_Smyth.md",
    "_OceanofPDF.com_Daniel_My_French_Cuisine_-_Daniel_Boulud.md",
    "_OceanofPDF.com_Eleven_Madison_Park_The_Cookbook_-_Daniel_Humm_Will_Guidara.md",
    "_OceanofPDF.com_Japanese_Farm_Food_-_Nancy_Singleton_Hachisu.md",
    "_OceanofPDF.com_Relae_A_Book_of_Ideas_-_Christian_F_Puglisi.md",
    "_OceanofPDF.com_The_Everlasting_Meal_Cookbook_Leftovers_A-Z_-_Tamar_Adler.md",
    "dokumen.pub_the-whole-fish-cookbook-new-ways-to-cook-eat-and-think-9781743586631-1743586639.md",
    "the-french-laundry-cookbook-9781579651268-1579651267_compress.md",
]


class Ingredient(BaseModel):
    item: str
    qty: Optional[float] = None
    unit: Optional[str] = None
    note: Optional[str] = None


class Step(BaseModel):
    order: int
    text: str
    action: str
    duration_min: Optional[int] = None
    temp_c: Optional[int] = None


class SubRecipeRef(BaseModel):
    ref_name: str
    ref_type: str
    ref_page: Optional[int] = None


class Recipe(BaseModel):
    recipe_type: str
    name: str
    yield_text: Optional[str] = None
    ingredients: List[Ingredient] = []
    steps: List[Step] = []
    equipment: List[str] = []
    sub_recipe_refs: List[SubRecipeRef] = []
    notes: Optional[str] = None


class ExtractionResult(BaseModel):
    recipes: List[Recipe] = []


SYSTEM_PROMPT = """你是专业烹饪配方结构化提取专家。从文本中提取所有食谱和子配方。

严格按JSON格式输出。如果文本中没有食谱，返回 {"recipes": []}

### 提取规则

1. 食材提取：
   - item: 食材名称（保留原文语言）
   - qty: 数字（"to taste"或无量 → null）
   - unit: 单位（g/mL/oz/lb/tsp/tbsp/cup/个/只/条，无单位 → null）
   - note: 额外说明（如"drained", "room temperature", "38% milkfat"）

2. 步骤提取：
   - order: 序号
   - text: 完整步骤文字（保留原文）
   - action: 核心动作词（mix/bake/ferment/fold/chill/fry/boil/steam等）
   - duration_min: 时间（分钟，没有明确时间 → null）
   - temp_c: 温度摄氏度（华氏自动转换，没有 → null）

3. 子配方引用（关键）：
   识别以下三种引用模式：

   模式A — 页码引用：
     "Classic Puff Pastry (p. 318)" 或 "see page 535"
     → ref_type: "page_ref", ref_name: "Classic Puff Pastry", ref_page: 318

   模式B — 同文内联定义：
     同一段文本中定义了多个组件（如独立的CARDAMOM OIL段）
     → 每个组件提取为独立的子配方
     → 主配方的 sub_recipe_refs 引用组件名
     → ref_type: "inline_def"

   模式C — 名称引用（无页码）：
     "use the chicken stock" 或 "the ramen broth"
     → ref_type: "name_ref", ref_name: "chicken stock", ref_page: null

4. 主配方 vs 子配方判断：
   - 有"TO PLATE"/"TO FINISH"/"ASSEMBLY"段 → 这是主配方
   - 有独立食材表但被主配方引用 → 这是子配方
   - 有"Basic Recipe"/"Foundation"标记 → 这是子配方

### 输出JSON格式

{
  "recipes": [
    {
      "recipe_type": "main" 或 "sub_recipe",
      "name": "食谱名称",
      "yield_text": "产量（原文）",
      "ingredients": [
        {"item": "bread flour", "qty": 1000, "unit": "g", "note": null}
      ],
      "steps": [
        {"order": 1, "text": "完整步骤文字", "action": "mix", "duration_min": 20, "temp_c": null}
      ],
      "equipment": ["stand mixer", "sheet pan"],
      "sub_recipe_refs": [
        {"ref_name": "Classic Puff Pastry", "ref_type": "page_ref", "ref_page": 318}
      ],
      "notes": null
    }
  ]
}

### 关键约束
- 华氏温度必须转为摄氏度（F→C），保留整数
- 一段文本可能包含多个食谱（主+子），全部提取
- 子配方如果在同一文本中有完整定义，同时提取为独立 recipe_type: "sub_recipe"
- 纯叙事没有可提取配方结构 → 返回 {"recipes": []}
- 不要编造文本中没有的信息
- 只输出JSON，不要输出任何其他文字"""

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


def call_ollama(text, model="qwen3.5:latest"):
    resp = SESSION.post(
        "http://localhost:11434/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"提取以下文本中的食谱：\n\n{text}"},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.1, "num_predict": 4096},
        },
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def call_dashscope(text, model="qwen3.5-flash"):
    import httpx
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        http_client=httpx.Client(trust_env=False),
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"提取以下文本中的食谱：\n\n{text}"},
        ],
        temperature=0.1,
        max_tokens=4096,
        extra_body={"enable_thinking": False},
    )
    return resp.choices[0].message.content


def call_llm(text, model):
    if "flash" in model or "plus" in model:
        return call_dashscope(text, model)
    return call_ollama(text, model)


def extract_json_block(raw_text):
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)

    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return None, "No JSON found in response"
    return text[start:end], None


def parse_response(raw_text):
    json_str, error = extract_json_block(raw_text)
    if error:
        return None, error

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        return None, f"JSON parse error: {exc}"

    try:
        result = ExtractionResult(**data)
        return result, None
    except Exception as exc:
        return None, f"Pydantic validation error: {exc}"


def extract_recipe(text, model="qwen3.5:latest"):
    for attempt in range(3):
        try:
            start = time.time()
            raw = call_llm(text, model)
            elapsed = time.time() - start

            result, error = parse_response(raw)

            if result is not None:
                return result, elapsed, None

            if attempt < 2:
                print(f"    Attempt {attempt + 1} failed: {error}, retrying...")
                continue
            return None, elapsed, error
        except Exception as exc:
            if attempt < 2:
                print(f"    Attempt {attempt + 1} exception: {exc}, retrying...")
                continue
            return None, 0, str(exc)


def normalize_compiled_md_book_id(filename):
    book_id = filename
    if book_id.lower().endswith(".md"):
        book_id = book_id[:-3]
    if book_id.startswith("_OceanofPDF.com_"):
        book_id = book_id[len("_OceanofPDF.com_") :]
    book_id = book_id.replace(" ", "_").lower()
    return book_id[:40]


def prepare_compiled_md_sources(md_dir=COMPILED_MD_DIR, output_root=L0_OUTPUT_ROOT):
    prepared = []
    for md_name in COMPILED_MD_FILES:
        source = Path(md_dir) / md_name
        if not source.exists():
            print(f"[warn] missing compiled md: {source}")
            continue
        book_id = normalize_compiled_md_book_id(md_name)
        prep_dir = Path(output_root) / book_id / "prep"
        prep_dir.mkdir(parents=True, exist_ok=True)
        target = prep_dir / "raw_merged.md"
        if not target.exists():
            # Fall back to old stage1 location
            stage1_target = Path(output_root) / book_id / "stage1" / "raw_merged.md"
            if stage1_target.exists():
                shutil.copyfile(stage1_target, target)
            else:
                shutil.copyfile(source, target)
            print(f"[prep] copied {md_name} -> {prep_dir}")
        prepared.append((book_id, target))
    return prepared


def chunk_compiled_md_books(output_root=L0_OUTPUT_ROOT, split_model="qwen3.5:2b"):
    split_count = 0
    stage1.configure_ollama({"url": "http://localhost:11434", "options": {"think": False}})
    for md_name in COMPILED_MD_FILES:
        book_id = normalize_compiled_md_book_id(md_name)
        prep_dir = Path(output_root) / book_id / "prep"
        stage1_dir = Path(output_root) / book_id / "stage1"
        # Try new path first, fall back to old
        if (prep_dir / "raw_merged.md").exists():
            work_dir = prep_dir
        elif (stage1_dir / "raw_merged.md").exists():
            work_dir = stage1_dir
        else:
            continue
        raw_merged = work_dir / "raw_merged.md"
        chunks_raw = work_dir / "chunks_raw.json"
        if not raw_merged.exists() or chunks_raw.exists():
            continue

        text = raw_merged.read_text(encoding="utf-8")
        text = stage1.clean_merged_text_for_chunking(
            stage1.BookSpec(book_id=book_id, title=book_id, path=raw_merged, file_type="md"),
            text,
        )
        chapter = stage1.Chapter(
            chapter_num=1,
            chapter_title=book_id,
            chapter_start=book_id,
            chapter_end="END",
            text=text,
        )
        chunk_texts = stage1.split_chapter_with_model(
            stage1.BookSpec(book_id=book_id, title=book_id, path=raw_merged, file_type="md"),
            chapter,
            split_model,
            False,
        )
        payload = []
        for idx, chunk_text in enumerate(chunk_texts):
            payload.append(
                {
                    "chunk_idx": idx,
                    "full_text": chunk_text,
                    "chapter_num": 1,
                    "chapter_title": book_id,
                    "chapter_start": book_id,
                    "chapter_end": "END",
                }
            )
        chunks_raw.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (work_dir / "step4_quality.json").write_text(
            json.dumps(stage1.summarize_step4_chunks(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[chunk] {book_id}: {len(payload)} chunks")
        split_count += 1
    return split_count


def create_smart_chunks_from_raw(output_root=L0_OUTPUT_ROOT):
    created = 0
    # Search both new and old paths
    raw_paths = list(Path(output_root).glob("*/prep/chunks_raw.json")) + list(Path(output_root).glob("*/stage1/chunks_raw.json"))
    for chunks_raw_path in raw_paths:
        smart_path = chunks_raw_path.with_name("chunks_smart.json")
        if smart_path.exists():
            continue
        chunks = json.loads(chunks_raw_path.read_text(encoding="utf-8"))
        source_book = chunks_raw_path.parent.parent.name
        smart = []
        for i, chunk in enumerate(chunks):
            smart.append(
                {
                    "chunk_idx": int(chunk.get("chunk_idx", i)),
                    "full_text": chunk.get("full_text", chunk.get("text", "")),
                    "chapter_num": chunk.get("chapter_num"),
                    "chapter_title": chunk.get("chapter_title"),
                    "chapter_start": chunk.get("chapter_start"),
                    "chapter_end": chunk.get("chapter_end"),
                    "source_book": source_book,
                    "summary": None,
                    "topics": [],
                    "chunk_type": None,
                }
            )
        smart_path.write_text(json.dumps(smart, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[smart] {source_book}: {len(smart)} chunks")
        created += 1
    return created


def discover_pending_stage5_books(output_root=L0_OUTPUT_ROOT, stage5_root=Path("output/recipes")):
    discovered = {}
    for book_id, chunks_path in BATCH_BOOKS.items():
        discovered[book_id] = Path(chunks_path)

    for smart_path in list(Path(output_root).glob("*/prep/chunks_smart.json")) + list(Path(output_root).glob("*/stage1/chunks_smart.json")):
        book_id = smart_path.parent.parent.name
        discovered.setdefault(book_id, smart_path)

    pending = []
    first_wave_order = list(BATCH_BOOKS.keys())
    for book_id in first_wave_order:
        chunks_path = discovered.get(book_id)
        if chunks_path is None:
            continue
        stats_path = Path(stage5_root) / book_id / "stats.json"
        if stats_path.exists():
            continue
        pending.append((book_id, Path(chunks_path)))

    for book_id in sorted(discovered):
        if book_id in BATCH_BOOKS:
            continue
        chunks_path = Path(discovered[book_id])
        stats_path = Path(stage5_root) / book_id / "stats.json"
        if stats_path.exists():
            continue
        pending.append((book_id, chunks_path))
    return pending


def write_batch_catalog(pending_books, path=Path("config/recipes_all.json")):
    payload = [{"book_id": book_id, "chunks_path": str(chunks_path)} for book_id, chunks_path in pending_books]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def process_book(book_id, chunks_path, output_dir, model="qwen3.5-flash"):
    from openai import OpenAI
    import httpx

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(chunks_path, encoding="utf-8") as handle:
        chunks = json.load(handle)

    print(f"\n=== {book_id}: {len(chunks)} chunks ===")

    progress_file = output_dir / "progress.json"
    done_ids = set()
    if progress_file.exists():
        done_ids = set(json.loads(progress_file.read_text()))
        print(f"  Resuming: {len(done_ids)} already done")

    result_file = output_dir / "stage5_results.jsonl"

    client = OpenAI(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        http_client=httpx.Client(trust_env=False),
    )

    stats = {
        "total": 0,
        "recipe": 0,
        "science": 0,
        "mixed": 0,
        "narrative": 0,
        "recipes_found": 0,
        "errors": 0,
    }

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
                print(f"  [{i + 1}/{len(chunks)}] WARN: {error}")

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

            with open(result_file, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")

            done_ids.add(str(chunk_id))
            progress_file.write_text(json.dumps(sorted(done_ids)))

            status = "📋" if n_recipes > 0 else "·"
            if (i + 1) % 50 == 0 or n_recipes > 0:
                print(f"  [{i + 1}/{len(chunks)}] {status} {chunk_type} ({n_recipes} recipes)")

        except Exception as exc:
            stats["errors"] += 1
            print(f"  [{i + 1}/{len(chunks)}] ERROR: {exc}")
            time.sleep(2)
            continue

        time.sleep(0.3)

    stats_file = output_dir / "stats.json"
    stats_file.write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"\n  Done: {stats}")


def process_pending_books(pending, output_root, model, concurrency=1):
    if not pending:
        return
    if concurrency <= 1:
        for book_id, chunks_path in pending:
            process_book(book_id, chunks_path, Path(output_root) / book_id, model=model)
        return

    workers = min(concurrency, len(pending))
    print(f"Running with concurrency={workers}")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_book, book_id, chunks_path, Path(output_root) / book_id, model): book_id
            for book_id, chunks_path in pending
        }
        for future in as_completed(futures):
            book_id = futures[future]
            future.result()
            print(f"[done] {book_id}")


def run_batch(model="qwen3.5-flash", output_root=Path("output/recipes"), selected_books=None, concurrency=1):
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    books = selected_books or list(BATCH_BOOKS.keys())
    pending = [(book_id, Path(BATCH_BOOKS[book_id])) for book_id in books]
    process_pending_books(pending, output_root, model, concurrency=concurrency)


def run_batch_catalog(model="qwen3.5-flash", output_root=Path("output/recipes"), selected_books=None, concurrency=1):
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    pending = discover_pending_stage5_books(stage5_root=output_root)
    if selected_books:
        selected = set(selected_books)
        pending = [(book_id, chunks_path) for book_id, chunks_path in pending if book_id in selected]

    write_batch_catalog(pending)
    print(f"Pending books: {len(pending)}")
    for book_id, chunks_path in pending:
        print(f"  {book_id}: {chunks_path}")
    process_pending_books(pending, output_root, model, concurrency=concurrency)


def run_batch_auto(
    model="qwen3.5-flash",
    output_root=Path("output/recipes"),
    scan_interval_hours=2,
    concurrency=1,
):
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    while True:
        print("\n=== Wave Prep ===")
        prepared = prepare_compiled_md_sources()
        split_count = chunk_compiled_md_books()
        smart_count = create_smart_chunks_from_raw()
        print(
            f"  compiled_md_prepared={len(prepared)} chunked={split_count} smart_created={smart_count}"
        )

        pending = discover_pending_stage5_books(stage5_root=output_root)
        catalog_path = write_batch_catalog(pending)
        print(f"  catalog={catalog_path} pending_books={len(pending)}")

        if pending:
            for book_id, chunks_path in pending:
                print(f"  pending: {book_id}")
            process_pending_books(pending, output_root, model, concurrency=concurrency)
            continue

        sleep_seconds = max(1, int(scan_interval_hours * 3600))
        print(f"No pending books. Sleeping for {scan_interval_hours} hours...")
        time.sleep(sleep_seconds)


TEST_CASES = {
    "test1_professional_baking": {
        "description": "Structured format: ingredient table + numbered steps + page refs",
        "expected": "1 main (Praline Millefeuille) + 1 sub (Praline Pailletine) + page_refs to p.318, p.535",
        "text": """PRALINE MILLEFEUILLE
Yield: one pastry, about 6 × 10 in. (15 × 25 cm) and weighing about 2½ lb (1200 g)
Ingredients U.S. Metric
Classic Puff Pastry (p. 318) 1 lb 4 oz 630 g
Confectioners' sugar as needed as needed
Praline Cream (p. 535) 1 lb 500 g
Praline Pailletine (recipe below) 5 oz 150 g
Garnish
Caramelized nuts as desired as desired
PROCEDURE
1. Roll out the puff pastry to a rectangle about 13 × 20 in. (33 × 52 cm). Place on a sheet pan lined with parchment paper. Dock the dough and refrigerate for 20 minutes.
2. Bake at 400°F (200°C). When the pastry is about four-fifths baked, remove from the oven and dredge generously with confectioners' sugar.
3. Raise the oven heat to 475°F (240°C). Return the pastry to the oven and bake until the sugar caramelizes, 2–3 minutes.
4. Remove from the oven and let cool.
5. With a serrated knife, trim the edges of the pastry so they are straight and square. Then cut crosswise into 3 equal rectangles.
6. Spread one of the pastry rectangles with a layer of praline cream 5/8 in. (1.5 cm) thick. Cover with a second layer of pastry.
7. Top with the praline pailletine and then another layer of the praline cream.
8. Cover with the third layer of pastry.
9. Decorate the top as desired with caramelized nuts.

PRALINE PAILLETINE
Ingredients U.S. Metric
Milk chocolate couverture 1 oz 25 g
Cocoa butter 0.25 oz 6 g
Almond-hazelnut praline paste 4 oz 100 g
Ice cream wafers (pailletine), crushed 1 oz 25 g
Total weight: 6 oz 156 g
PROCEDURE
1. Melt the chocolate and cocoa butter in a bowl over a hot-water bath.
2. Mix in the praline paste.
3. Add the crushed wafers and mix in.
4. To use in Praline Millefeuille (above), spread on a sheet pan to a thickness of about 1/4 in. (5 mm), making a rectangle about 6 × 10 in. (15 × 25 cm).
5. Place in the refrigerator to harden.""",
    },
    "test2_noma": {
        "description": "Multi-component format: 4 sub-recipes + TO PLATE assembly",
        "expected": "1 main (Cardamom-Scented Candle / TO PLATE) + 4 subs (Candle, Oil, Wick, Perfume), all inline_def",
        "text": """CARDAMOM-SAFFRON CANDLE
100 g sugar
175 g glucose syrup
375 mL cream (38% milkfat)
35 g cardamom pods
0.3 g saffron
90 g butter
9 g salt
7 mL white wine vinegar
0.7% agar
Liquid nitrogen
Lightly toast the cardamom pods and the saffron in a pan. Once toasted, break them apart with a mortar and pestle and toss them in with the cream. Bring to the fermentation lab to sonicate the mixture together at 30% amplitude for 5 minutes while stirring frequently over ice. Once sonicated, strain the cream with a fine-mesh nylon sieve and discard the pods and the saffron.
From there, place the sugar, salt, glucose, and 300 mL of the infused cream in a pot. Cook the mixture until it reaches 108°C on a candy thermometer. While it's cooking, melt the butter in another pot on the side. Once the caramel is up to temperature, add the melted butter and vinegar. Return the mixture to the heat and cook it again until it reaches 114°C. Once up to temperature, remove it from the heat, and wait until the mixture cools down to 70°C. Weigh the mixture to calculate the amount of agar necessary, then mix in the agar and the remaining 75 g cream. Heat the mixture once more to activate the agar.
When shaping the candles, keep the caramel mix warm on the stove for ease of processing. In a Styrofoam ice cream container fill up 4 cm diameter silicone molds with liquid nitrogen and wait until they are frozen. Once frozen, pour the nitro out of the molds and into the Styrofoam container so that the molds are now surrounded by the nitro. Fill up the mold with the warm caramel and wait 10 to 15 seconds. Once the caramel begins to be set, remove the mold from the Styrofoam, flip it upside down, and rest it on a skinny yogurt cup so that the caramel starts to drip down from the mold into the yogurt cup. Move this dripping caramel immediately to the blast freezer to set. Once it is completely set, remove the candle from the mold and make a small hole for the wick in the center of the candle with a metal skewer. Keep the candle in a 1 L container in the blast freezer.

CARDAMOM OIL
300 g grapeseed oil
100 g cardamom pods
Combine the cardamom pods and the oil in a pot. Over low heat, infuse the cardamom and oil for 30 minutes. Once infused, remove from the stove, and lightly blend it with an immersion blender. Once blended, cover the pot with foil and rest for 1 hour. Once rested, strain the oil through a fine-mesh nylon sieve. Reserve the oil in the fridge and discard the cardamom.

WALNUT WICK
Walnuts
Find the biggest dried walnuts you can possibly find. Set a combi oven to 90°C dry heat, with 70% humidity (30% fan). Lay the walnuts in one flat layer in the oven for a few minutes. Once warmed, retrieve the walnuts, and shave the skin off using a very sharp knife. Split the shaved walnuts in half and trim the edges. From each half of the walnut, you should be able to get 2 wicks cut approximately into the shape and size of matchsticks—approximately 3 mm thick. Reserve the walnut wicks in an airtight container until service.

CARDAMOM PERFUME
200 mL filtered water
35 g cardamom pods
Combine the cardamom and the water in a container. Using an immersion blender, blend till the cardamom is broken apart and infused into the water. Strain the mixture through a fine-mesh nylon sieve and reserve in a spray bottle.

TO PLATE
Cardamom Oil
Cardamom-Saffron Candle
Walnut Wick
Cardamom Perfume
Keep the candles in the blast freezer at -30°C. Brush the plates with a bit of cardamom oil (to prevent the candle from sticking to the plate) and keep them in the blast freezer. When called out, put the candle on the cold plate, spray it once with cardamom perfume, and place the wick in the candle. Double-check that the candle is not too frozen. Light the wick just before leaving the kitchen to walk to the table.""",
    },
    "test3_narrative": {
        "description": "Narrative format: story mixed with recipe, implicit references",
        "expected": "Possibly empty or partial extraction. name_ref to 'ramen broth' if detected",
        "text": """bo ssäm SERVES 6 TO 8
Our bo ssäm was a long time in the making before it showed up on the menu. I'd had an inkling for years it would be a good idea—bo ssäm is a supercommon dish in Korean restaurants, though the ingredients and cooking that go into it are frequently an afterthought. The oysters are usually Gulf oysters from a bucket, the kind that are really only suited to frying; the pork is belly that's been boiled into submission. Almost every time I ate it at a restaurant, I'd think about how much better it would be if all the ingredients were awesome.
The first time we made one was for family meal back when we'd just started serving kimchi puree on our oysters at Noodle Bar. One of the new cooks was fucking up oysters left and right, so I made him shuck a few dozen perfectly, and then we ate them ssäm-style: wrapped up in lettuce with rice, kimchi, and some shredded pork shoulder that was otherwise destined for the ramen bowl. (The shoulder in our bo ssäm is, essentially, the same shoulder we put in the soup at Noodle Bar.)""",
    },
}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--batch":
        model = sys.argv[2] if len(sys.argv) > 2 else "qwen3.5-flash"
        output_root = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("output/recipes")
        selected_books = sys.argv[4:] if len(sys.argv) > 4 else None
        concurrency = 1
        print(f"Batch model: {model}")
        print(f"Batch output: {output_root}")
        if selected_books:
            print(f"Books: {selected_books}")
        run_batch(model=model, output_root=output_root, selected_books=selected_books, concurrency=concurrency)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--batch-all":
        model = sys.argv[2] if len(sys.argv) > 2 else "qwen3.5-flash"
        output_root = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("output/recipes")
        concurrency = int(sys.argv[4]) if len(sys.argv) > 4 else 1
        selected_books = sys.argv[5:] if len(sys.argv) > 5 else None
        print(f"Batch-all model: {model}")
        print(f"Batch-all output: {output_root}")
        print(f"Batch-all concurrency: {concurrency}")
        run_batch_catalog(model=model, output_root=output_root, selected_books=selected_books, concurrency=concurrency)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--batch-auto":
        model = sys.argv[2] if len(sys.argv) > 2 else "qwen3.5-flash"
        output_root = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("output/recipes")
        scan_interval_hours = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
        concurrency = int(sys.argv[5]) if len(sys.argv) > 5 else 1
        print(f"Batch-auto model: {model}")
        print(f"Batch-auto output: {output_root}")
        print(f"Batch-auto scan interval hours: {scan_interval_hours}")
        print(f"Batch-auto concurrency: {concurrency}")
        run_batch_auto(model=model, output_root=output_root, scan_interval_hours=scan_interval_hours, concurrency=concurrency)
        return

    model = sys.argv[1] if len(sys.argv) > 1 else "qwen3.5:latest"
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output/recipes_pilot")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Model: {model}")
    print(f"Output: {output_dir}")
    print(f"Test cases: {len(TEST_CASES)}")
    print()

    results = {}

    for test_id, test in TEST_CASES.items():
        print(f"=== {test_id} ===")
        print(f"  Description: {test['description']}")
        print(f"  Expected: {test['expected']}")
        print(f"  Text length: {len(test['text'])} chars")
        print("  Extracting...", end=" ", flush=True)

        result, elapsed, error = extract_recipe(test["text"], model)

        if error:
            print(f"FAILED ({elapsed:.1f}s): {error}")
            results[test_id] = {"status": "failed", "error": error, "elapsed": elapsed}
        else:
            n_recipes = len(result.recipes)
            print(f"OK ({elapsed:.1f}s)")
            print(f"  Recipes found: {n_recipes}")
            for recipe in result.recipes:
                print(f"    [{recipe.recipe_type}] {recipe.name}")
                print(
                    f"      ingredients: {len(recipe.ingredients)}, steps: {len(recipe.steps)}, equipment: {len(recipe.equipment)}"
                )
                if recipe.sub_recipe_refs:
                    refs = [f"{ref.ref_name}({ref.ref_type})" for ref in recipe.sub_recipe_refs]
                    print(f"      refs: {refs}")

            results[test_id] = {
                "status": "ok",
                "elapsed": elapsed,
                "n_recipes": n_recipes,
                "recipes": [recipe.model_dump() for recipe in result.recipes],
                "expected": test["expected"],
            }

        with open(output_dir / f"{test_id}.json", "w", encoding="utf-8") as handle:
            json.dump(results[test_id], handle, ensure_ascii=False, indent=2)

        print()

    with open(output_dir / "pilot_summary.json", "w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for test_id, result in results.items():
        status = result["status"]
        elapsed = result.get("elapsed", 0)
        if status == "ok":
            print(f"  {test_id}: ✅ {result['n_recipes']} recipes ({elapsed:.1f}s)")
        else:
            print(f"  {test_id}: ❌ {result.get('error', 'unknown')} ({elapsed:.1f}s)")

    print()
    print("=== QUALITY CHECK ===")
    print()
    print("For Jeff to review:")
    print("  test1: Should have 1 main + 1 sub, page_refs to p.318/p.535")
    print("  test2: Should have 1 main + 4 subs, all inline_def")
    print("  test3: Should be empty or partial (narrative text)")
    print()
    print(f"Full results saved to: {output_dir}/")


if __name__ == "__main__":
    main()
