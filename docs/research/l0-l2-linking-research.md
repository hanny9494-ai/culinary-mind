# Research: L0-L2 Linking Strategies

**Date**: 2026-03-26
**Researcher**: researcher agent
**Purpose**: How to connect L2 (ingredients/recipes) with L0 (scientific principles)

---

## Core Architecture: Three-Hop Linking

```
(Ingredient) -[:CONTAINS {concentration}]-> (Compound) -[:GOVERNED_BY]-> (ScientificPrinciple)
(ProcessStep) -[:TRIGGERS {confidence}]-> (ScientificPrinciple)
(ProcessStep) -[:TRANSFORMS {from_state, to_state}]-> (Compound)
```

### Two Linking Mechanisms in Parallel

| Mechanism | Data Source | Strength | Use |
|-----------|-----------|----------|-----|
| **A. Pre-computed static edges** | FoodAtlas + USDA import | Reliable, deterministic | Known ingredient science |
| **B. Vector similarity** | Neo4j vector index on L0 embeddings | Broad coverage, supports novel combos | Runtime discovery |

---

## External Data Sources Evaluated

### FoodAtlas (gjorgjinac/foodatlas)
- 230K food-compound relations, MIT license
- Maps ~1,000 foods to ~28,000 chemical compounds from FooDB
- **Value**: CRITICAL as bridge layer. Provides `Ingredient → Compound` links; our L0 provides `Compound → Scientific Principle` links.
- **Difficulty**: LOW. Python package, clean API.

### USDA FoodData Central
- 380K+ foods, free API, public domain
- Detailed composition: protein%, fat%, moisture%, amino acid profiles, minerals
- **Value**: CRITICAL for L2a. Provides quantitative parameters that L0 boundary_conditions reference.

### Wikidata Bilingual Names
- SPARQL endpoint, CC0
- **Value**: CRITICAL for L6 translation layer and universal entity linker (QIDs bridge FoodOn, USDA, FooDB).

### FoodOn Ontology (30K classes, OWL, CC BY 3.0)
- **Value**: HIGH for L2a ingredient taxonomy.

### FlavorGraph (Sony AI, 6,653 ingredients, 1,525 flavor compounds)
- **Value**: HIGH for FT layer.

---

## Recipe-to-Science Binding — Literature Gap

No existing system does automatic recipe-step-to-scientific-principle linking.
- Recipe flow graphs (Yamakata 2020): structural parsing only
- Procedural text understanding (Bosselut 2018): state tracking, no chemistry
- **This is our unique value proposition.**

---

## Neo4j Implementation Pattern

```cypher
CREATE VECTOR INDEX l0_embedding IF NOT EXISTS
FOR (p:ScientificPrinciple)
ON (p.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}

CALL db.index.vector.queryNodes('l0_embedding', 10, $step_embedding)
YIELD node, score
WHERE score > 0.75 AND node.domain IN $relevant_domains
RETURN node
```

---

## Recommended Import Priority

| # | Data Source | Target Layer | Value | Difficulty | Time |
|---|-----------|-------------|-------|------------|------|
| 1 | USDA FoodData Central | L2a composition | Critical | Low | 2 days |
| 2 | FoodAtlas | L2a→L0 bridge | Critical | Low | 2-3 days |
| 3 | Wikidata bilingual | L6 + entity linking | Critical | Low | 1 day |
| 4 | FoodOn taxonomy | L2a classification | High | Medium | 2 days |
| 5 | FlavorGraph | FT layer | High (defer) | Low | 1 day |

## Not Recommended
- FoodKG full 67M triples (overkill)
- Building custom food NER (qwen LLM is better)
- Recipe flow graph tools near-term (ISA-88 schema already more structured)
