# OpenClaw 4-Skill 路线图
> 版本: 2026-04-15 | 状态: 配置完成，待首跑

---

## Skill A — 定量公式参数提取 (Track A)

**模型**: claude-opus-4-6 via aigocode  
**OCR**: PaddleOCR VL 1.5 (layout-parsing API)  
**输入**: engineering_textbook PDF (8本 P0 + 6本 P1 + 5本 P2)  
**输出**: ParameterSet JSONL

### Pipeline 流程
```
PDF → PaddleOCR VL 1.5 (layout-parsing) → markdown pages
  → Opus 4.6 逐页提取 → ParameterSet JSON
  → QC 校验 → 写入 output/{book_id}/track_a/
```

### 提取 Schema: ParameterSet
```json
{
  "mother_formula": "Arrhenius",        // 28个 MotherFormula 之一
  "formula_id": "MF-T03",
  "parameter_name": "Ea",               // 参数名
  "value": 127000,                      // 数值
  "unit": "J/mol",                      // 单位
  "conditions": {                       // 测量条件
    "substrate": "whey protein",
    "pH": 7.0,
    "temperature_range": "60-90°C"
  },
  "source": {
    "book": "van_boekel_kinetic_modeling",
    "chapter": "Ch8",
    "page": 234,
    "table": "Table 8.3"
  },
  "confidence": "high",                 // high/medium/inferred
  "notes": "Maillard reaction in milk systems"
}
```

### System Prompt 核心指令
```
你是食品工程参数提取器。从给定页面中提取所有可量化的科学参数。
每个参数必须绑定到 28 个 MotherFormula 之一。
输出纯 JSON 数组。关注：
- 表格中的数值（温度、时间、速率常数、活化能等）
- LaTeX 公式中的系数和指数
- 图表标注中的临界值
- 参数的适用条件（基质、pH、温度范围）
```

### P0 书目 (Wave 1)
1. van_boekel_kinetic_modeling (79页, 已OCR通过)
2. rao_engineering_properties
3. singh_food_engineering
4. mc_vol1-4 (已有 L0, 现提参数)

---

## Skill B — L2b 食谱提取 (Track B)

**模型**: gemini-3-flash-preview via Google API  
**OCR**: PaddleOCR VL 1.5  
**输入**: science+recipe / recipe_only 书 PDF  
**输出**: Recipe JSONL (Stage5 格式)

### Pipeline 流程
```
PDF → PaddleOCR VL 1.5 → markdown pages
  → Flash 逐页识别食谱 → Recipe JSON
  → Step B 标注 (course/flavor/L0绑定)
  → QC → output/{book_id}/stage5/
```

### 提取 Schema: Recipe
```json
{
  "recipe_id": "book_page_001",
  "name": "Braised Short Ribs",
  "name_zh": "红烧牛小排",
  "recipe_type": "main",
  "ingredients": [
    {"name": "beef short ribs", "amount": "2 kg", "prep": "cut into 5cm pieces"},
    {"name": "red wine", "amount": "500 ml"}
  ],
  "steps": [
    {"step": 1, "text": "Season ribs with salt, rest 1 hour", "time_min": 60},
    {"step": 2, "text": "Sear in cast iron at 230°C until deep brown", "temp_c": 230}
  ],
  "equipment": ["cast iron dutch oven", "probe thermometer"],
  "course": "main",
  "serving_temp": "hot",
  "flavor_tags": ["rich", "umami", "earthy"],
  "dietary_tags": ["gluten_free"],
  "key_science_points": [
    {
      "l0_domain": "maillard_caramelization",
      "decision_point": "High-heat sear creates Maillard crust before braising",
      "confidence": "high"
    },
    {
      "l0_domain": "protein_science",
      "decision_point": "Collagen → gelatin conversion at 80°C over 3 hours",
      "confidence": "high"
    }
  ],
  "source": {"book": "cooking_for_geeks", "page": 156}
}
```

### 已有基线
- 29,085 条食谱 (63本书)
- 新书继续用此 schema 扩充

---

## Skill C — L2a 食材参数采集 (Track C)

**模型**: gemini-3-flash-preview via Google API  
**OCR**: PaddleOCR VL 1.5  
**输入**: 书籍 + USDA Foundation Foods + FooDB  
**输出**: IngredientAtom JSONL

### Pipeline 流程
```
PDF/数据源 → PaddleOCR or API 采集 → raw ingredients
  → Flash 归一化 (Canonical Atom)
  → Flash 参数蒸馏 → IngredientAtom JSON
  → L0 domain tag 绑定 → QC
  → output/l2a/atoms/
```

### 提取 Schema: IngredientAtom
```json
{
  "atom_id": "chicken_breast_raw",
  "canonical_name": "Chicken Breast",
  "canonical_name_zh": "鸡胸肉",
  "wikidata_qid": "Q1535106",
  "usda_fdc_id": 171077,
  "foodb_id": "FDB003456",
  "category": "poultry",
  "processing_states": {
    "raw": {
      "moisture_pct": 74.0,
      "protein_pct": 23.1,
      "fat_pct": 1.2,
      "pH": 5.9,
      "water_activity": 0.99
    },
    "cooked_pan_seared": {
      "moisture_pct": 62.0,
      "protein_pct": 31.0,
      "fat_pct": 3.6,
      "internal_temp_c": 74
    }
  },
  "varieties": [
    {"name": "Free-range", "origin": "generic", "note": "Lower fat, firmer texture"},
    {"name": "Cornish", "origin": "UK", "note": "Smaller bird, tender"}
  ],
  "seasons": ["year_round"],
  "l0_domain_tags": ["protein_science", "thermal_dynamics", "food_safety"],
  "sensory_profile": {
    "texture_raw": "soft, elastic",
    "flavor_cooked": "mild, savory"
  },
  "source": "USDA Foundation Foods + Modernist Cuisine Vol3"
}
```

### 已有基线
- Pilot 75 种完成
- R1 蒸馏 21,266 atoms
- R2 深度蒸馏 21,422 atoms (进行中)

---

## Skill D — FT 风味目标 + L6 翻译 (Track D)

**模型**: claude-opus-4-6 via aigocode  
**OCR**: PaddleOCR VL 1.5  
**输入**: aesthetic_culture 书 + 粤菜专业文献  
**输出**: FlavorTarget JSONL + L6 Glossary JSONL

### Pipeline 流程
```
PDF → PaddleOCR VL 1.5 → markdown pages
  → Opus 4.6 提取审美词-基质-目标状态三元组
  → L0 domain 绑定 + 参数范围标注
  → output/ft/targets/ + output/l6/glossary/
```

### 提取 Schema: FlavorTarget
```json
{
  "ft_id": "crispy_chicken_skin",
  "aesthetic_word": "脆",
  "aesthetic_word_en": "crispy",
  "matrix_type": "Type B: 胶原蛋白/脂肪基质",
  "substrate": "chicken_skin",
  "target_states": {
    "water_activity": {"target": 0.3, "range": [0.2, 0.4]},
    "glass_transition_temp_c": {"target": 45, "note": "below Tg = glassy = crispy"},
    "surface_temp_c": {"target": 180, "range": [170, 200]},
    "thickness_mm": {"target": 1.5, "range": [1.0, 2.5]}
  },
  "spatial_gradient": {
    "crust": {"Aw": 0.3, "state": "glassy"},
    "core": {"Aw": 0.95, "state": "juicy"}
  },
  "l0_domains": ["water_activity", "texture_rheology", "maillard_caramelization"],
  "source": "粤菜烧味工艺 + Modernist Cuisine Vol2"
}
```

### 提取 Schema: L6 Glossary
```json
{
  "term_zh": "镬气",
  "term_en": "wok hei",
  "pinyin": "wok6 hei3",
  "definition_zh": "用猛火大镬快速翻炒产生的焦香气息",
  "definition_en": "Smoky char-flavor from high-heat wok tossing",
  "l0_domains": ["maillard_caramelization", "aroma_volatiles", "thermal_dynamics"],
  "related_ft": ["ft_smoky_char", "ft_wok_aroma"],
  "context": "粤菜炒锅技法核心概念",
  "source": "粤菜师傅工程教材"
}
```

---

## 通用 OCR 流程 (所有 Skill 共用)

```python
# PaddleOCR VL 1.5 API 调用
API_URL = "https://t1m0ybsdk3d2hcyc.aistudio-app.com/layout-parsing"
TOKEN = "6c85d029b67e3ea07bd94338dc0f27ce8c54318f"

payload = {
    "file": base64_encoded_pdf,
    "fileType": 0,  # 0=PDF, 1=Image
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useChartRecognition": False
}
# Response: layoutParsingResults[].markdown.text → per-page markdown
```

## API 总览

| API | Endpoint | 用途 |
|---|---|---|
| aigocode | https://api.aigocode.com/v1/messages | Skill A/D (Opus 4.6) |
| Lingya Gemini | `${L0_API_ENDPOINT}/v1/messages` | Skill B/C (Flash) |
| PaddleOCR | https://t1m0ybsdk3d2hcyc.aistudio-app.com/layout-parsing | 所有 Skill OCR |
| 灵雅 (备用) | https://api.lingyaai.cn/v1/messages | 充值后可替代 aigocode |
