// Neo4j LOAD CSV seed script for ingredient tree
CREATE CONSTRAINT ingredient_id IF NOT EXISTS FOR (i:CKG_Ingredient) REQUIRE i.canonical_id IS UNIQUE;
CREATE CONSTRAINT cuisine_id IF NOT EXISTS FOR (c:CKG_Cuisine) REQUIRE c.cuisine_id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
CREATE (:CKG_Ingredient {
  canonical_id: row.canonical_id,
  display_name_zh: row.display_name_zh,
  display_name_en: row.display_name_en,
  aliases_json: row.aliases,
  scientific_name: row.scientific_name,
  form_type: row.form_type,
  value_kind: row.value_kind,
  tree_status: row.tree_status,
  exclusion_reason: row.exclusion_reason,
  peak_season_codes_json: row.peak_season_codes,
  peak_months_json: row.peak_months,
  seasonality_records_json: row.seasonality_records,
  dietary_flags_json: row.dietary_flags,
  allergens_json: row.allergens,
  atom_id: row.atom_id,
  confidence_overall: row.confidence_overall
});

LOAD CSV WITH HEADERS FROM 'file:///is_a_edges.csv' AS row
MATCH (s:CKG_Ingredient {canonical_id: row.source})
MATCH (t:CKG_Ingredient {canonical_id: row.target})
CREATE (s)-[:IS_A {kind: row.kind}]->(t);

LOAD CSV WITH HEADERS FROM 'file:///part_of_edges.csv' AS row
MATCH (s:CKG_Ingredient {canonical_id: row.source})
MATCH (t:CKG_Ingredient {canonical_id: row.target})
CREATE (s)-[:PART_OF {part_role: row.part_role}]->(t);

LOAD CSV WITH HEADERS FROM 'file:///derived_from_edges.csv' AS row
MATCH (s:CKG_Ingredient {canonical_id: row.source})
MATCH (t:CKG_Ingredient {canonical_id: row.target})
CREATE (s)-[:DERIVED_FROM {process_type: row.process_type}]->(t);

LOAD CSV WITH HEADERS FROM 'file:///cuisines_seed.csv' AS row
CREATE (:CKG_Cuisine {
  cuisine_id: row.cuisine_id,
  name_zh: row.name_zh,
  name_en: row.name_en,
  region: row.region
});

LOAD CSV WITH HEADERS FROM 'file:///has_culinary_role_edges.csv' AS row
MATCH (i:CKG_Ingredient {canonical_id: row.source})
MATCH (c:CKG_Cuisine {cuisine_id: row.target})
CREATE (i)-[:HAS_CULINARY_ROLE {
  applications: row.applications,
  tips: row.tips
}]->(c);
