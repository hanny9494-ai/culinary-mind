#!/usr/bin/env python3
"""L2a 食材数据库 — test (5个) + pilot (75个) 两轮 Gemini 采集"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get(
    "GEMINI_L2A_KEY",
    "sk-IPQBLX1VUnIe4IOWTuSxXzFtRqQ1A5gIijjFXqfR89HTaTzn",
)
GEMINI_BASE_URL = os.environ.get(
    "GEMINI_BASE_URL",
    "https://api.lingyaai.cn/v1",
)
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview-search")

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_TEST = REPO_ROOT / "output" / "l2a" / "test"
OUTPUT_PILOT = REPO_ROOT / "output" / "l2a" / "pilot"

API_DELAY = 1.5
MAX_RETRIES = 3

TEST_INGREDIENTS = [
    ("poultry", "清远走地鸡"),
    ("beef", "和牛"),
    ("crustacean", "大闸蟹"),
    ("mushroom", "羊肚菌"),
    ("saltwater_fish", "金目鲷"),
]

PILOT_INGREDIENTS = {
    "beef":           ["和牛", "安格斯牛", "黄牛", "雪花牛", "草饲牛"],
    "pork":           ["黑猪", "伊比利亚猪", "土猪", "三元猪", "金华猪"],
    "lamb":           ["盐池滩羊", "苏尼特羊", "新西兰羊", "普罗旺斯羊", "崇明白山羊"],
    "poultry":        ["清远走地鸡", "布雷斯鸡", "三黄鸡", "北京鸭", "Moulard鸭"],
    "game":           ["乳鸽", "鹌鹑", "兔", "鹿", "野鸡"],
    "saltwater_fish": ["金目鲷", "比目鱼", "石斑", "黄鱼", "鲈鱼"],
    "freshwater_fish": ["鳜鱼", "淡水鲈鱼", "鲟鱼", "虹鳟", "鲤鱼"],
    "crustacean":     ["大闸蟹", "波士顿龙虾", "基围虾", "帝王蟹", "濑尿虾"],
    "mollusk":        ["生蚝", "扇贝", "蛏子", "鲍鱼", "蛤蜊"],
    "cephalopod":     ["墨鱼", "鱿鱼", "章鱼", "花枝", "小管"],
    "root_veg":       ["莲藕", "萝卜", "山药", "芋头", "松露"],
    "leaf_veg":       ["菜心", "芥蓝", "菠菜", "芝麻菜", "豆苗"],
    "fruit_veg":      ["番茄", "茄子", "青椒", "南瓜", "苦瓜"],
    "mushroom":       ["松茸", "羊肚菌", "鸡枞菌", "牛肝菌", "香菇"],
    "legume_grain":   ["大豆", "鹰嘴豆", "日本米", "泰国米", "杜兰小麦"],
}

# Already completed in test round — skip in pilot
TEST_DONE = {("poultry", "清远走地鸡"), ("beef", "和牛"), ("crustacean", "大闸蟹"),
             ("mushroom", "羊肚菌"), ("saltwater_fish", "金目鲷")}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

ROUND1_SYSTEM = """你是服务粤菜、法餐和融合菜高端厨房的食材顾问。

对于给定的食材，基于你的专业知识提供结构化信息。
找不到的字段填 null。只输出 JSON，不要 markdown 代码块或任何前后缀。

{
  "ingredient_zh": "中文名",
  "ingredient_en": "英文名（含拉丁学名如有）",
  "category": "类别",

  "varieties": [
    {
      "variety_name": "品种名（中英文）",
      "origin": "核心产地",
      "quality_notes": "专业厨房选购要点（重量/尺寸/脂肪层/色泽/气味等具体指标）",
      "spec": {
        "ideal_weight_g": null,
        "ideal_age_days": null,
        "fat_content_pct": null,
        "other": null
      },
      "best_for": ["最适合的烹饪方式"],
      "texture_profile": "质地描述（纤维粗细/脂肪分布/含水量/弹性等）"
    }
  ],

  "cuisine_context": {
    "cantonese": "在粤菜中的经典用法和选料标准",
    "french": "在法餐中的经典用法和选料标准",
    "fusion": "融合菜的创新方向"
  },

  "storage_notes": "专业厨房保存要点",
  "freshness_window_days": null,
  "key_science": "影响品质的核心科学原理（一句话概括）"
}

要求：
1. varieties 至少列 3 个不同产区的品种
2. quality_notes 必须是专业厨房级别的具体指标，不要"肉质鲜嫩"这种笼统描述
3. 如果同一食材在中餐和西餐语境中品质标准不同（如鸡的理想日龄），请在 cuisine_context 里分别说明
4. spec 里尽量给具体数字
"""

ROUND1_USER = "请提供以下食材的专业烹饪参数：{ingredient}（类别：{category}）"

ROUND2_SYSTEM = """你是食材地理和季节性的研究助手。

对于给定的食材及其品种列表，搜索并补充地理和季节信息。
所有信息必须基于搜索结果。找不到的填 null。只输出 JSON。

{
  "ingredient_zh": "食材名",

  "varieties_geo": [
    {
      "variety_name": "品种名（与输入对应）",
      "origin_detail": "详细产地（省/州/地区级别）",
      "country": "国家",
      "latitude": 纬度数字,
      "longitude": 经度数字,
      "peak_months": [最佳月份],
      "season_reason": "为什么这几个月最好（温度/降水/洋流/饲料周期等科学原因）",
      "why_this_origin": "这个产地优于其他产地的原因（土壤/水质/气候/养殖传统）"
    }
  ],

  "general_season": "总体最佳季节概述",
  "cross_region_comparison": "不同产区的关键差异（一段话总结）",
  "seasonal_price_note": "季节对价格/供应量的影响",
  "sources": ["引用URL"]
}

注意：
1. 海鲜类的季节性主要受水温和洋流影响，不只是纬度
2. peak_months 要具体到月份数字，不要笼统说"春季"
3. latitude/longitude 取产地中心点，精确到小数点后一位即可
4. 如果是养殖品种，季节性可能不明显，请说明
"""

ROUND2_USER = """请搜索以下食材的地理和季节信息：
食材：{ingredient}
已知品种列表：{variety_names_json}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_client() -> OpenAI:
    if not GEMINI_API_KEY:
        print("[FATAL] GEMINI_API_KEY not set", flush=True)
        sys.exit(1)
    return OpenAI(
        api_key=GEMINI_API_KEY,
        base_url=GEMINI_BASE_URL,
        http_client=httpx.Client(verify=True, trust_env=False),
    )


def ensure_dirs(base: Path) -> None:
    for sub in ("round1", "round2", "merged"):
        (base / sub).mkdir(parents=True, exist_ok=True)


def file_key(category: str, ingredient: str) -> str:
    return f"{category}_{ingredient}"


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_json_response(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def call_gemini(
    client: OpenAI,
    system: str,
    user: str,
    temperature: float = 0.3,
    search: bool = False,
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    if search:
        kwargs["extra_body"] = {"tools": [{"google_search": {}}]}

    t0 = time.time()
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        if search:
            print(f"  [search failed: {e}] retrying without search...", flush=True)
            kwargs.pop("extra_body", None)
            resp = client.chat.completions.create(**kwargs)
        else:
            raise
    elapsed = time.time() - t0

    raw_text = resp.choices[0].message.content or ""
    usage = {
        "input_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
        "output_tokens": getattr(resp.usage, "completion_tokens", 0) or 0,
        "elapsed_sec": round(elapsed, 1),
    }
    parsed = parse_json_response(raw_text)
    return parsed, raw_text, usage


# ---------------------------------------------------------------------------
# Post-processing (fixes from pilot review)
# ---------------------------------------------------------------------------


def validate_and_fix(entry: dict[str, Any]) -> dict[str, Any]:
    """Fix known field issues."""
    # Fix 1: quality_nodes typo -> quality_notes
    for v in entry.get("varieties", []):
        if "quality_nodes" in v and "quality_notes" not in v:
            v["quality_notes"] = v.pop("quality_nodes")

    # Fix 2: category lowercase
    if "category" in entry:
        entry["category"] = str(entry["category"]).lower()

    # Fix 3: add seasonality_type
    entry["seasonality_type"] = infer_seasonality(entry.get("varieties", []))

    return entry


def infer_seasonality(varieties: list[dict[str, Any]]) -> str:
    all_months: set[int] = set()
    for v in varieties:
        pm = v.get("peak_months")
        if isinstance(pm, list):
            all_months.update(int(m) for m in pm if isinstance(m, (int, float)))

    if not all_months:
        return "unknown"
    if len(all_months) >= 10:
        return "year_round"

    sorted_months = sorted(all_months)
    gaps = 0
    for i in range(1, len(sorted_months)):
        if sorted_months[i] - sorted_months[i - 1] > 2:
            gaps += 1
    # Check wrap-around gap (e.g. [10,11,12,1] should not count 12->1 gap)
    if len(sorted_months) >= 2 and (sorted_months[0] + 12 - sorted_months[-1]) > 2:
        gaps += 1

    if gaps >= 2:
        return "bi_peak"
    return "seasonal"


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------


def load_progress(base: Path) -> dict[str, Any]:
    p = base / "progress.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"done": [], "failed": []}


def save_progress(base: Path, progress: dict[str, Any]) -> None:
    save_json(base / "progress.json", progress)


def load_failed(base: Path) -> list[dict[str, Any]]:
    p = base / "failed.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


def save_failed(base: Path, failed: list[dict[str, Any]]) -> None:
    save_json(base / "failed.json", failed)


# ---------------------------------------------------------------------------
# Core pipeline (shared by test & pilot)
# ---------------------------------------------------------------------------


def run_round1_single(
    client: OpenAI, cat: str, ing: str, base: Path,
) -> dict[str, Any] | None:
    key = file_key(cat, ing)
    out_path = base / "round1" / f"{key}.json"
    print(f"  [R1] {key}...", end=" ", flush=True)
    user_msg = ROUND1_USER.format(ingredient=ing, category=cat)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            parsed, raw_text, usage = call_gemini(client, ROUND1_SYSTEM, user_msg, temperature=0.3)
            if parsed is None:
                (base / "round1" / f"{key}_raw.txt").write_text(raw_text, encoding="utf-8")
                if attempt < MAX_RETRIES:
                    print(f"parse fail (retry {attempt})...", end=" ", flush=True)
                    time.sleep(API_DELAY)
                    continue
                parsed = {"_parse_error": True, "_raw": raw_text[:2000]}
            parsed["_usage"] = usage
            save_json(out_path, parsed)
            n = len(parsed.get("varieties", []))
            print(f"{n} varieties, {usage['elapsed_sec']}s", flush=True)
            return parsed
        except Exception as e:
            if attempt < MAX_RETRIES:
                print(f"error (retry {attempt}: {e})...", end=" ", flush=True)
                time.sleep(API_DELAY * 2)
            else:
                print(f"FAILED: {e}", flush=True)
                return None
    return None


def run_round2_single(
    client: OpenAI, cat: str, ing: str, base: Path,
) -> dict[str, Any] | None:
    key = file_key(cat, ing)
    r1_path = base / "round1" / f"{key}.json"
    if not r1_path.exists():
        return None

    round1 = json.loads(r1_path.read_text(encoding="utf-8"))
    variety_names = [v.get("variety_name", "") for v in round1.get("varieties", [])]
    if not variety_names:
        return None

    print(f"  [R2] {key}...", end=" ", flush=True)
    user_msg = ROUND2_USER.format(
        ingredient=ing,
        variety_names_json=json.dumps(variety_names, ensure_ascii=False),
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            parsed, raw_text, usage = call_gemini(
                client, ROUND2_SYSTEM, user_msg, temperature=0.2, search=True,
            )
            if parsed is None:
                (base / "round2" / f"{key}_raw.txt").write_text(raw_text, encoding="utf-8")
                if attempt < MAX_RETRIES:
                    print(f"parse fail (retry {attempt})...", end=" ", flush=True)
                    time.sleep(API_DELAY)
                    continue
                parsed = {"_parse_error": True, "_raw": raw_text[:2000]}

            sources = parsed.get("sources", [])
            has_urls = any("http" in str(s) for s in sources) if sources else False
            parsed["_usage"] = usage
            parsed["_search_grounding"] = has_urls
            save_json(base / "round2" / f"{key}.json", parsed)

            geo_count = len(parsed.get("varieties_geo", []))
            print(f"{geo_count} geo, search={has_urls}, {usage['elapsed_sec']}s", flush=True)
            return parsed
        except Exception as e:
            if attempt < MAX_RETRIES:
                print(f"error (retry {attempt}: {e})...", end=" ", flush=True)
                time.sleep(API_DELAY * 2)
            else:
                print(f"FAILED: {e}", flush=True)
                return None
    return None


def merge_single(
    cat: str, ing: str, seq: int, base: Path,
) -> dict[str, Any] | None:
    key = file_key(cat, ing)
    r1_path = base / "round1" / f"{key}.json"
    r2_path = base / "round2" / f"{key}.json"

    if not r1_path.exists():
        return None

    round1 = json.loads(r1_path.read_text(encoding="utf-8"))
    round2 = json.loads(r2_path.read_text(encoding="utf-8")) if r2_path.exists() else {}

    geo_map: dict[str, dict[str, Any]] = {}
    for vg in round2.get("varieties_geo", []):
        geo_map[vg.get("variety_name", "")] = vg

    merged_varieties = []
    matched = 0
    for v in round1.get("varieties", []):
        vname = v.get("variety_name", "")
        geo = geo_map.get(vname, {})
        if geo:
            matched += 1
        merged_variety = {
            **v,
            "origin_detail": geo.get("origin_detail", v.get("origin")),
            "country": geo.get("country"),
            "latitude": geo.get("latitude"),
            "longitude": geo.get("longitude"),
            "peak_months": geo.get("peak_months"),
            "season_reason": geo.get("season_reason"),
            "why_this_origin": geo.get("why_this_origin"),
        }
        merged_varieties.append(merged_variety)

    merged = {
        "ingredient_id": f"L2A-{cat.upper()}-{seq:03d}",
        "ingredient_zh": round1.get("ingredient_zh", ing),
        "ingredient_en": round1.get("ingredient_en"),
        "category": round1.get("category", cat),
        "varieties": merged_varieties,
        "general_season": round2.get("general_season"),
        "cross_region_comparison": round2.get("cross_region_comparison"),
        "seasonal_price_note": round2.get("seasonal_price_note"),
        "cuisine_context": round1.get("cuisine_context"),
        "storage_notes": round1.get("storage_notes"),
        "freshness_window_days": round1.get("freshness_window_days"),
        "key_science": round1.get("key_science"),
        "sources": round2.get("sources", []),
        "_meta": {
            "round1_model": MODEL,
            "round2_model": MODEL,
            "round2_search_grounding": round2.get("_search_grounding", False),
            "generated_at": datetime.now().isoformat(),
        },
    }

    # Apply fixes
    merged = validate_and_fix(merged)

    save_json(base / "merged" / f"{key}.json", merged)
    total_v = len(round1.get("varieties", []))
    print(f"  [merge] {key}: {total_v} varieties, {matched}/{total_v} geo matched", flush=True)
    return merged


# ---------------------------------------------------------------------------
# Test commands (original 5)
# ---------------------------------------------------------------------------


def cmd_test_api() -> None:
    print(f"Testing Gemini API...", flush=True)
    print(f"  base_url: {GEMINI_BASE_URL}", flush=True)
    print(f"  model: {MODEL}", flush=True)
    client = get_client()
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": 'Say hello in JSON: {"msg": "..."}'}],
            max_tokens=20,
        )
        print(f"  Response: {resp.choices[0].message.content}", flush=True)
        print("  API OK", flush=True)
    except Exception as e:
        print(f"  API FAILED: {e}", flush=True)
        sys.exit(1)

    print("\nTesting search grounding...", flush=True)
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "What is the current population of Tokyo? Return JSON."}],
            extra_body={"tools": [{"google_search": {}}]},
            max_tokens=100,
        )
        text = resp.choices[0].message.content or ""
        print(f"  Has URL: {'http' in text.lower()}", flush=True)
        print("  Search grounding: likely enabled", flush=True)
    except Exception as e:
        print(f"  Search grounding failed: {e}", flush=True)


def cmd_run_all(ingredient_filter: str | None = None) -> None:
    """Run test mode (5 ingredients)."""
    base = OUTPUT_TEST
    ensure_dirs(base)
    client = get_client()

    cmd_test_api()

    ingredients = TEST_INGREDIENTS
    if ingredient_filter:
        ingredients = [(c, i) for c, i in ingredients if i == ingredient_filter]

    print(f"\n=== Round 1 ({len(ingredients)} ingredients) ===", flush=True)
    for cat, ing in ingredients:
        run_round1_single(client, cat, ing, base)
        time.sleep(API_DELAY)

    print(f"\n=== Round 2 ({len(ingredients)} ingredients) ===", flush=True)
    for cat, ing in ingredients:
        run_round2_single(client, cat, ing, base)
        time.sleep(API_DELAY)

    print(f"\n=== Merge ===", flush=True)
    for seq, (cat, ing) in enumerate(ingredients, 1):
        merge_single(cat, ing, seq, base)

    cmd_report_test()
    print("\nDone! Check output/l2a/test/", flush=True)


def cmd_report_test() -> None:
    """Generate test_report.md (for test mode)."""
    base = OUTPUT_TEST
    lines: list[str] = ["## L2a 小规模验证报告\n", f"生成时间: {datetime.now().isoformat()}\n"]
    lines.append(f"### API 状态\n- 模型: {MODEL}\n- Base URL: {GEMINI_BASE_URL}\n")

    for idx, (cat, ing) in enumerate(TEST_INGREDIENTS, 1):
        key = file_key(cat, ing)
        merged_path = base / "merged" / f"{key}.json"
        if merged_path.exists():
            m = json.loads(merged_path.read_text(encoding="utf-8"))
            nv = len(m.get("varieties", []))
            geo = sum(1 for v in m.get("varieties", []) if v.get("latitude") is not None)
            lines.append(f"#### {idx}. {ing} ({cat}): {nv} varieties, {geo}/{nv} geo matched\n")
    lines.append("### 结论\n- 待 Jeff 审核后填写\n")
    save_json_text(base / "test_report.md", "\n".join(lines))
    print(f"Report saved to {base / 'test_report.md'}", flush=True)


def save_json_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Pilot commands (75 ingredients)
# ---------------------------------------------------------------------------


def build_pilot_list(category_filter: str | None = None) -> list[tuple[str, str]]:
    """Build flat list of (category, ingredient) for pilot."""
    result = []
    for cat, ingredients in PILOT_INGREDIENTS.items():
        if category_filter and cat != category_filter:
            continue
        for ing in ingredients:
            result.append((cat, ing))
    return result


def cmd_pilot(category_filter: str | None = None, reset: bool = False) -> None:
    base = OUTPUT_PILOT
    ensure_dirs(base)
    (base / "by_category").mkdir(parents=True, exist_ok=True)
    client = get_client()

    all_items = build_pilot_list(category_filter)
    print(f"=== L2a Pilot: {len(all_items)} ingredients ===", flush=True)

    # Load progress
    if reset:
        progress = {"done": [], "failed": []}
        save_progress(base, progress)
        print("  Progress reset.", flush=True)
    else:
        progress = load_progress(base)

    done_set = set(progress.get("done", []))
    failed_list = load_failed(base)
    failed_keys = {f.get("key", "") for f in failed_list}

    # Copy test results for the 5 already-done ingredients
    for cat, ing in TEST_DONE:
        key = file_key(cat, ing)
        if key in done_set:
            continue
        src_merged = OUTPUT_TEST / "merged" / f"{key}.json"
        src_r1 = OUTPUT_TEST / "round1" / f"{key}.json"
        src_r2 = OUTPUT_TEST / "round2" / f"{key}.json"
        if src_merged.exists():
            for src, sub in [(src_r1, "round1"), (src_r2, "round2"), (src_merged, "merged")]:
                if src.exists():
                    dst = base / sub / f"{key}.json"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    # Re-apply fixes when copying
                    data = json.loads(src.read_text(encoding="utf-8"))
                    if sub == "merged":
                        data = validate_and_fix(data)
                    save_json(dst, data)
            done_set.add(key)
            progress["done"] = sorted(done_set)
            save_progress(base, progress)
            print(f"  [copied from test] {key}", flush=True)

    # Run remaining
    t_start = time.time()
    total_r1_usage = {"input_tokens": 0, "output_tokens": 0}
    total_r2_usage = {"input_tokens": 0, "output_tokens": 0}
    seq_counter = {cat: 0 for cat in PILOT_INGREDIENTS}

    for cat, ing in all_items:
        key = file_key(cat, ing)
        seq_counter[cat] += 1

        if key in done_set:
            continue
        if key in failed_keys:
            continue

        print(f"\n[{len(done_set)+1}/{len(all_items)}] {cat}/{ing}", flush=True)

        # Round 1
        r1 = run_round1_single(client, cat, ing, base)
        time.sleep(API_DELAY)

        if r1 is None or r1.get("_parse_error"):
            failed_list.append({"key": key, "category": cat, "ingredient": ing,
                                "stage": "round1", "time": datetime.now().isoformat()})
            save_failed(base, failed_list)
            failed_keys.add(key)
            continue

        u1 = r1.get("_usage", {})
        total_r1_usage["input_tokens"] += u1.get("input_tokens", 0)
        total_r1_usage["output_tokens"] += u1.get("output_tokens", 0)

        # Round 2
        r2 = run_round2_single(client, cat, ing, base)
        time.sleep(API_DELAY)

        if r2 is not None:
            u2 = r2.get("_usage", {})
            total_r2_usage["input_tokens"] += u2.get("input_tokens", 0)
            total_r2_usage["output_tokens"] += u2.get("output_tokens", 0)

        # Merge
        merged = merge_single(cat, ing, seq_counter[cat], base)

        if merged is None:
            failed_list.append({"key": key, "category": cat, "ingredient": ing,
                                "stage": "merge", "time": datetime.now().isoformat()})
            save_failed(base, failed_list)
            failed_keys.add(key)
            continue

        done_set.add(key)
        progress["done"] = sorted(done_set)
        save_progress(base, progress)

    elapsed_min = (time.time() - t_start) / 60

    # Generate by_category JSONL
    print("\n=== Generating by_category JSONL ===", flush=True)
    for cat in PILOT_INGREDIENTS:
        cat_entries = []
        for ing in PILOT_INGREDIENTS[cat]:
            key = file_key(cat, ing)
            merged_path = base / "merged" / f"{key}.json"
            if merged_path.exists():
                cat_entries.append(json.loads(merged_path.read_text(encoding="utf-8")))
        if cat_entries:
            jsonl_path = base / "by_category" / f"{cat}.jsonl"
            with open(jsonl_path, "w", encoding="utf-8") as f:
                for entry in cat_entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            print(f"  {cat}.jsonl: {len(cat_entries)} entries", flush=True)

    # Generate summary + report
    generate_pilot_summary(base, total_r1_usage, total_r2_usage, elapsed_min)
    generate_quality_report(base, total_r1_usage, total_r2_usage, elapsed_min)

    print(f"\n=== Pilot complete: {len(done_set)} done, {len(failed_list)} failed ===", flush=True)


def generate_pilot_summary(
    base: Path,
    r1_usage: dict[str, int],
    r2_usage: dict[str, int],
    elapsed_min: float,
) -> None:
    merged_dir = base / "merged"
    entries = []
    for f in sorted(merged_dir.glob("*.json")):
        entries.append(json.loads(f.read_text(encoding="utf-8")))

    summary = {
        "total": len(entries),
        "failed": len(load_failed(base)),
        "r1_usage": r1_usage,
        "r2_usage": r2_usage,
        "elapsed_min": round(elapsed_min, 1),
        "generated_at": datetime.now().isoformat(),
    }
    save_json(base / "pilot_summary.json", summary)


def generate_quality_report(
    base: Path,
    r1_usage: dict[str, int],
    r2_usage: dict[str, int],
    elapsed_min: float,
) -> None:
    merged_dir = base / "merged"
    entries = []
    for f in sorted(merged_dir.glob("*.json")):
        entries.append(json.loads(f.read_text(encoding="utf-8")))

    total = len(entries)
    failed = load_failed(base)

    # Coverage stats
    has_varieties = sum(1 for e in entries if e.get("varieties"))
    all_varieties = [v for e in entries for v in e.get("varieties", [])]
    avg_varieties = len(all_varieties) / total if total else 0
    has_qn = sum(1 for v in all_varieties if v.get("quality_notes"))
    has_pm = sum(1 for v in all_varieties if v.get("peak_months"))
    has_sr = sum(1 for v in all_varieties if v.get("season_reason"))
    has_ll = sum(1 for v in all_varieties if v.get("latitude") is not None)
    has_ctx = sum(1 for e in entries if e.get("cuisine_context"))
    has_src = sum(1 for e in entries if e.get("sources"))

    # Seasonality
    st_dist: dict[str, int] = {}
    for e in entries:
        st = e.get("seasonality_type", "unknown")
        st_dist[st] = st_dist.get(st, 0) + 1

    # Quality checks
    cat_upper = sum(1 for e in entries if e.get("category", "") != e.get("category", "").lower())
    qn_typo = sum(1 for v in all_varieties if "quality_nodes" in v)
    lat_bad = sum(1 for v in all_varieties if v.get("latitude") is not None and (abs(v["latitude"]) > 90))
    pm_bad = sum(1 for v in all_varieties
                 if v.get("peak_months") and any(m < 1 or m > 12 for m in v["peak_months"]))

    # Best/worst
    def completeness(e: dict[str, Any]) -> int:
        score = 0
        for v in e.get("varieties", []):
            if v.get("quality_notes"): score += 1
            if v.get("peak_months"): score += 1
            if v.get("latitude") is not None: score += 1
            if v.get("season_reason"): score += 1
        if e.get("cuisine_context"): score += 2
        if e.get("sources"): score += 1
        score += len(e.get("varieties", []))
        return score

    ranked = sorted(entries, key=completeness, reverse=True)
    best_5 = ranked[:5]
    worst_5 = ranked[-5:] if len(ranked) >= 5 else ranked

    nv = len(all_varieties) or 1
    lines = [
        f"=== L2a Pilot 质量报告 ===",
        f"生成时间: {datetime.now().isoformat()}",
        f"总食材数: {total}",
        f"成功: {total}, 失败: {len(failed)}",
        f"",
        f"覆盖率:",
        f"  有 varieties 的: {has_varieties}/{total} ({100*has_varieties//max(total,1)}%)",
        f"  varieties 平均数量: {avg_varieties:.1f}（目标>=3）",
        f"  有 quality_notes 的品种: {has_qn}/{nv} ({100*has_qn//nv}%)",
        f"  有 peak_months 的品种: {has_pm}/{nv} ({100*has_pm//nv}%)",
        f"  有 season_reason 的品种: {has_sr}/{nv} ({100*has_sr//nv}%)",
        f"  有 latitude/longitude 的品种: {has_ll}/{nv} ({100*has_ll//nv}%)",
        f"  有 cuisine_context 的食材: {has_ctx}/{total} ({100*has_ctx//max(total,1)}%)",
        f"  有 sources URL 的食材: {has_src}/{total} ({100*has_src//max(total,1)}%)",
        f"",
        f"seasonality_type 分布:",
    ]
    for st, count in sorted(st_dist.items(), key=lambda x: -x[1]):
        lines.append(f"  {st}: {count} 个")

    lines += [
        f"",
        f"数据质量:",
        f"  category 大小写异常: {cat_upper} 个",
        f"  quality_notes typo: {qn_typo} 个",
        f"  纬度范围异常(>90或<-90): {lat_bad} 个",
        f"  peak_months 异常(>12或<1): {pm_bad} 个",
        f"",
        f"成本:",
        f"  Round 1 总 tokens: input {r1_usage['input_tokens']:,}, output {r1_usage['output_tokens']:,}",
        f"  Round 2 总 tokens: input {r2_usage['input_tokens']:,}, output {r2_usage['output_tokens']:,}",
        f"  总耗时: {elapsed_min:.1f} 分钟",
        f"",
        f"最佳样本（字段最完整的 5 个）:",
    ]
    for i, e in enumerate(best_5, 1):
        lines.append(f"  {i}. {e.get('ingredient_zh', '?')} ({e.get('category', '?')}) "
                     f"— {len(e.get('varieties', []))} varieties, score={completeness(e)}")

    lines.append(f"\n问题食材（字段最不完整的 5 个）:")
    for i, e in enumerate(worst_5, 1):
        lines.append(f"  {i}. {e.get('ingredient_zh', '?')} ({e.get('category', '?')}) "
                     f"— {len(e.get('varieties', []))} varieties, score={completeness(e)}")

    report_text = "\n".join(lines)
    save_json_text(base / "quality_report.md", report_text)
    print(report_text, flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="L2a ingredient database — test + pilot")
    parser.add_argument("command", choices=["test-api", "round1", "round2", "merge", "report", "all", "pilot"])
    parser.add_argument("--ingredient", help="只跑某个食材（中文名）")
    parser.add_argument("--category", help="Pilot: 只跑某个类别")
    parser.add_argument("--reset", action="store_true", help="Pilot: 重置进度重跑")
    args = parser.parse_args()

    dispatch = {
        "test-api": lambda: cmd_test_api(),
        "all": lambda: cmd_run_all(args.ingredient),
        "report": lambda: cmd_report_test(),
        "pilot": lambda: cmd_pilot(args.category, args.reset),
    }

    # Legacy single-step commands for test mode
    if args.command in ("round1", "round2", "merge"):
        base = OUTPUT_TEST
        ensure_dirs(base)
        client = get_client()
        for cat, ing in TEST_INGREDIENTS:
            if args.ingredient and ing != args.ingredient:
                continue
            if args.command == "round1":
                run_round1_single(client, cat, ing, base)
            elif args.command == "round2":
                run_round2_single(client, cat, ing, base)
            elif args.command == "merge":
                merge_single(cat, ing, 0, base)
            time.sleep(API_DELAY)
        return

    dispatch[args.command]()


if __name__ == "__main__":
    main()
