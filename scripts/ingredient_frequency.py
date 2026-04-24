#!/usr/bin/env python3
"""
scripts/ingredient_frequency.py
Extract ingredient names + frequencies from L2b recipe data,
weight Cantonese-cuisine sources 1.5×, and write a CSV ranking
for human curation (pick top 200 from top 300).

Data sources (both formats scanned):
  • NEW pipeline:  output/*/skill_b/results.jsonl
     top-level recipe, ingredient field = `name`
  • OLD pipeline:  output/*/l2b/stage5_results.jsonl
     recipes wrapped in `recipes[]`, ingredient field = `item`

Run:
    /Users/jeff/miniforge3/bin/python3 scripts/ingredient_frequency.py

Output:
    data/ingredient_frequency.csv  (top 300, ranked)
    stdout: summary stats + top 20
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import opencc
    _T2S = opencc.OpenCC("t2s")
except Exception as e:   # noqa: BLE001
    print(f"ERROR: opencc-python-reimplemented not installed: {e}", file=sys.stderr)
    print("Install: /Users/jeff/miniforge3/bin/python3 -m pip install opencc-python-reimplemented",
          file=sys.stderr)
    sys.exit(1)

REPO_ROOT   = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "output"
OUT_CSV     = REPO_ROOT / "data" / "ingredient_frequency.csv"
TOP_N       = 300

# Cantonese books get 1.5× weight in the weighted_count column.
YUE_BOOKS: set[str] = {
    "guangdong_pengtiao_quanshu", "hk_yuecan_yanxi",
    "zhujixiaoguan_2", "zhujixiaoguan_3", "zhujixiaoguan_4",
    "zhujixiaoguan_6", "zhujixiaoguan_v6b", "zhujixiaoguan_dimsim2",
    "yuecan_zhenwei_meat", "fenbuxiangjiena_yc",
    "chuantong_yc", "gufa_yc", "shijing", "phoenix_claws",
    "xidage_xunwei_hk", "yuecan_wangliang",
    "zhongguo_caipu_guangdong", "zhongguo_yinshi_meixueshi",
}
YUE_WEIGHT  = 1.5
NON_YUE_WEIGHT = 1.0

# Filler words / quantity qualifiers that are not ingredients.
STOPWORDS: set[str] = {
    "适量", "少许", "少量", "若干", "酌量", "随意", "按需",
    "一些", "数粒", "数片", "数根",
    "to taste", "as needed", "as desired", "optional", "for garnish",
    "for serving", "for dusting", "for brushing",
}
# Drop if ingredient is only non-alnum CJK (e.g. "——" or empty).
_ALNUM_RE = re.compile(r"[\w\u4e00-\u9fff]")


def _clean(raw: str) -> str:
    """Lower-level cleaning. Returns '' if the string should be dropped."""
    if not raw:
        return ""
    s = str(raw).strip()
    # Drop parentheticals like "(Dark, Milk, or White)" — keep bare noun.
    s = re.sub(r"\s*[\(（][^)）]*[\)）]\s*$", "", s).strip()
    # Strip trailing commas / trailing qualifier fragments.
    s = s.strip(",，.。;；:：")
    if not s:
        return ""
    if not _ALNUM_RE.search(s):
        return ""
    lo = s.lower()
    if lo in STOPWORDS:
        return ""
    # 繁 → 简 for CJK portions; leaves ASCII alone.
    s = _T2S.convert(s)
    # Normalise case: English → lower; CJK unaffected.
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in s)
    if not has_cjk:
        s = s.lower()
    # Collapse internal whitespace.
    s = re.sub(r"\s+", " ", s)
    return s


# Very rough category guess — not authoritative, curators will fix.
# Rules evaluated in order; first match wins.
# Order matters — first match wins. Put specific rules (水/液体, 香料, 酒)
# before generic ones (肉类, 蔬菜, 蛋奶) to avoid cases like 胡椒粉→蔬菜 or
# 鸡汤→肉类. 蛋奶's "清" token is dropped because 清水/清汤 are more likely
# water/broth than egg-white.
CATEGORY_RULES: list[tuple[str, re.Pattern]] = [
    ("水/液体",    re.compile(r"(水|汤|高汤|清汤|上汤|stock|broth|water)", re.I)),
    ("香料",       re.compile(r"(花椒|八角|桂皮|丁香|茴|胡椒|香料|香叶|nutmeg|cinnamon|clove|pepper|spice|herb)", re.I)),
    ("酒",         re.compile(r"(酒|黄酒|白酒|绍酒|wine|rum|brandy|whisky|vodka)", re.I)),
    ("调味料",     re.compile(r"(酱|醋|糖|盐|味精|鸡精|蚝油|酱油|生抽|老抽|鱼露|豆瓣|料酒|米酒|绍兴|沙茶|芥末|XO)", re.I)),
    ("油脂",       re.compile(r"(油|脂|butter|lard|shortening|tallow)", re.I)),
    ("巧克力/甜点",re.compile(r"(巧克力|可可|chocolate|cocoa|caramel|praline|ganache)", re.I)),
    ("水产",       re.compile(r"(鱼|虾|蟹|贝|蛤|蚬|螺|鲍|鳗|鱿|乌贼|章鱼|墨鱼|海鲜|fish|shrimp|crab|scallop|octopus|squid|seafood)", re.I)),
    ("肉类",       re.compile(r"(肉|排骨|里脊|腩|腿|翅|胸|鸡|鸭|鹅|猪|牛|羊|lamb|beef|pork|chicken|duck|veal)", re.I)),
    ("蛋奶",       re.compile(r"(蛋|蛋黄|蛋清|奶|乳|芝士|奶酪|cream|milk|egg|cheese|yoghurt|yogurt|butter)", re.I)),
    ("豆制品",     re.compile(r"(豆|腐|tofu)", re.I)),
    ("蔬菜",       re.compile(r"(菜|葱|蒜|姜|椒|菇|笋|藕|蘑|薯|萝卜|番茄|洋葱|韭|芹|萝)", re.I)),
    ("水果",       re.compile(r"(果|枣|柠|柑|橘|梨|桃|葡萄|strawberry|apple|lemon|berry|mango|banana|pear)", re.I)),
    ("坚果/种子",  re.compile(r"(仁|籽|核桃|杏仁|芝麻|花生|nut|almond|sesame|peanut)", re.I)),
    ("主食/谷物",  re.compile(r"(米|面|粉|饭|粥|馒|包|饺|汤圆|flour|rice|bread|pasta|noodle|dough)", re.I)),
]


def category_guess(name: str) -> str:
    for label, pat in CATEGORY_RULES:
        if pat.search(name):
            return label
    return "其他"


# ── Scanners ──────────────────────────────────────────────────────────────────

def _book_id_from_path(p: Path, depth_after_output: int) -> str:
    """output/<book_id>/skill_b/results.jsonl → book_id at index 1."""
    parts = p.relative_to(OUTPUT_ROOT).parts
    return parts[0] if parts else "?"


def scan_skill_b(
    per_book: dict[str, Counter[str]],
    per_ingredient_books: dict[str, set[str]],
) -> tuple[int, int]:
    """Returns (files_scanned, recipes_counted)."""
    files = 0
    recipes = 0
    for p in sorted(OUTPUT_ROOT.glob("*/skill_b/results.jsonl")):
        book = _book_id_from_path(p, 1)
        files += 1
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("_error"):
                    continue
                ings = rec.get("ingredients") or []
                if not ings:
                    continue
                recipes += 1
                for ing in ings:
                    if not isinstance(ing, dict):
                        continue
                    name = _clean(ing.get("name", ""))
                    if not name:
                        continue
                    per_book[book][name] += 1
                    per_ingredient_books[name].add(book)
    return files, recipes


def scan_stage5(
    per_book: dict[str, Counter[str]],
    per_ingredient_books: dict[str, set[str]],
) -> tuple[int, int]:
    """Returns (files_scanned, recipes_counted)."""
    files = 0
    recipes = 0
    for p in sorted(OUTPUT_ROOT.glob("*/l2b/stage5_results.jsonl")):
        book = _book_id_from_path(p, 1)
        files += 1
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("_error"):
                    continue
                for r in rec.get("recipes") or []:
                    if not isinstance(r, dict):
                        continue
                    ings = r.get("ingredients") or []
                    if not ings:
                        continue
                    recipes += 1
                    for ing in ings:
                        if not isinstance(ing, dict):
                            continue
                        name = _clean(ing.get("item", ""))
                        if not name:
                            continue
                        per_book[book][name] += 1
                        per_ingredient_books[name].add(book)
    return files, recipes


# ── Aggregation ───────────────────────────────────────────────────────────────

def aggregate(per_book: dict[str, Counter[str]]) -> list[dict]:
    raw   : Counter[str]           = Counter()
    weight: Counter[str]           = Counter()
    top_src: dict[str, Counter[str]] = defaultdict(Counter)   # ingredient → book → count
    for book, cnt in per_book.items():
        w = YUE_WEIGHT if book in YUE_BOOKS else NON_YUE_WEIGHT
        for name, c in cnt.items():
            raw[name]    += c
            weight[name] += c * w
            top_src[name][book] += c
    rows = []
    for name, raw_c in raw.items():
        sources = top_src[name]
        top_list = [bid for bid, _ in sources.most_common(3)]
        rows.append({
            "ingredient":         name,
            "raw_count":          raw_c,
            "weighted_count":     round(weight[name], 2),
            "source_books_count": len(sources),
            "top_sources":        "|".join(top_list),
            "category_guess":     category_guess(name),
        })
    rows.sort(key=lambda r: (-r["weighted_count"], -r["raw_count"], r["ingredient"]))
    return rows


def write_csv(rows: list[dict], out_path: Path, top_n: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["rank", "ingredient", "raw_count", "weighted_count",
            "source_books_count", "top_sources", "category_guess"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for i, r in enumerate(rows[:top_n], start=1):
            w.writerow({"rank": i, **r})


def print_summary(rows: list[dict], n_ing_total: int, n_recipes: int,
                  files_skill_b: int, files_stage5: int) -> None:
    print()
    print(f"=== Ingredient Frequency Summary ===")
    print(f"  files scanned:      skill_b={files_skill_b}, stage5={files_stage5}")
    print(f"  recipes counted:    {n_recipes}")
    print(f"  unique ingredients: {n_ing_total}")
    print(f"  wrote top {min(TOP_N, len(rows))} → {OUT_CSV}")
    print()
    print("=== Top 20 (weighted) ===")
    print(f"  {'rank':>4}  {'ingredient':<28} {'raw':>6} {'wgt':>8} {'books':>5}  {'category':<10}  top_sources")
    for i, r in enumerate(rows[:20], start=1):
        print(f"  {i:>4}  {r['ingredient'][:28]:<28} "
              f"{r['raw_count']:>6} {r['weighted_count']:>8.1f} "
              f"{r['source_books_count']:>5}  {r['category_guess']:<10}  "
              f"{r['top_sources']}")


def main() -> int:
    per_book: dict[str, Counter[str]] = defaultdict(Counter)
    per_ingredient_books: dict[str, set[str]] = defaultdict(set)
    files_b, recipes_b = scan_skill_b(per_book, per_ingredient_books)
    files_5, recipes_5 = scan_stage5(per_book, per_ingredient_books)
    rows = aggregate(per_book)
    if not rows:
        print("No ingredients extracted. Nothing to write.", file=sys.stderr)
        return 1
    write_csv(rows, OUT_CSV, TOP_N)
    print_summary(rows, len(rows), recipes_b + recipes_5, files_b, files_5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
