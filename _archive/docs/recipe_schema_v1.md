# 配方Schema v1 — ISA-88三段分离

> 母对话定义，agent不许修改
> 2026-03-16

---

## SubRecipe（原子单元）

判定标准：有独立的formula（自己的食材+自己的调味）= SubRecipe

```json
{
  "sub_recipe_id": "SR-xxx",
  "name": "xxx",
  "name_en": "xxx",
  "category": "xxx",

  "process": [
    {"n": 1, "action": "xxx", "text": "自然语言描述"}
  ],

  "formula": {
    "ingredients": [
      {"item": "xxx", "qty": 0, "unit": "g", "role": "xxx"}
    ],
    "params": {}
  },

  "equipment": [],
  "sub_components": [{"ref": "SR-xxx", "role": "xxx"}],
  "tags": [],
  "source": {"book": "xxx"}
}
```

### 三段分离

| 段 | 内容 | 独立变化 |
|----|------|---------|
| process | 做什么（动作序列，自然语言） | 换工艺 = 新SubRecipe |
| formula | 配多少（食材+精确用量+参数） | 换食材/换比例只改这里 |
| equipment | 用什么（设备列表） | 换设备只改这里 |

### ingredients字段

| 字段 | 必填 | 说明 |
|------|------|------|
| item | ✅ | 标准化食材名（英文snake_case） |
| qty | ✅ | 数字，LLM必须转换模糊量词 |
| unit | ✅ | g/ml/pc/sprig/cm 等 |
| role | ✅ | main/seasoning/fat/acid/aromatics/liquid/thickener/emulsifier/cure/spice/color/umami/herb/binder/flavor/condiment |
| qualifier | 可选 | "to_taste"/"approx"（仅当qty=null时） |

### LLM蒸馏规则

1. 模糊量词必须转数字：`Juice of ½ lemon` → `{"item":"lemon_juice","qty":15,"unit":"ml"}`
2. 只有 "to taste" 类才允许 qty=null
3. 单位统一用公制（g/ml/cm），teaspoon→5ml，tablespoon→15ml，cup→240ml，oz→28g，inch→2.5cm

---

## Recipe（组装层）

```json
{
  "recipe_id": "RCP-xxx",
  "name": "xxx",
  "name_en": "xxx",
  "category": "xxx",
  "cuisine": "xxx",
  "source": {"book": "xxx", "page": null},

  "components": [
    {"ref": "SR-xxx", "role": "main", "order": 1}
  ],

  "main_ingredients": [
    {"item": "xxx", "qty": 0, "unit": "g"}
  ],

  "garnish": [
    {"item": "xxx", "qty": 0, "unit": "g"}
  ],

  "refs": [
    {"item": "xxx", "ref": "SR-xxx"}
  ],

  "assembly": [
    {"n": 1, "text": "xxx"}
  ],

  "chef_notes": []
}
```

### 四种食材来源

| 字段 | 定义 | 判定标准 |
|------|------|---------|
| components[] | SubRecipe引用 | 有独立formula的 |
| main_ingredients[] | 简单处理食材 | 需处理但没独立formula（煮熟、回温） |
| garnish[] | 零操作装饰 | 没有任何操作过程 |
| refs[] | 外部SubRecipe引用 | 有独立配方但定义在别处（书末Basic Recipes） |

### component role词表

```
main            主料（鱼、肉、主蛋白）
carrier         载体（馒头、饭、面、面包）
accompaniment   配菜/平衡（沙拉、酸菜、蔬菜）
sauce           酱汁/汁液
marinade        腌渍料
seasoning       调味组件
filling         馅料
base            基底（高汤、蛋奶酱）
```

### 蒸馏顺序

一本书的蒸馏顺序：
1. 先蒸馏 Basic Recipes / Appendix 章节 → 建共享SubRecipe库
2. 再蒸馏正文菜式 → Recipe组装层引用已有SubRecipe

---

## 验证记录

| 配方 | 来源 | 复杂度 | 结果 |
|------|------|--------|------|
| Corsu Vecchiu with Carrot Salad | French Laundry | 简单 | ✅ |
| Tilefish Steamed with Millet | Tsuji Japanese Cooking | 中等 | ✅ |
| Sunflower Barigoule | Eleven Madison Park | 极复杂（10个交叉引用） | ✅ |
| 盐曲熟成鲈鱼 | 手写 | 中等（多天工序） | ✅ |
| 叉烧汉堡包 | 手写 | 中等（嵌套子配方） | ✅ |
