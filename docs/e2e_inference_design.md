# 端到端推理链路设计 — 架构验证

> 文档角色：架构师分析 + 数据缺口评估 + Schema 补丁建议
> 日期：2026-03-26
> 版本：v1

---

## 0. 目的

用 4 个真实用户查询，走完整推理链路，验证当前七层架构（L0/L2a/L2b/FT/L6/L3）能否支撑端到端输出。发现缺口，提出最小可行补丁。

---

## 1. 查询一：南方酸辣海鲜冷前菜

### 用户输入

> "我需要制作一个南方的，酸辣口味的，春天的海鲜类冷前菜"

---

### 1.1 查询拆解

| 维度 | 原始词 | 系统语言 | 谁负责翻译 |
|------|--------|----------|-----------|
| 地域 | 南方 | 广东/福建/浙江/海南/东南亚（华南圈） | L6 |
| 口味 | 酸辣 | sour (pH < 4.0) + spicy (capsaicin / allicin) | L6 + FT |
| 季节 | 春天 | peak_months [3,4,5] | L2a |
| 食材 | 海鲜 | category = seafood_* | L2a |
| 菜式 | 冷前菜 | serving_temp ≤ 12°C, portion_size = appetizer, course = starter | FT + L2b |
| 烹饪状态 | 冷 | no active heat at service, food_safety: 0-4°C hold or ceviche-type acid denaturation | L0 |

**地域展开（L6 南方映射表）：**
- 广东：白灼、泡椒、姜葱 → 偏鲜甜底，酸辣需强化
- 福建：沙茶、红曲 → 酸辣元素弱，需外部引入
- 浙江：醋鱼系、酸辣汤底 → 天然酸辣基因
- 海南/东南亚：青柠、鱼露、辣椒 → 最接近 ceviche 逻辑
- **推荐聚焦**：粤菜底色（用户背景）× 东南亚酸辣技法（天然契合）

**酸辣展开（FT 量化目标）：**
- 酸：pH 目标 3.2–3.8（柠檬酸 / 米醋 / 青柠汁）
- 辣：Scoville 1,000–5,000（青辣椒 / 小米椒），不能掩盖海鲜鲜味
- 冷前菜里酸是主调，辣是点缀——比例 acid:spice ≈ 7:3

---

### 1.2 推理链路

```
用户输入
  │
  ▼
[L6 翻译层]
  "南方" → [广东, 福建, 浙江, 海南, 东南亚华南圈]
  "酸辣" → sour(pH 3.2-3.8) + spicy(Scoville 1000-5000)
  "冷前菜" → serving_temp ≤ 12°C, course=starter, portion=60-80g
  "春天" → peak_months [3,4,5]
  "海鲜" → category in [seafood_crustacean, seafood_mollusk, seafood_fish]
  │
  ▼
[L2a 食材筛选]
  查询：peak_months 包含 [3,4,5]
       AND category in seafood_*
       AND region in [广东, 福建, 浙江, 海南]

  候选食材：
  - 白虾/基围虾（peak_months: 3-6，广东湛江）
  - 生蚝（peak_months: 11-4，秋冬春）
  - 花蛤（peak_months: 3-5，福建/浙江）
  - 墨鱼（peak_months: 4-6，广东沿海）
  - 石斑鱼（peak_months: 3-5，南海）

  → 按 importance_score 降序排列
  → 输出：前3-5个候选食材 + 各自 composition + flavor_profile + processing_states
  │
  ▼
[L0 科学原理锁定]
  触发域：protein_science, salt_acid_chemistry, food_safety, taste_perception

  关键原理（向量检索 or 图谱遍历）：
  - 柑橘酸使虾蛋白变性（ceviche 原理）：pH ≤ 3.5，20-30分钟完全变性
  - 冷菜食品安全：海鲜必须加热 ≥63°C 或酸 pH ≤ 4.0 充分时间才合规
  - 酸对鲜味的影响：pH 3.2-3.8 增强海鲜 IMP/GMP 释放，提升鲜感
  - 辣椒素与冷觉：TRPV1 受体在低温时灵敏度下降，冷菜需提升辣度
  - 质地：虾蛋白酸变性后质地比热变性更弹，但时间过长（>45min）变橡皮
  │
  ▼
[L2b 食谱检索]
  筛选条件：
  - main_ingredients 包含 seafood_*
  - 有 marinate + acid 操作（或 ceviche / aguachile 标签）
  - recipe_type = appetizer / cold_dish / starter
  - cuisine in [cantonese, southeast_asian, latin]  ← 类型最接近

  候选食谱（29,085条里检索）：
  - Thai-Style Shrimp Ceviche（已知存在）
  - 酸辣墨鱼（需验证是否存在）
  - 类 ceviche 类型食谱

  → 提取 steps + formula 作为参考框架
  │
  ▼
[FT 风味目标校验]
  输入：酸辣冷前菜 → 目标感官参数

  感官目标矩阵：
  - sourness: 4/5（主调）
  - spiciness: 3/5（点缀）
  - umami: 4/5（海鲜本底）
  - sweetness: 2/5（平衡酸）
  - texture_target: tender + slightly firm（蛋白适度变性）
  - aroma_target: 柑橘前调 + 海鲜本味 + 辣椒尾香

  验证 L2b 候选食谱的 flavor_profile 是否匹配 FT 目标
  │
  ▼
[L3 推理引擎]
  整合所有层输出，生成菜品方案：

  1. 选定食材：白虾（广东湛江，3-5月，活虾）
  2. 酸化剂：青柠汁 + 少量米醋（pH 3.3-3.5）
  3. 辣味来源：小米椒 + 姜（保留粤菜底色）
  4. 时间参数：腌制25-30分钟（L0约束：完全变性 + 不过熟）
  5. 辅料：香茅、鱼露、少许糖（调和酸辣，增鲜）
  6. 装盘：6-8只虾/份，冷盘呈现，配柑橘装饰
  │
  ▼
[L0 最终校验]
  - 食品安全：pH 3.3 × 30分钟 → 蛋白质完全变性 ✓
  - 风味平衡：酸主辣辅，IMP 鲜味增强 ✓
  - 季节合规：3-5月白虾品质最佳 ✓
  │
  ▼
输出：完整菜品方案
  名称：青柠腌白虾（粤式 Aguachile）
  食材 / 用量 / 步骤 / L0 科学注释 / 替换建议
```

---

### 1.3 数据缺口分析

#### a) L2a：春天 + 海鲜 + 南方 筛选

**当前 schema（任务书给出的版本）：**

```json
"varieties": [{
  "region": "广东湛江",
  "peak_months": [3, 4, 5, 6]
}]
```

**能不能筛？**

| 条件 | 字段 | 状态 | 问题 |
|------|------|------|------|
| peak_months [3,4,5] | varieties[].peak_months | ✅ 有字段 | Variety 是内嵌数组 → Neo4j 无法做 `WHERE peak_months IN [3,4,5]` 的高效查询 |
| region 南方 | varieties[].region | ⚠️ 有字段 | 是自由文本字符串，没有标准化地区分类，无法做 "南方" → [广东, 福建...] 的图谱级别过滤 |
| category seafood | atom.category | ✅ 有字段 | seafood_crustacean 等已定义 |
| 食品安全状态 | processing_states | ❌ 缺失 | 当前 schema 没有 processing_states → 无法判断哪些海鲜支持"酸变性/不需加热"的冷菜处理 |

**关键缺口**：
1. `varieties` 是内嵌 JSON 数组，Neo4j 图谱里无法高效按 `peak_months` 过滤 → **必须拆成 Variety 独立节点**（l2a_atom_schema_v2.md 第 2c 节已指出但未实施）
2. `region` 是自由文本，没有标准化的 geo_zone 字段 → 无法做 "南方" 聚合查询

#### b) L2b：冷前菜 + 酸辣 筛选

**当前 L2b schema（Stage5 提取）：**

```json
{
  "recipe_type": "main",
  "name": "Thai-Style Shrimp Ceviche",
  "ingredients": [{"item": "shrimp", "qty": 200, "unit": "g"}],
  "steps": [{"order": 1, "text": "用青柠汁腌制虾仁20分钟", "action": "marinate"}]
}
```

**能不能筛？**

| 条件 | 字段 | 状态 | 问题 |
|------|------|------|------|
| course = appetizer/starter | recipe_type | ⚠️ 有 recipe_type | 值域里有 "main"，但没有 "appetizer" / "cold_starter" 标准化值 |
| serving_temp = cold | 无 | ❌ 缺失 | 完全没有温度字段 |
| 酸辣 flavor_tag | 无 | ❌ 缺失 | 食谱没有风味标签，只能靠 steps 文本关键词推断 |
| 技法 = marinate + acid | steps[].action | ⚠️ 部分 | action 字段有 "marinate"，但没有 acid_type / pH 参数 |
| cuisine | cuisine | ✅ 有字段 | 但部分 L2b 条目 cuisine 为空 |

**关键缺口**：
1. `recipe_type` 值域不包含标准课序（appetizer/main/dessert/snack），无法区分前菜
2. `serving_temp_c` 完全缺失 → 无法区分冷菜 vs 热菜
3. 没有 `flavor_tags[]` → 只能靠 NLP 扫描 steps 文本，效率低、准确率低

#### c) FT 层缺失的影响

**直接影响：**

"酸辣" 是一个审美复合词，对应的量化参数（pH目标、Scoville范围、酸辣比例）目前无处定义。

不可替代的 FT 功能：

| FT 功能 | 降级方案 | 降级代价 |
|---------|---------|---------|
| 审美词 → 感官参数量化 | 规则字典 hardcode | 覆盖率低，新词无法处理 |
| 感官目标 → L2b 筛选条件 | 关键词搜索 steps 文本 | 漏召回率高（"腌制20分钟" ≠ "酸") |
| 多维感官目标的冲突检测 | 无法实现 | 输出食谱可能酸辣平衡失当 |
| 风味目标 × 食材参数匹配 | 无法实现 | 选食材时缺乏风味层约束 |

**最小可行 FT（见第 4 节）**

#### d) L6 层缺失的影响

**直接影响：**

"南方"、"春天"、"冷前菜" 这三个词都需要 L6 才能变成系统可处理的过滤条件。

| L6 功能 | 降级方案 | 降级代价 |
|---------|---------|---------|
| "南方" → 地区列表 | 规则字典 | 覆盖常见词，但 "岭南"/"华南"/"南粤" 等变体会漏 |
| "酸辣" → sour+spicy | 规则字典 | 基本覆盖，问题不大 |
| "冷前菜" → serving_temp + course | 规则字典 | 基本覆盖 |
| "春天海鲜" → 品种推荐 | 无，需 L2a 支撑 | L6 只是翻译，品种推荐是 L3 的事 |
| 粤菜术语识别 | 无法识别 "走地" / "靓" 等修饰词的含义 | 会丢失重要质量信号 |

**L6 缺失比 FT 缺失更容易降级处理**：大部分常见审美词可以先用规则字典 hardcode，系统依然可以跑通。

#### e) L0 在这个查询里的参与方式

L0 在这个查询里扮演三个角色：

**角色 1：安全守门人（不可绕过）**

```
L0 原理：pH ≤ 3.5 × 20-30分钟 → 虾蛋白完全变性（ceviche 安全原理）
L3 必须在输出前验证：用户选定的酸化剂 + 腌制时间 是否满足这个边界条件
如果用户说要腌 5 分钟，L3 必须拒绝或给出安全警告
```

**角色 2：参数优化器（提升输出质量）**

```
L0 原理：腌制时间超过 45 分钟 → 蛋白质过度变性 → 橡皮质地
L3 利用这条原理给出精确时间范围（25-35 分钟），而不是模糊的 "腌一会儿"
```

**角色 3：冷觉修正**

```
L0 原理：低温下 TRPV1 辣觉受体灵敏度下降
→ 冷菜里的辣椒用量需比热菜增加约 30%，才能达到相同主观辣度感知
L3 据此调整辣椒用量参数
```

这三个 L0 参与角色都依赖**运行时向量检索**找到具体原理，不能靠预埋字段 hardcode。

---

## 2. 查询二：和牛 A5 西冷最优处理方案

### 用户输入

> "我有一块和牛A5西冷，怎么做最能发挥它的价值？"

---

### 2.1 查询拆解

| 维度 | 原始词 | 系统语言 |
|------|--------|----------|
| 食材 | 和牛 A5 西冷 | wagyu_striploin, grade=A5, marbling=BMS12 |
| 目标 | 发挥价值 | 最大化感官体验（fat render + maillard + umami release） |
| 隐含约束 | 无 | 高价食材 → 不允许浪费 → 推理需加 "高价值食材保守策略" 标志 |

---

### 2.2 推理链路

```
用户输入
  │
  ▼
[L6] "和牛A5" → wagyu, grade=A5, BMS_score≥12; "西冷" → striploin
      "发挥价值" → maximize: fat_render_quality + maillard_crust + umami_perception
  │
  ▼
[L2a 食材参数]
  原子：wagyu_striploin
  关键参数：
  - fat_pct: 30-40%（A5级，BMS≥12）
  - MUFA比例：50%+（油酸为主，低熔点38-42°C）
  - 最优内部温度：50-54°C（rare-medium rare）→ 脂肪已流动，蛋白质未过熟
  - 超过65°C：脂肪流失，失去和牛特有"化口感"
  - 肌间脂肪（marbling）：热处理时自然渗透到肌肉纤维间隙
  │
  ▼
[L0 关键原理检索]
  域：lipid_science, maillard_caramelization, thermal_dynamics, taste_perception

  - 美拉德反应：140°C以上表面启动，需快速高温建立外壳
  - 脂肪熔点：和牛脂肪熔点38-42°C（低于普通牛脂肪55°C），体温即可融化
  - 热传导：厚切牛排需反向烹饪（reverse sear）或低温熟成确保中心均匀
  - 鲜味叠加：肌苷酸（IMP）在50-60°C释放峰值，配合脂肪鲜甜味（glutamate）
  │
  ▼
[L2b 食谱检索]
  筛选：wagyu / A5 + striploin + 高端技法
  候选：reverse sear、铁板烧、日式火炙、French sear
  提取参考做法 + 用量框架
  │
  ▼
[L3 推理引擎]
  策略选择：
  1. 厚度 ≥ 4cm → 推荐反向烹饪（低温烤箱50°C × 1小时 → 铸铁锅大火30秒/面）
  2. 厚度 2-3cm → 铸铁锅大火直接煎（每面60-90秒，静置5分钟）

  L0 约束应用：
  - 表面 Maillard：锅温 ≥ 230°C，时间 ≤ 90秒/面（否则内部过熟）
  - 内部目标：52°C（脂肪全融，蛋白质最嫩）
  - 静置：肌肉纤维弛豫，汁液重新分布（5-8分钟）
  │
  ▼
输出：处理方案 + 参数 + 替换建议
```

---

### 2.3 断点分析

| 环节 | 状态 | 问题 |
|------|------|------|
| L2a 查 wagyu_striploin | ❌ L2a 未建 | 无法获取 BMS 参数、脂肪熔点、最优温度 |
| L2b 查 wagyu 食谱 | ⚠️ 部分 | 29,085条里有西方高端食谱，但和牛专项可能稀少 |
| L0 查 lipid/maillard 原理 | ✅ 有 | 44,692条里这两个域覆盖率高 |
| "发挥价值" 意图理解 | ❌ FT 缺失 | 无法把 "发挥价值" 量化为感官目标 |
| 厚度 → 技法选择的推理 | ⚠️ L3 未建 | 逻辑需要 L3 推理引擎，当前不存在 |

**这个查询的主要断点：L2a 未建（食材参数空缺）+ L3 未建（推理逻辑空缺）**

L0 层反而是最完整的。如果 L2a 有数据，这个查询的核心推理链是可以跑通的。

---

## 3. 查询三：无麸质法式甜品台

### 用户输入

> "帮我设计一个无麸质的法式甜品台，8人份"

---

### 3.1 查询拆解

| 维度 | 原始词 | 系统语言 |
|------|--------|----------|
| 约束 | 无麸质 | gluten_free = true（排除含麸质食材） |
| 风格 | 法式 | cuisine = french, pastry/dessert 分类 |
| 规模 | 8人份 | yield = 8 portions |
| 类型 | 甜品台 | 多品种（4-6种不同甜品） |

---

### 3.2 推理链路

```
用户输入
  │
  ▼
[L6] "无麸质" → allergen_exclude: [wheat, barley, rye, oats]
     "法式甜品台" → cuisine=french, course=dessert, format=multi-item_display
     "8人份" → yield=8
  │
  ▼
[L2a 成分过滤]
  反向过滤：排除 allergens 包含 "wheat" 的原子
  保留：杏仁粉、米粉、玉米淀粉、可可、黄油、蛋、奶油、砂糖、覆盆子...

  关键食材可用性：
  - 马卡龙（杏仁粉 + 蛋白）→ 天然无麸质 ✓
  - 焦糖布丁 → 无麸质 ✓
  - 克拉芙缇 → 原版含面粉 → 需替换（杏仁粉替代）
  - 法式挞（pâte sucrée）→ 需无麸质面粉替代配方
  │
  ▼
[L0 原理检索]
  域：carbohydrate, texture_rheology, maillard_caramelization

  - 无麸质烘焙原理：缺乏麸质网络 → 结构弱 → 需胶体替代（黄原胶/瓜尔胶）
  - 杏仁粉替代面粉：高脂含量 → 产品更湿润 → 需减少液体 or 加热时间
  - 焦糖化：不受麸质影响，法式焦糖类甜品天然适合无麸质
  │
  ▼
[L2b 食谱检索]
  筛选：gluten_free=true + cuisine=french + recipe_type=dessert

  候选：
  - French Laundry / Alinea / EMP 等高端食谱里的无麸质选项
  - 马卡龙（天然无麸质，大概率在 29,085 条里存在）
  - 法式焦糖布丁（crème brûlée）
  │
  ▼
[L3 组合推理]
  目标：选 4-6 道，满足：
  1. 全部无麸质
  2. 口感多样（crispy/creamy/chewy/smooth）
  3. 法式审美（精致、层次、经典技法）
  4. 制作可分散完成（不是全部最后时刻制作）
  │
  ▼
输出：甜品台菜单 + 每道食谱 + 制作时间轴
```

---

### 3.3 断点分析

| 环节 | 状态 | 问题 |
|------|------|------|
| L2a 过敏原过滤 | ⚠️ L2a 未建 | `allergens` 字段在 schema 里设计了但数据未建 |
| L2b gluten_free 标签 | ❌ 缺失 | 当前 L2b schema 没有 `dietary_tags[]` 字段 |
| L0 无麸质烘焙原理 | ✅ 有 | Professional Baking 覆盖 |
| 多品种组合推理 | ❌ L3 未建 | 需要推理引擎做组合优化 |
| 8人份 yield 换算 | ⚠️ 部分 | L2b 食谱有 yield 字段但不标准化 |

**最大缺口：L2b 没有 `dietary_tags[]`（gluten_free / dairy_free / vegan 等）**

这是一个高频用户需求，靠扫描 steps 文本无法可靠地判断是否真的无麸质。

---

## 4. 查询四：广东客人粤菜宴会 500/人

### 用户输入

> "广东客人来了，设计一桌粤菜宴会，预算人均500"

---

### 4.1 查询拆解

| 维度 | 原始词 | 系统语言 |
|------|--------|----------|
| 用户 | 广东客人 | preference: cantonese, authentic_style=high |
| 风格 | 粤菜宴会 | cuisine=cantonese, format=banquet, course_sequence=traditional_cantonese |
| 预算 | 人均500 | cost_per_head ≤ 500 CNY（假设10人桌 = 5000总预算） |
| 隐含 | 宴会 | 8-10道菜，冷盘+热菜+汤+主食+甜品 序列 |

---

### 4.2 推理链路

```
用户输入
  │
  ▼
[L6] 粤菜宴会结构解析：
  标准粤菜宴席（10道）：
  - 大拼盘（冷荤）× 1
  - 热炒 × 3-4（头菜通常为整鸡/整鱼）
  - 海鲜 × 1-2
  - 高汤 × 1
  - 主食（炒饭/炒面/肠粉）× 1
  - 甜品 × 1（糕点/甜汤）

  预算分配（经验值）：
  - 头菜（整鸡/乳猪）：20-25%
  - 海鲜：30-35%
  - 热炒：25%
  - 汤/主食/甜品：15-20%
  │
  ▼
[L2a 食材成本过滤]
  price_tier 字段：
  - 人均500，海鲜预算 ≈ 150-175/人
  - 可用食材：mid-tier seafood（石斑、花蛤、墨鱼）而非超高端（龙虾、鲍鱼）
  - 主蛋白：整鸡（清远鸡 or 走地鸡，price_tier=3）

  季节过滤（当前3月）：
  - 春季食材：春笋、马蹄、嫩姜、春蚬
  │
  ▼
[L0 粤菜原理]
  域：protein_science, thermal_dynamics, taste_perception, maillard_caramelization

  - 白灼（bai zhuo）原理：沸腾水95°C快速过熟，保持最短烹饪时间 → 最大保留鲜味
  - 清蒸整鱼/整鸡：蒸汽传热均匀，蛋白质在70-75°C熟成，保持嫩滑
  - 粤菜"镬气"（wok hei）：铁锅高温1000°C以上瞬间Maillard + 美拉德，是粤式炒菜核心
  - 高汤（清汤 vs 奶汤）：长时间低温萃取（胶原蛋白 / 氨基酸），不同于法式基础高汤
  │
  ▼
[L2b 食谱检索]
  筛选：cuisine=cantonese + 宴席菜式
  候选：
  - 白切鸡（或清远鸡白斩）
  - 清蒸石斑鱼
  - 椒盐濑尿虾
  - 老鸡煲汤
  - 炒时蔬

  提取参考配方框架
  │
  ▼
[FT 风味目标]
  广东客人的风味期望（L6 + FT 协作）：
  - "鲜" 是核心（umami 5/5）
  - 不喜欢过度调味、重口、糊化
  - "镬气" 是判断水准的标志
  - 整鸡整鱼上桌是面子体现（presentation 重要）
  │
  ▼
[L3 菜单编排]
  优化目标：
  1. 预算达标（≤ 500/人）
  2. 课序标准（冷→热→汤→主食→甜品）
  3. 烹调技法多样（白灼/清蒸/炒/炖汤不重复）
  4. 主材不重复（鸡≠鱼≠虾≠蔬菜）
  5. 粤菜审美（鲜甜底色，不掩盖食材本味）
  │
  ▼
输出：完整宴席菜单 + 每道食谱摘要 + 预算分解 + 操作时间轴
```

---

### 4.3 断点分析

| 环节 | 状态 | 问题 |
|------|------|------|
| L6 粤菜宴会结构解析 | ❌ L6 未建 | "大拼盘/头菜/例汤" 等粤语宴席词汇无法标准化 |
| L2a price_tier 过滤 | ❌ L2a 未建 | 无食材成本数据 |
| L2a 季节食材 | ❌ L2a 未建 | 无 peak_months 数据 |
| L0 粤菜技法原理 | ⚠️ 部分 | phoenix_claws（phoenix_claws 书）还未处理，粤菜专项L0偏少 |
| L2b 粤菜宴席食谱 | ⚠️ 部分 | 现有 29,085 条以西方高端食谱为主，粤菜专项少 |
| 预算约束推理 | ❌ L3 未建 | 价格约束需推理引擎 |
| 粤菜审美验证 | ❌ FT 未建 | "鲜甜" 等粤菜风味目标没有量化 |

**这个查询是最难的**：同时需要 L6（粤语宴席术语）+ L2a（成本+季节）+ L2b（粤菜食谱）+ FT（粤菜审美）+ L3（菜单组合优化）。4层都未建，只有 L0 部分可用。

---

## 5. 综合缺口清单

### 5.1 L2a Schema 缺口（优先级排序）

| # | 缺口 | 影响查询 | 优先级 |
|---|------|---------|--------|
| 1 | `varieties` 必须拆成独立 Neo4j 节点，不能内嵌数组 | 查询1（season/region 过滤） | P0 |
| 2 | `region` 字段需要标准化 geo_zone（不能是自由文本） | 查询1、4 | P0 |
| 3 | `processing_states` 字段缺失 | 查询1（冷菜安全判断） | P0 |
| 4 | `allergens[]` 字段缺失 | 查询3（无麸质过滤） | P0 |
| 5 | `price_tier` 字段缺失 | 查询4（预算约束） | P1 |
| 6 | `peak_season_quality_notes` 缺失（为什么春天好） | 查询1 | P2 |

### 5.2 L2b Schema 缺口（优先级排序）

| # | 缺口 | 影响查询 | 优先级 |
|---|------|---------|--------|
| 1 | `course` 字段缺失（appetizer/main/soup/dessert） | 查询1、3、4 | P0 |
| 2 | `serving_temp_c` 字段缺失 | 查询1（冷菜判断） | P0 |
| 3 | `dietary_tags[]` 缺失（gluten_free/dairy_free/vegan/kosher） | 查询3 | P0 |
| 4 | `flavor_tags[]` 缺失（sour/spicy/rich/light...） | 查询1、4 | P1 |
| 5 | `recipe_type` 值域不完整 | 查询1、3 | P1 |
| 6 | `yield_persons` 不标准化 | 查询3（8人份换算） | P1 |
| 7 | `primary_technique[]` 缺失（marinade/steam/fry...） | 查询1（技法筛选） | P1 |

### 5.3 连接缺口

| # | 缺口 | 影响 |
|---|------|------|
| 1 | L2a → L2b 的食材-食谱关系不在图谱里 | 无法从食材反查适合的食谱 |
| 2 | L2b → L0 的关键科学决策点未建（Step B 待做） | 食谱没有 L0 约束注释 |
| 3 | L2a Variety 节点未独立 → 无法做图谱级别的地域/季节查询 | |

---

## 6. Schema 补丁建议

### 6.1 L2a 最小补丁（3个必改字段）

**补丁 A：region 标准化**

```json
// 当前（有问题）
"varieties": [{"region": "广东湛江"}]

// 补丁后（在 Variety 节点上）
{
  "variety_id": "shrimp_white_guangdong",
  "region_zh": "广东湛江",
  "geo_zone": "south_china",          // 新增：标准化地理区域
  "geo_province": "guangdong",         // 新增：省级
  "coordinates": [21.2, 110.3]        // 已有
}
```

标准化 geo_zone 词表（12个区域）：
```
south_china    (广东/广西/海南)
southeast_china (福建/浙江/上海)
east_china     (江苏/山东)
north_china    (北京/天津/河北)
southwest_china (四川/贵州/云南)
central_china  (湖南/湖北)
northeast_china (黑龙江/吉林/辽宁)
northwest_china (陕西/甘肃/新疆)
southeast_asia  (泰国/越南/马来西亚)
japan          (日本)
europe         (法国/意大利...)
other
```

**补丁 B：processing_states 字段（添加到 Ingredient 节点）**

```json
{
  "atom_id": "shrimp_white",
  "processing_states": [
    {
      "state_id": "shrimp_white_live",
      "state_type": "live",
      "ph_range": [6.8, 7.2],
      "water_activity": 0.99,
      "cold_dish_compatible": true,     // 新增：是否适合冷菜
      "acid_denature_compatible": true, // 新增：是否支持酸变性（ceviche 类）
      "min_safe_acid_time_min": 20,     // 新增：酸变性最短安全时间
      "min_safe_ph": 3.5,               // 新增：最低安全 pH
      "heat_required": false            // 新增：是否必须加热处理
    },
    {
      "state_id": "shrimp_white_frozen",
      "state_type": "frozen_thawed",
      "cold_dish_compatible": false,    // 解冻虾不建议直接酸腌
      "heat_required": true
    }
  ]
}
```

**补丁 C：allergens 字段（添加到 Ingredient 节点）**

```json
{
  "allergens": ["shellfish", "crustacean"],  // 标准化 14 大过敏原词表
  "allergen_notes": "虾属于甲壳类过敏原，与蟹/龙虾交叉反应"
}
```

---

### 6.2 L2b 最小补丁（4个必改字段）

需要在 Stage5 Step A 的 prompt 里追加提取这些字段，或通过后处理 LLM 批量补充现有 29,085 条。

**补丁 D：course + serving_temp_c**

```json
{
  "recipe_id": "RCP-xxx",
  "course": "appetizer",          // 新增：appetizer/soup/main/side/dessert/snack/bread
  "serving_temp_c": 8,            // 新增：null = 不限，0-12 = 冷菜，50+ = 热菜
  "serving_temp_type": "cold"     // 新增：cold/warm/hot/room_temp
}
```

**补丁 E：dietary_tags[]**

```json
{
  "dietary_tags": ["gluten_free", "dairy_free"]
  // 词表：gluten_free / dairy_free / egg_free / nut_free / vegan /
  //       vegetarian / kosher / halal / low_carb / low_fat
}
```

**补丁 F：flavor_tags[] + primary_technique[]**

```json
{
  "flavor_tags": ["sour", "spicy", "umami", "light"],
  // 词表：sour/spicy/sweet/salty/bitter/umami/rich/light/smoky/fermented

  "primary_technique": ["marinate", "acid_cure"],
  // 词表：boil/steam/fry/saute/roast/braise/marinate/acid_cure/
  //       smoke/ferment/cure/raw/blend/bake
}
```

**补丁 G：yield 标准化**

```json
{
  "yield": {
    "persons": 4,           // 新增：标准份人数
    "portions": 4,          // 新增：份数
    "total_weight_g": 800   // 新增：总重量（可选）
  }
}
```

---

## 7. FT 风味目标库最小可行设计

目标：能支撑上述 4 个查询，不求完整，求可用。

### 7.1 FT 的两个核心功能

1. **审美词 → 感官参数矩阵**：把 "酸辣"、"鲜甜"、"清淡" 这类词翻译成可测量参数
2. **感官参数 → 食谱筛选条件**：把参数矩阵变成 L2b 查询的 WHERE 条件

### 7.2 FT 节点设计（最小版）

```json
{
  "ft_id": "sour_spicy",
  "name_zh": "酸辣",
  "name_en": "sour-spicy",
  "aliases": ["酸辣口", "酸辣风格"],

  "sensory_params": {
    "sourness": {"target": 4, "min": 3, "max": 5, "scale": "1-5"},
    "spiciness": {"target": 3, "min": 2, "max": 4, "scale": "1-5"},
    "sweetness": {"target": 1, "min": 0, "max": 2, "scale": "1-5"},
    "umami": {"target": 3, "min": 2, "max": 5, "scale": "1-5"}
  },

  "physicochemical_params": {
    "ph_target": 3.5,
    "ph_range": [3.2, 3.8],
    "scoville_target": 2000,
    "scoville_range": [1000, 5000]
  },

  "acid_sources": ["lime_juice", "rice_vinegar", "lemon_juice", "tamarind"],
  "spice_sources": ["fresh_chili", "dried_chili", "ginger", "white_pepper"],

  "l2b_filter_hints": {
    "flavor_tags_include": ["sour", "spicy"],
    "flavor_tags_exclude": ["rich", "creamy"],
    "primary_technique_include": ["marinate", "acid_cure", "pickling"]
  },

  "compatible_proteins": ["seafood", "pork", "chicken"],
  "incompatible_with": ["dairy", "delicate_fish_like_sole"],

  "cuisine_associations": ["sichuan", "hunan", "southeast_asian", "latin"],
  "cantonese_adaptation": "粤菜版酸辣：酸主辣副，保留食材鲜味，辣度克制（Scoville ≤ 3000）"
}
```

### 7.3 4 个查询需要的最小 FT 条目

| FT 条目 | 用于查询 | 优先级 |
|---------|---------|--------|
| sour_spicy（酸辣） | Q1 | P0 |
| maximize_value（发挥价值→感官最大化） | Q2 | P0 |
| gluten_free_french_pastry（无麸质法式） | Q3 | P1 |
| cantonese_banquet_aesthetic（粤菜宴席审美） | Q4 | P0 |
| fresh_light（鲜甜清淡，粤菜底色） | Q4 | P0 |

**最小 FT 启动：5-10 条 FT 节点，覆盖最高频的审美词，其他按需增加。**

FT 不需要 LLM 蒸馏，直接人工写，Jeff + 粤菜经验定义，比任何外部数据库都更精准。

---

## 8. L6 翻译层最小可行设计

### 8.1 L6 的职责边界（必须清楚）

```
L6 做：自然语言词 → 系统字段值的映射
L6 不做：判断哪个食材好、哪个食谱合适（那是 L3）
```

### 8.2 L6 实现策略

**阶段 1（立即可用）：规则字典 + 正则**

```python
# l6_rules.py

REGION_MAP = {
    "南方": ["south_china", "southeast_china"],
    "北方": ["north_china", "northeast_china"],
    "岭南": ["south_china"],
    "华南": ["south_china"],
    "广东": ["south_china"],
    "粤": ["south_china"],
    "东南亚": ["southeast_asia"],
    # ...
}

SEASON_MAP = {
    "春天": [3, 4, 5],
    "春季": [3, 4, 5],
    "夏天": [6, 7, 8],
    "秋天": [9, 10, 11],
    "冬天": [12, 1, 2],
}

COURSE_MAP = {
    "冷前菜": {"course": "appetizer", "serving_temp_type": "cold"},
    "前菜": {"course": "appetizer"},
    "主菜": {"course": "main"},
    "甜品": {"course": "dessert"},
    "汤": {"course": "soup"},
    # ...
}

FLAVOR_MAP = {
    "酸辣": "sour_spicy",
    "鲜甜": "fresh_sweet",
    "清淡": "light",
    "浓郁": "rich",
    "香辣": "spicy_aromatic",
    # ...
}

CANTONESE_TERMS = {
    "大拼盘": "cold_platter",
    "头菜": "main_course_centerpiece",
    "例汤": "soup_of_the_day",
    "走地鸡": {"item": "free_range_chicken", "quality_marker": "free_range"},
    "靓": {"quality_modifier": "premium"},
    # ...
}
```

**阶段 2（FoodOn 对齐，后期）**

挂接 FoodOn OWL 本体，通过 neosemantics 导入 Neo4j，处理更复杂的食材术语层次。

### 8.3 4 个查询需要的 L6 规则

| 规则集 | 覆盖查询 | 条目数 | 优先级 |
|--------|---------|--------|--------|
| 地域词典（南方/北方/粤/闽...） | Q1、Q4 | 20-30 条 | P0 |
| 季节词典（春夏秋冬 + 节气） | Q1 | 10-15 条 | P0 |
| 课序词典（前菜/主菜/甜品/汤...） | Q1、Q3、Q4 | 20 条 | P0 |
| 风味词典（酸辣/鲜甜/清淡...） | Q1、Q4 | 30-50 条 | P0 |
| 饮食限制词典（无麸质/素食/清真...） | Q3 | 15 条 | P0 |
| 粤菜专有术语（白灼/镬气/走地...) | Q4 | 50-100 条 | P1 |

**L6 阶段 1 总规模：约 150-200 条规则，1-2 天人工维护完成。**

---

## 9. 需要 Jeff 决策的点

### 决策 A：Variety 节点拆分时间点

**问题**：当前 L2a schema 里 varieties 是内嵌 JSON 数组。按 l2a_atom_schema_v2.md 的设计，应该拆成独立 Neo4j 节点。但 L2a 还没建。

**选项 A1**：现在就按独立节点设计蒸馏，不走内嵌数组路线。
**选项 A2**：先内嵌数组快速建起来，L2a 建完后再迁移到独立节点。
**建议**：A1，一次做对，迁移成本大于一次做对的代价。

---

### 决策 B：L2b 补字段的方式

**问题**：29,085 条 L2b 食谱缺 `course` / `serving_temp_c` / `dietary_tags` / `flavor_tags`。

**选项 B1**：修改 Stage5 Step A prompt，对新食谱提取时同步填充这些字段。
**选项 B2**：对现有 29,085 条跑后处理 LLM batch job（flash，估算 ¥100-200）。
**选项 B3**：B1 + B2 同时做（新的新提，旧的批量补）。
**建议**：B3。Step A 已经验证通过，改 prompt 成本低；旧数据有价值，值得补全。

---

### 决策 C：FT 层的建设优先级

**问题**：FT 是待建状态，但对查询质量影响大。

**选项 C1**：先用规则字典（L6 规则）临时替代 FT，等 L3 推理引擎建好后再补 FT。
**选项 C2**：现在就用人工定义建 FT 最小集（10-20 条节点），覆盖最高频审美词。
**建议**：C2。FT 节点结构简单，人工定义 20 条覆盖 80% 场景，2-3 天可完成。成本是 Jeff 的时间。

---

### 决策 D：L6 粤语术语词典建设方式

**问题**："走地鸡" / "靓" / "大拼盘" 等粤菜专有词没有外部数据源，只能人工或 Gemini 辅助生成。

**选项 D1**：Jeff 人工维护，每次遇到新术语就追加。
**选项 D2**：Gemini 批量生成 200 条粤菜术语词典初稿，Jeff 审校。
**建议**：D2 更快。批量生成后人工校验，¥10 以内，半天完成。

---

### 决策 E：L6 vs FT 的建设顺序

**问题**：两者都未建，都阻塞查询质量。

**建议顺序**：
1. **L6 规则字典**（1-2天，人工）→ 解锁基础查询路由
2. **FT 最小集**（2-3天，人工定义 + Jeff 审校）→ 解锁风味目标量化
3. **L2a 蒸馏**（6-8天，参见 l2a_atom_schema_v2.md）→ 解锁食材参数筛选
4. **L2b 补字段**（1天 prompt 改 + 2天 batch job）→ 解锁食谱精确筛选
5. **L3 推理引擎**（LangGraph MVP）→ 整合以上所有层

---

## 10. 架构评估结论

### 当前状态

```
已有（可用）：
- L0: 44,692条，覆盖率高，17域，是最强的底层基础设施
- L2b: 29,085条食谱，有基础结构，缺关键筛选字段
- L6 & FT: 完全未建，可用规则字典临时替代

缺失（阻塞）：
- L2a: 完全未建 → 所有需要食材参数的查询都阻塞
- L3: 完全未建 → 所有需要组合推理/优化的查询都阻塞
- L2b 字段: course/temp/dietary/flavor 缺失 → 精确筛选不可用
```

### 哪些查询今天就能跑通（降级版）

| 查询 | 今天能做到 | 依赖 |
|------|-----------|------|
| Q1 海鲜冷前菜 | 60%：能找到相关食谱，L0原理说明，但食材参数/安全边界靠LLM推断不靠图谱 | L2b + L0 |
| Q2 和牛处理 | 70%：L0原理最强，能给出科学建议，但缺L2a具体参数 | L0 |
| Q3 无麸质甜品 | 40%：L2b缺dietary_tags，只能靠文本搜索，覆盖率低 | L2b（不完整）|
| Q4 粤菜宴会 | 30%：粤菜食谱少，L6/FT/L2a全缺 | 几乎全缺 |

### 最高优先级修复路径

```
Week 1:  L6 规则字典 (150条) + FT 最小集 (20条) → 解锁查询路由
Week 2:  L2b 补字段 (batch job) → 解锁精确食谱筛选
Week 3-4: L2a 第一批蒸馏 (500条高频食材) → 解锁食材参数查询
Month 2: L3 LangGraph MVP → 整合所有层，实现真正的端到端推理
```

---

*文档路径：~/culinary-engine/docs/e2e_inference_design.md*
*关联文档：l2a_atom_schema_v2.md | recipe_schema_v1.md | STATUS.md*
