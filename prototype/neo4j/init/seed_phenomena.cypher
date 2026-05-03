// 18 domains from CLAUDE.md section 2: 17 canonical domains + unclassified.

UNWIND [
  {name: 'protein_science', name_zh: '蛋白质科学'},
  {name: 'carbohydrate', name_zh: '碳水化合物'},
  {name: 'lipid_science', name_zh: '脂质科学'},
  {name: 'fermentation', name_zh: '发酵'},
  {name: 'food_safety', name_zh: '食品安全'},
  {name: 'water_activity', name_zh: '水分活度'},
  {name: 'enzyme', name_zh: '酶'},
  {name: 'color_pigment', name_zh: '色素与颜色'},
  {name: 'equipment_physics', name_zh: '设备物理'},
  {name: 'maillard_caramelization', name_zh: '美拉德与焦糖化'},
  {name: 'oxidation_reduction', name_zh: '氧化还原'},
  {name: 'salt_acid_chemistry', name_zh: '盐酸化学'},
  {name: 'taste_perception', name_zh: '味觉感知'},
  {name: 'aroma_volatiles', name_zh: '香气挥发物'},
  {name: 'thermal_dynamics', name_zh: '热力学'},
  {name: 'mass_transfer', name_zh: '传质'},
  {name: 'texture_rheology', name_zh: '质构流变'},
  {name: 'unclassified', name_zh: '未分类'}
] AS row
MERGE (d:CKG_Domain {name: row.name})
SET d.name_zh = row.name_zh;

UNWIND [
  {
    phn_id: 'phn_maillard_browning',
    name_en: 'Maillard Browning Reaction',
    name_zh: '煎香上色（美拉德）',
    domain: 'maillard_caramelization',
    definition: '还原糖的羰基与蛋白质/氨基酸的氨基在>130°C发生非酶促反应，产生褐色色素和复杂风味化合物。'
  },
  {
    phn_id: 'phn_caramelization',
    name_en: 'Sugar Caramelization',
    name_zh: '焦糖化反应',
    domain: 'maillard_caramelization',
    definition: '糖在高温（通常>150°C）下不需要氨基酸参与，直接发生热分解并产生焦糖色和焦糖风味。'
  },
  {
    phn_id: 'phn_thermal_protein_denaturation',
    name_en: 'Protein Thermal Denaturation',
    name_zh: '蛋白质热变性',
    domain: 'protein_science',
    definition: '加热使蛋白质三维结构展开，导致凝固、收缩、失水；不同蛋白质具有不同变性温度窗口。'
  },
  {
    phn_id: 'phn_starch_gelatinization',
    name_en: 'Starch Gelatinization',
    name_zh: '淀粉糊化',
    domain: 'carbohydrate',
    definition: '淀粉颗粒在有水和加热条件下吸水膨胀、结晶区熔化，形成黏稠凝胶。'
  },
  {
    phn_id: 'phn_salt_diffusion',
    name_en: 'Salt Diffusion',
    name_zh: '盐分扩散',
    domain: 'mass_transfer',
    definition: '盐或盐水中的溶质沿浓度梯度进入食材组织，同时改变水分迁移与蛋白质保水性，是腌制入味的基础。'
  }
] AS row
MERGE (p:CKG_PHN {phn_id: row.phn_id})
SET p += row;

MATCH (p:CKG_PHN)
MATCH (d:CKG_Domain {name: p.domain})
MERGE (p)-[:PRIMARY_DOMAIN]->(d);

MATCH (a:CKG_PHN {phn_id: 'phn_maillard_browning'})
MATCH (b:CKG_PHN {phn_id: 'phn_caramelization'})
MERGE (a)-[:RELATED_PHN {
  type: 'concurrent',
  description: 'High dry heat can drive both Maillard browning and sugar caramelization.'
}]->(b);

MATCH (a:CKG_PHN {phn_id: 'phn_salt_diffusion'})
MATCH (b:CKG_PHN {phn_id: 'phn_thermal_protein_denaturation'})
MERGE (a)-[:RELATED_PHN {
  type: 'amplifies',
  description: 'Salt diffusion changes protein water binding before heat denaturation.'
}]->(b);
