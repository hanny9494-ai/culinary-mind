# L2b Step B — L0 绑定 + 4 字段补标 Prompt 设计

> 母对话设计，2026-03-26
> 定位：对 29,085 条 Stage5 Step A 食谱做 L0 科学原理绑定，同时补标 course / serving_temp / flavor_tags / dietary_tags

---

## 1. 任务定义

**输入：** Stage5 Step A 产出的食谱 JSON（含 recipe_type, name, ingredients, steps, equipment）
**输出：** Step B 补充字段，合并写回同一条食谱记录
**一次调用完成：** 4 字段分类 + key_science_points 全部在一个 completion 里

---

## 2. 值域定义

### course（菜品位置）
```
appetizer | soup | main | side | dessert | snack | beverage | sauce | bread
```

### serving_temp（上菜温度）
```
hot | warm | cold | room_temp | frozen
```
- hot: 立即上桌趁热吃（≥60°C）
- warm: 温食（40-60°C）
- cold: 冷食冷藏（≤15°C）
- room_temp: 常温存放/食用（15-25°C）
- frozen: 冰冻食用（冰淇淋/冰棒）

### flavor_tags（风味词，多选，从词表选）
```
sweet | sour | salty | bitter | umami | spicy | smoky | herbal | rich | light | tangy | nutty | floral | earthy
```
- 最多选 5 个，按主次排序

### dietary_tags（饮食限制，多选，从词表选）
```
vegetarian | vegan | gluten_free | dairy_free | nut_free | egg_free | shellfish_free | halal | kosher | low_carb
```
- 只标能**确认**的，不确定不标（宁少勿错）

### l0_domains（科学域，从 17 域选）
```
protein_science | carbohydrate | lipid_science | fermentation | food_safety |
water_activity | enzyme | color_pigment | equipment_physics | maillard_caramelization |
oxidation_reduction | salt_acid_chemistry | taste_perception | aroma_volatiles |
thermal_dynamics | mass_transfer | texture_rheology
```

---

## 3. Prompt 设计

### 3.1 System Prompt

```
You are a culinary science analyst specializing in food chemistry and cooking physics.
Your task is to analyze recipe data and output structured JSON annotations.

You MUST:
1. Output ONLY valid JSON — no markdown fences, no explanations, no preamble
2. Select all values STRICTLY from the provided controlled vocabularies
3. Identify 1-5 key science decision points that determine recipe success or failure
4. Each science point must cite the exact step number it applies to
5. Be precise about parameter boundaries — temperature ranges, ratios, timing windows

You MUST NOT:
- Invent new vocabulary outside the provided lists
- Add commentary outside the JSON structure
- Include more than 5 key_science_points
- Include trivial observations (e.g., "salt adds saltiness") — only failure-critical science
- Leave key_science_points non-empty for extremely simple recipes (single-ingredient preparations)
```

### 3.2 User Prompt Template

```
Analyze this recipe and return JSON with exactly these fields:
- course: one value from [appetizer, soup, main, side, dessert, snack, beverage, sauce, bread]
- serving_temp: one value from [hot, warm, cold, room_temp, frozen]
- flavor_tags: 1-5 values from [sweet, sour, salty, bitter, umami, spicy, smoky, herbal, rich, light, tangy, nutty, floral, earthy]
- dietary_tags: 0 or more confirmed values from [vegetarian, vegan, gluten_free, dairy_free, nut_free, egg_free, shellfish_free, halal, kosher, low_carb]
- key_science_points: array of 0-5 objects, each with:
  - step_ref: integer (step order number this applies to, use 0 for overall recipe)
  - principle: string (the science mechanism — what happens and why)
  - l0_domains: 1-3 values from [protein_science, carbohydrate, lipid_science, fermentation, food_safety, water_activity, enzyme, color_pigment, equipment_physics, maillard_caramelization, oxidation_reduction, salt_acid_chemistry, taste_perception, aroma_volatiles, thermal_dynamics, mass_transfer, texture_rheology]
  - parameter_boundary: string (the critical threshold — what value causes failure)

Rules:
- dietary_tags: only mark what ingredients CONFIRM (e.g., do not mark dairy_free if unknown)
- key_science_points: focus on decisions that change the outcome — temperature windows, emulsion stability, protein denaturation points, fermentation conditions
- If recipe is trivially simple (1-2 ingredients, no technique), key_science_points = []

Recipe:
{{RECIPE_JSON}}

Return JSON only:
```

### 3.3 完整输出 Schema

```json
{
  "course": "dessert",
  "serving_temp": "cold",
  "flavor_tags": ["sweet", "rich", "bitter"],
  "dietary_tags": ["vegetarian"],
  "key_science_points": [
    {
      "step_ref": 1,
      "principle": "Whipping incorporates air into fat globules via partial coalescence; overwhipping fully coalesces fat globules, releasing liquid fat and forming butter",
      "l0_domains": ["lipid_science", "texture_rheology"],
      "parameter_boundary": "Stop at soft peaks (volume ~2x, trails just hold shape); overwhip = grainy clumped texture, weeps liquid"
    },
    {
      "step_ref": 2,
      "principle": "Chocolate temperature determines fat crystal state; above 36°C cocoa butter is fully liquid and will melt whipped cream fat structure on contact",
      "l0_domains": ["thermal_dynamics", "lipid_science"],
      "parameter_boundary": "Cool chocolate to 30-34°C before folding; >38°C collapses foam, <28°C causes lumps from premature solidification"
    }
  ]
}
```

---

## 4. 样本验证

### Sample A — 简单甜品（Chocolate Whipped Cream）

**输入：**
```json
{
  "recipe_type": "main",
  "name": "Chocolate Whipped Cream",
  "ingredients": [
    {"item": "Heavy cream", "qty": 1, "unit": "qt"},
    {"item": "Semisweet chocolate", "qty": 12, "unit": "oz"}
  ],
  "steps": [
    {"order": 1, "text": "Whip the cream as in the basic procedure, but underwhip it slightly.", "action": "whip"},
    {"order": 2, "text": "Melt the chocolate and let it cool to lukewarm.", "action": "melt"},
    {"order": 3, "text": "Fold the chocolate quickly into the cream.", "action": "fold"}
  ],
  "equipment": ["mixer", "bowl"]
}
```

**预期输出：**
```json
{
  "course": "dessert",
  "serving_temp": "cold",
  "flavor_tags": ["sweet", "rich", "bitter"],
  "dietary_tags": ["vegetarian"],
  "key_science_points": [
    {
      "step_ref": 1,
      "principle": "Partial fat globule coalescence traps air bubbles; underwhipping preserves flexibility for chocolate folding without structure collapse",
      "l0_domains": ["lipid_science", "texture_rheology"],
      "parameter_boundary": "Target soft peaks only; medium peaks will over-set after chocolate incorporation"
    },
    {
      "step_ref": 2,
      "principle": "Cocoa butter polymorphic state changes with temperature; lukewarm (30-34°C) keeps chocolate fluid enough to fold without resolidifying as lumps",
      "l0_domains": ["thermal_dynamics", "lipid_science"],
      "parameter_boundary": "32-34°C optimal; above 38°C melts cream fat structure; below 27°C seizes into lumps on contact with cold cream"
    },
    {
      "step_ref": 3,
      "principle": "Folding speed determines air retention; rapid overmixing shears foam bubbles, slow undermixing leaves chocolate streaks that later seize",
      "l0_domains": ["mass_transfer", "texture_rheology"],
      "parameter_boundary": "10-15 fold strokes maximum; stop when just homogeneous"
    }
  ]
}
```

---

### Sample B — 蛋白质主菜（Seared Duck Breast）

**输入：**
```json
{
  "recipe_type": "main",
  "name": "Seared Duck Breast",
  "ingredients": [
    {"item": "Duck breast", "qty": 2, "unit": "each"},
    {"item": "Salt", "qty": null, "unit": "to taste"},
    {"item": "Black pepper", "qty": null, "unit": "to taste"}
  ],
  "steps": [
    {"order": 1, "text": "Score the skin in a crosshatch pattern without cutting into the flesh.", "action": "score"},
    {"order": 2, "text": "Season generously with salt 30 minutes before cooking.", "action": "season"},
    {"order": 3, "text": "Place skin-side down in a cold pan, then bring to medium heat. Cook 8-10 minutes until fat is rendered and skin is crisp.", "action": "sear"},
    {"order": 4, "text": "Flip and cook flesh side 3-4 minutes to medium-rare (57°C internal).", "action": "cook"},
    {"order": 5, "text": "Rest 5 minutes before slicing.", "action": "rest"}
  ],
  "equipment": ["pan", "thermometer"]
}
```

**预期输出：**
```json
{
  "course": "main",
  "serving_temp": "hot",
  "flavor_tags": ["savory", "rich", "smoky"],
  "dietary_tags": ["gluten_free", "dairy_free", "egg_free"],
  "key_science_points": [
    {
      "step_ref": 2,
      "principle": "Early salting draws moisture to surface via osmosis, then diffusion pulls dissolved salt back into muscle while surface dries — net effect is seasoned interior and drier skin",
      "l0_domains": ["salt_acid_chemistry", "mass_transfer", "water_activity"],
      "parameter_boundary": "30-60 min pre-salting: surface re-absorbs brine; <10 min: wet surface inhibits browning; >24h: muscle begins to cure/texture changes"
    },
    {
      "step_ref": 3,
      "principle": "Cold-pan start allows subcutaneous fat to render gradually before skin proteins set; hot-pan start contracts skin proteins before fat escapes, trapping fat and preventing crispness",
      "l0_domains": ["lipid_science", "thermal_dynamics", "protein_science"],
      "parameter_boundary": "Start cold; target skin internal temp >130°C for Maillard; fat render complete when skin feels rigid and flat"
    },
    {
      "step_ref": 4,
      "principle": "Myosin denatures at 50°C, actin at 65-70°C; medium-rare target preserves myowater-binding myosin structure while avoiding tough actin coagulation",
      "l0_domains": ["protein_science", "thermal_dynamics"],
      "parameter_boundary": "57°C internal = medium-rare (pink, juicy); above 65°C = actin denaturation, significant moisture loss, tough texture"
    },
    {
      "step_ref": 5,
      "principle": "Resting allows thermal equalization and myofibril reabsorption of expelled juices as muscle tension relaxes after heat contraction",
      "l0_domains": ["protein_science", "mass_transfer"],
      "parameter_boundary": "5 min minimum; cutting immediately loses 20-30% more juice than rested meat"
    }
  ]
}
```

**注意：** flavor_tags 中 "savory" 不在词表，正式跑时 LLM 应选 "umami" 替代。此处标注提醒 prompt 中词表约束的重要性。

---

### Sample C — 极简配方（Clarified Butter）

**输入：**
```json
{
  "recipe_type": "sauce",
  "name": "Clarified Butter",
  "ingredients": [
    {"item": "Unsalted butter", "qty": 1, "unit": "lb"}
  ],
  "steps": [
    {"order": 1, "text": "Melt butter slowly over low heat without stirring.", "action": "melt"},
    {"order": 2, "text": "Skim the foam from the surface.", "action": "skim"},
    {"order": 3, "text": "Carefully ladle the clear golden liquid, leaving the milky solids on the bottom.", "action": "decant"}
  ],
  "equipment": ["saucepan", "ladle"]
}
```

**预期输出：**
```json
{
  "course": "sauce",
  "serving_temp": "warm",
  "flavor_tags": ["rich", "nutty"],
  "dietary_tags": ["vegetarian", "gluten_free", "egg_free"],
  "key_science_points": [
    {
      "step_ref": 1,
      "principle": "Low heat prevents Maillard reaction of milk proteins; target temperature keeps butter liquid (>35°C) without browning milk solids (>120°C starts browning)",
      "l0_domains": ["lipid_science", "maillard_caramelization", "thermal_dynamics"],
      "parameter_boundary": "Keep below 80°C; above 100°C water evaporates too fast and milk solids begin to brown, producing beurre noisette instead of clarified butter"
    },
    {
      "step_ref": 0,
      "principle": "Butter emulsion breaks into three layers by density: foam (denatured whey protein), clear butterfat (triglycerides), milk solids (casein + lactose); separation exploits density and protein aggregation",
      "l0_domains": ["lipid_science", "protein_science", "water_activity"],
      "parameter_boundary": "Complete separation requires full protein denaturation; incomplete heating leaves emulsified fat in the discarded solids, reducing yield"
    }
  ]
}
```

---

## 5. 模型选择分析

### flash（qwen-plus/qwen-flash 或 claude-haiku）

| 维度 | 评估 |
|---|---|
| 推理深度 | 中等；能识别主要科学机制，但参数边界有时模糊 |
| JSON 合规率 | 高（95%+），结构稳定 |
| 速度 | 3-5 并发，29,085 条约 4-6 小时 |
| 成本（代理价）| ~¥0.1-0.3/千条 → 全量 ¥3-9 |
| 失误模式 | 偶尔把 principle 写得太笼统；parameter_boundary 用定性而非定量描述 |

### Opus 4.6（claude-opus-4-6）

| 维度 | 评估 |
|---|---|
| 推理深度 | 高；能给出精确温度窗口、机制因果链清晰 |
| JSON 合规率 | 高（98%+） |
| 速度 | 串行限速，29,085 条约 40-60 小时 |
| 成本（代理价，1/22折）| ~¥3-5/千条 → 全量 ¥87-145 |
| 优势场景 | 复杂多步骤配方、蛋白质变性精确参数、发酵/酶促反应边界 |

### 推荐策略：Flash 主跑 + Opus 精修

**原因：**
1. flash 能处理 ~80% 的标准配方（烘焙/酱汁/甜点）
2. 复杂配方（蛋白质烹饪/发酵/多阶段乳化）flash 给出的 parameter_boundary 精度不够
3. 全量 Opus 成本可接受（¥87-145），但时间成本太高

**两阶段方案：**

```
Phase 1: flash 全量跑（29,085 条，¥3-9，4-6小时）
  → 输出初稿

Phase 2: 识别需要 Opus 精修的条目（规则筛选）：
  - key_science_points 含 protein_science / fermentation / enzyme 的
  - parameter_boundary 中没有具体数字的（正则匹配）
  - steps >= 8 的复杂配方
  → 预计约 20-30% 条目需要精修（~5,000-8,000 条）

Phase 3: Opus 精修那批（¥15-40，可批量并发）
```

**总成本估算（代理价）：**
- Flash 全量：¥5-15
- Opus 精修 ~7,000 条：¥20-50
- **合计：¥25-65**，远低于 Stage4 全量成本

---

## 6. 执行脚本架构建议

### 6.1 目录结构

```
scripts/
  stage5_stepb_l0_bind.py      ← 主脚本
  stage5_stepb_quality.py      ← 质控：检查 JSON 合规 + 词表合规
  stage5_stepb_opus_review.py  ← Opus 精修批次
```

### 6.2 主脚本架构（stage5_stepb_l0_bind.py）

```python
"""
Stage5 Step B: L0 绑定 + 4 字段补标
输入: ~/l0-knowledge-engine/output/l2b/recipes_stepa/*.jsonl
输出: ~/l0-knowledge-engine/output/l2b/recipes_stepb/*.jsonl
"""

import asyncio
import json
from pathlib import Path

SYSTEM_PROMPT = """..."""  # 见 Section 3.1

USER_TEMPLATE = """..."""   # 见 Section 3.2

VALID_COURSES = {"appetizer","soup","main","side","dessert","snack","beverage","sauce","bread"}
VALID_TEMPS = {"hot","warm","cold","room_temp","frozen"}
VALID_FLAVORS = {"sweet","sour","salty","bitter","umami","spicy","smoky","herbal","rich","light","tangy","nutty","floral","earthy"}
VALID_DIETARY = {"vegetarian","vegan","gluten_free","dairy_free","nut_free","egg_free","shellfish_free","halal","kosher","low_carb"}
VALID_DOMAINS = {"protein_science","carbohydrate","lipid_science","fermentation","food_safety","water_activity","enzyme","color_pigment","equipment_physics","maillard_caramelization","oxidation_reduction","salt_acid_chemistry","taste_perception","aroma_volatiles","thermal_dynamics","mass_transfer","texture_rheology"}

async def process_batch(recipes: list[dict], concurrency: int = 4) -> list[dict]:
    """Flash 并发批处理，4 并发"""
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [annotate_recipe(r, semaphore) for r in recipes]
    return await asyncio.gather(*tasks, return_exceptions=True)

async def annotate_recipe(recipe: dict, semaphore: asyncio.Semaphore) -> dict:
    async with semaphore:
        prompt = USER_TEMPLATE.replace("{{RECIPE_JSON}}", json.dumps(recipe, ensure_ascii=False))
        response = await call_api(model="qwen-plus", system=SYSTEM_PROMPT, user=prompt)
        annotation = parse_and_validate(response)
        return {**recipe, **annotation}

def parse_and_validate(raw: str) -> dict:
    """解析 JSON，验证词表合规，标记违规字段"""
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        return {"step_b_error": "json_parse_failed", "raw": raw[:200]}

    errors = []
    if data.get("course") not in VALID_COURSES:
        errors.append(f"invalid_course: {data.get('course')}")
    for tag in data.get("flavor_tags", []):
        if tag not in VALID_FLAVORS:
            errors.append(f"invalid_flavor: {tag}")
    for tag in data.get("dietary_tags", []):
        if tag not in VALID_DIETARY:
            errors.append(f"invalid_dietary: {tag}")
    for pt in data.get("key_science_points", []):
        for d in pt.get("l0_domains", []):
            if d not in VALID_DOMAINS:
                errors.append(f"invalid_domain: {d}")

    if errors:
        data["step_b_validation_errors"] = errors
    return data

def needs_opus_review(recipe: dict) -> bool:
    """识别需要 Opus 精修的条目"""
    pts = recipe.get("key_science_points", [])
    # 包含高精度域
    complex_domains = {"protein_science", "fermentation", "enzyme"}
    for pt in pts:
        if set(pt.get("l0_domains", [])) & complex_domains:
            return True
    # parameter_boundary 没有数字
    for pt in pts:
        boundary = pt.get("parameter_boundary", "")
        if boundary and not any(c.isdigit() for c in boundary):
            return True
    # 步骤超过 8
    if len(recipe.get("steps", [])) >= 8:
        return True
    return False

# 断点续跑：用 recipe_id 做已完成记录
# 输出：每本书一个 output JSONL，实时 flush
# 日志：tqdm 进度 + 错误计数
```

### 6.3 运行参数

```bash
# Flash 全量跑
python scripts/stage5_stepb_l0_bind.py \
  --input ~/l0-knowledge-engine/output/l2b/recipes_stepa/ \
  --output ~/l0-knowledge-engine/output/l2b/recipes_stepb/ \
  --model qwen-plus \
  --concurrency 4 \
  --batch-size 100

# 质控
python scripts/stage5_stepb_quality.py \
  --input ~/l0-knowledge-engine/output/l2b/recipes_stepb/ \
  --report ~/l0-knowledge-engine/output/l2b/stepb_qc_report.json

# Opus 精修（质控后筛选的需精修条目）
python scripts/stage5_stepb_opus_review.py \
  --input ~/l0-knowledge-engine/output/l2b/stepb_needs_review.jsonl \
  --output ~/l0-knowledge-engine/output/l2b/stepb_opus_patched.jsonl \
  --model claude-opus-4-6 \
  --concurrency 2
```

### 6.4 API 配置

```python
# 直连灵雅 API（proxy :3001 已删除，决策 D43），trust_env=False
API_CONFIG = {
    "endpoint": "${L0_API_ENDPOINT}/v1/chat/completions",  # 灵雅直连
    "headers": {
        "Authorization": "Bearer sk-fS8bLdyWiCys5lIHRrnzJAXWLYViLZ5N4ovEdzT6bdYUasF3",
        "Content-Type": "application/json"
    },
    "trust_env": False  # 绕过本机代理 127.0.0.1:7890
}
```

---

## 7. 质控标准

| 检查项 | 通过条件 |
|---|---|
| JSON 解析成功率 | ≥98% |
| course 词表合规 | 100%（违规记录待人工复查） |
| flavor_tags 词表合规 | 100% |
| key_science_points 非空率 | ≥70%（过多空说明 prompt 没识别到科学要点） |
| parameter_boundary 含数字率 | ≥60%（数字越多说明精度越高） |
| l0_domains 平均数量 | 1.5-3.0（太少说明绑定不够，太多说明乱标） |

---

## 8. 已知风险和缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| Flash 给 protein_science 配方的温度边界不精确 | 中 | Opus 精修批次兜底 |
| 词表外词汇（如 "savory" 不在 flavor_tags）| 低 | parse_and_validate() 捕获，人工审查 top-N |
| 步骤引用错误（step_ref 指向不存在的步骤） | 低 | 质控脚本检查 step_ref 范围 |
| 极简配方给出冗余 science_points | 低 | Prompt 明确"trivially simple = empty array" |
| API 限速导致大量 429 | 中 | 指数退避 + 断点续跑 |
