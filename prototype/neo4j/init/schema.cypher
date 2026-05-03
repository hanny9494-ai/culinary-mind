// P1-33 Neo4j prototype schema, locked by D66 schema v2.
//
// Relationship types in architect 034 section 1.2:
// EXHIBITS_PHENOMENON, GOVERNED_BY_MF, IMPLEMENTED_BY,
// PRIMARY_DOMAIN, SECONDARY_DOMAIN,
// MAPS_TO_PHN, TRANSLATES_TO_PHN, MAPS_TO_FT,
// HAS_STEP, NEXT_STEP, USES_INGREDIENT, TRIGGERS_PHENOMENON,
// USES_EQUIPMENT, IS_A, PART_OF,
// AFFECTS_PHENOMENON, RELATED_PHN.

// Unique constraints for all 11 CKG_ node labels.
CREATE CONSTRAINT ckg_l0_id_unique IF NOT EXISTS
FOR (p:CKG_L0_Principle) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT ckg_phn_id_unique IF NOT EXISTS
FOR (n:CKG_PHN) REQUIRE n.phn_id IS UNIQUE;

CREATE CONSTRAINT ckg_mf_id_unique IF NOT EXISTS
FOR (m:CKG_MF) REQUIRE m.mf_id IS UNIQUE;

CREATE CONSTRAINT ckg_ingredient_id_unique IF NOT EXISTS
FOR (i:CKG_Ingredient) REQUIRE i.id IS UNIQUE;

CREATE CONSTRAINT ckg_recipe_id_unique IF NOT EXISTS
FOR (r:CKG_Recipe) REQUIRE r.id IS UNIQUE;

CREATE CONSTRAINT ckg_step_id_unique IF NOT EXISTS
FOR (s:CKG_Step) REQUIRE s.step_id IS UNIQUE;

CREATE CONSTRAINT ckg_ft_id_unique IF NOT EXISTS
FOR (f:CKG_FT) REQUIRE f.ft_id IS UNIQUE;

CREATE CONSTRAINT ckg_l6_term_id_unique IF NOT EXISTS
FOR (t:CKG_L6_Term) REQUIRE t.term_id IS UNIQUE;

CREATE CONSTRAINT ckg_domain_name_unique IF NOT EXISTS
FOR (d:CKG_Domain) REQUIRE d.name IS UNIQUE;

CREATE CONSTRAINT ckg_tool_id_unique IF NOT EXISTS
FOR (t:CKG_ToolFunction) REQUIRE t.tool_id IS UNIQUE;

CREATE CONSTRAINT ckg_equipment_id_unique IF NOT EXISTS
FOR (e:CKG_Equipment) REQUIRE e.equipment_id IS UNIQUE;

// Vector indexes: 4096 dimensions, cosine similarity.
CREATE VECTOR INDEX ckg_l0_embedding_index IF NOT EXISTS
FOR (p:CKG_L0_Principle) ON (p.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 4096, `vector.similarity_function`: 'cosine'}};

CREATE VECTOR INDEX ckg_phn_embedding_index IF NOT EXISTS
FOR (n:CKG_PHN) ON (n.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 4096, `vector.similarity_function`: 'cosine'}};

CREATE VECTOR INDEX ckg_ft_embedding_index IF NOT EXISTS
FOR (f:CKG_FT) ON (f.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 4096, `vector.similarity_function`: 'cosine'}};

CREATE VECTOR INDEX ckg_l6_embedding_index IF NOT EXISTS
FOR (t:CKG_L6_Term) ON (t.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 4096, `vector.similarity_function`: 'cosine'}};

// Fulltext indexes.
CREATE FULLTEXT INDEX ckg_l0_fulltext IF NOT EXISTS
FOR (p:CKG_L0_Principle) ON EACH
[p.scientific_statement, p.causal_chain_text, p.citation_quote];

CREATE FULLTEXT INDEX ckg_ingredient_fulltext IF NOT EXISTS
FOR (i:CKG_Ingredient) ON EACH [i.name_zh, i.name_en];

CREATE FULLTEXT INDEX ckg_recipe_fulltext IF NOT EXISTS
FOR (r:CKG_Recipe) ON EACH [r.name_zh, r.name];

CREATE FULLTEXT INDEX ckg_step_text_fulltext IF NOT EXISTS
FOR (s:CKG_Step) ON EACH [s.instruction_text, s.normalized_text];

// B-tree indexes.
CREATE INDEX ckg_l0_domain_idx IF NOT EXISTS
FOR (p:CKG_L0_Principle) ON (p.domain);

CREATE INDEX ckg_ingredient_category_idx IF NOT EXISTS
FOR (i:CKG_Ingredient) ON (i.category);

CREATE INDEX ckg_ingredient_name_zh_idx IF NOT EXISTS
FOR (i:CKG_Ingredient) ON (i.name_zh);

CREATE INDEX ckg_step_action_idx IF NOT EXISTS
FOR (s:CKG_Step) ON (s.action);

CREATE INDEX ckg_recipe_cuisine_idx IF NOT EXISTS
FOR (r:CKG_Recipe) ON (r.cuisine);
