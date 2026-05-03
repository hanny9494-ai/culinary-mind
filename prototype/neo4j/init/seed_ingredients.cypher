// 10 generic ingredients plus 5 level=cut hierarchy nodes.

UNWIND [
  {
    id: 'ing_chicken',
    name_en: 'chicken',
    name_zh: '鸡肉',
    category: 'meat',
    level: 'generic',
    foodon_id: null,
    water_content: 0.74,
    protein_pct: 20.0,
    fat_pct: 5.0,
    carb_pct: 0.0,
    fiber_pct: 0.0,
    collagen_pct: 1.5,
    pH: 5.9,
    data_source: 'seed',
    confidence: 0.9
  },
  {
    id: 'ing_onion',
    name_en: 'onion',
    name_zh: '洋葱',
    category: 'vegetable',
    level: 'generic',
    foodon_id: null,
    water_content: 0.89,
    protein_pct: 1.1,
    fat_pct: 0.1,
    carb_pct: 9.3,
    fiber_pct: 1.7,
    collagen_pct: 0.0,
    pH: 5.5,
    data_source: 'seed',
    confidence: 0.9
  },
  {
    id: 'ing_garlic',
    name_en: 'garlic',
    name_zh: '大蒜',
    category: 'vegetable',
    level: 'generic',
    foodon_id: null,
    water_content: 0.59,
    protein_pct: 6.4,
    fat_pct: 0.5,
    carb_pct: 33.1,
    fiber_pct: 2.1,
    collagen_pct: 0.0,
    pH: 5.8,
    data_source: 'seed',
    confidence: 0.9
  },
  {
    id: 'ing_tomato',
    name_en: 'tomato',
    name_zh: '番茄',
    category: 'vegetable',
    level: 'generic',
    foodon_id: null,
    water_content: 0.95,
    protein_pct: 0.9,
    fat_pct: 0.2,
    carb_pct: 3.9,
    fiber_pct: 1.2,
    collagen_pct: 0.0,
    pH: 4.3,
    data_source: 'seed',
    confidence: 0.9
  },
  {
    id: 'ing_beef',
    name_en: 'beef',
    name_zh: '牛肉',
    category: 'meat',
    level: 'generic',
    foodon_id: null,
    water_content: 0.67,
    protein_pct: 21.0,
    fat_pct: 12.0,
    carb_pct: 0.0,
    fiber_pct: 0.0,
    collagen_pct: 2.5,
    pH: 5.6,
    data_source: 'seed',
    confidence: 0.9
  },
  {
    id: 'ing_rice',
    name_en: 'rice',
    name_zh: '稻米',
    category: 'grain',
    level: 'generic',
    foodon_id: null,
    water_content: 0.12,
    protein_pct: 7.1,
    fat_pct: 0.7,
    carb_pct: 80.0,
    fiber_pct: 1.3,
    collagen_pct: 0.0,
    pH: 6.5,
    data_source: 'seed',
    confidence: 0.9
  },
  {
    id: 'ing_butter',
    name_en: 'butter',
    name_zh: '黄油',
    category: 'dairy',
    level: 'generic',
    foodon_id: null,
    water_content: 0.16,
    protein_pct: 0.9,
    fat_pct: 81.0,
    carb_pct: 0.1,
    fiber_pct: 0.0,
    collagen_pct: 0.0,
    pH: 6.2,
    data_source: 'seed',
    confidence: 0.9
  },
  {
    id: 'ing_egg',
    name_en: 'egg',
    name_zh: '鸡蛋',
    category: 'egg',
    level: 'generic',
    foodon_id: null,
    water_content: 0.76,
    protein_pct: 12.6,
    fat_pct: 10.6,
    carb_pct: 1.1,
    fiber_pct: 0.0,
    collagen_pct: 0.0,
    pH: 7.6,
    data_source: 'seed',
    confidence: 0.9
  },
  {
    id: 'ing_flour',
    name_en: 'flour',
    name_zh: '面粉',
    category: 'grain',
    level: 'generic',
    foodon_id: null,
    water_content: 0.12,
    protein_pct: 10.3,
    fat_pct: 1.0,
    carb_pct: 76.3,
    fiber_pct: 2.7,
    collagen_pct: 0.0,
    pH: 6.1,
    data_source: 'seed',
    confidence: 0.9
  },
  {
    id: 'ing_salt',
    name_en: 'salt',
    name_zh: '食盐',
    category: 'condiment',
    level: 'generic',
    foodon_id: null,
    water_content: 0.0,
    protein_pct: 0.0,
    fat_pct: 0.0,
    carb_pct: 0.0,
    fiber_pct: 0.0,
    collagen_pct: 0.0,
    pH: null,
    data_source: 'seed',
    confidence: 0.9
  },
  {
    id: 'ing_chicken_breast',
    name_en: 'chicken breast',
    name_zh: '鸡胸肉',
    category: 'meat',
    level: 'cut',
    foodon_id: null,
    water_content: 0.74,
    protein_pct: 23.0,
    fat_pct: 2.0,
    carb_pct: 0.0,
    fiber_pct: 0.0,
    collagen_pct: 1.2,
    pH: 5.9,
    data_source: 'seed',
    confidence: 0.8
  },
  {
    id: 'ing_chicken_thigh',
    name_en: 'chicken thigh',
    name_zh: '鸡腿肉',
    category: 'meat',
    level: 'cut',
    foodon_id: null,
    water_content: 0.73,
    protein_pct: 18.0,
    fat_pct: 8.0,
    carb_pct: 0.0,
    fiber_pct: 0.0,
    collagen_pct: 1.8,
    pH: 6.0,
    data_source: 'seed',
    confidence: 0.8
  },
  {
    id: 'ing_beef_shank',
    name_en: 'beef shank',
    name_zh: '牛腱',
    category: 'meat',
    level: 'cut',
    foodon_id: null,
    water_content: 0.70,
    protein_pct: 21.0,
    fat_pct: 6.0,
    carb_pct: 0.0,
    fiber_pct: 0.0,
    collagen_pct: 7.5,
    pH: 5.7,
    data_source: 'seed',
    confidence: 0.8
  },
  {
    id: 'ing_beef_sirloin',
    name_en: 'beef sirloin',
    name_zh: '西冷牛排',
    category: 'meat',
    level: 'cut',
    foodon_id: null,
    water_content: 0.68,
    protein_pct: 22.0,
    fat_pct: 11.0,
    carb_pct: 0.0,
    fiber_pct: 0.0,
    collagen_pct: 2.0,
    pH: 5.6,
    data_source: 'seed',
    confidence: 0.8
  },
  {
    id: 'ing_egg_yolk',
    name_en: 'egg yolk',
    name_zh: '蛋黄',
    category: 'egg',
    level: 'cut',
    foodon_id: null,
    water_content: 0.52,
    protein_pct: 16.0,
    fat_pct: 27.0,
    carb_pct: 3.6,
    fiber_pct: 0.0,
    collagen_pct: 0.0,
    pH: 6.0,
    data_source: 'seed',
    confidence: 0.8
  }
] AS row
MERGE (i:CKG_Ingredient {id: row.id})
SET i += row;

MATCH (child:CKG_Ingredient {id: 'ing_chicken_breast'})
MATCH (parent:CKG_Ingredient {id: 'ing_chicken'})
MERGE (child)-[:IS_A]->(parent);

MATCH (child:CKG_Ingredient {id: 'ing_chicken_thigh'})
MATCH (parent:CKG_Ingredient {id: 'ing_chicken'})
MERGE (child)-[:IS_A]->(parent);

MATCH (child:CKG_Ingredient {id: 'ing_beef_shank'})
MATCH (parent:CKG_Ingredient {id: 'ing_beef'})
MERGE (child)-[:IS_A]->(parent);

MATCH (child:CKG_Ingredient {id: 'ing_beef_sirloin'})
MATCH (parent:CKG_Ingredient {id: 'ing_beef'})
MERGE (child)-[:IS_A]->(parent);

MATCH (child:CKG_Ingredient {id: 'ing_egg_yolk'})
MATCH (parent:CKG_Ingredient {id: 'ing_egg'})
MERGE (child)-[:IS_A]->(parent);
