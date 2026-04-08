# Phase 0 — External Dataset Pull Report (Final)

**Date**: 2026-04-09
**Total size**: 2.8 GB
**Summary**: 5 done/documented, 1 dropped (misaligned)

## Dataset Status

### ✅ FoodOn
- **Status**: done
- **Size**: 38.6 MB
- **Files**: `foodon.owl` (OWL ontology v2025-02-01), `foodon.obo`
- **Notes**: From raw.githubusercontent.com/FoodOntology/foodon/master. 9445+ classes.

### ✅ FlavorGraph
- **Status**: done
- **Size**: 27 MB
- **Files**: git clone --depth=1, commit 8d3472d0823f
- **Notes**: 1561 molecules × 6000 ingredients + 300D pre-trained embeddings.

### ✅ FoodKG
- **Status**: done
- **Size**: 96 MB
- **Files**: git clone --depth=1 (foodkg.github.io repo — subgraphs + tooling)
- **Notes**: Full 67M triple dump requires separate tooling — evaluate after QC.

### ❌ Recipe1M+
- **Status**: dropped — misaligned with project goals
- **Reason**: Dataset is designed for image-recipe cross-modal retrieval (ML vision task).
  Architecture centers on visual embeddings + bidirectional image↔recipe matching.
  Not useful for culinary science reasoning. RecipeNLG covers all our actual use cases
  (ingredient co-occurrence, MSA variant signal). Registration submitted but download not pursued.

### ✅ RecipeNLG
- **Status**: done
- **Size**: 2.1 GB CSV + 592 MB zip
- **Files**: `full_dataset.csv` — 2,231,142 recipes (title, ingredients, directions, NER)
- **Notes**: Downloaded manually from recipenlg.cs.put.poznan.pl. v1.0 May 2020.

### ✅ USDA FoodData Central
- **Status**: done (existing data)
- **Size**: 2.2 MB (partial JSONL at data/external/usda-fdc/)
- **Notes**: Previously downloaded. Full CSV zip (~750MB) available at fdc.nal.usda.gov if needed after QC.

## Constraints Verified
- ✅ All files in `data/external/raw/` only
- ✅ Production databases untouched (L0/L2a/L2b/Neo4j)
- ✅ No loaders written, no data cleaning performed

## No Pending Actions
Phase 0 complete. All 5 relevant datasets archived. Recipe1M+ dropped by Jeff's decision.

## Next Steps
1. QC pass on each dataset (counts, schema, license, alignment check)
2. FoodKG full 67M triple dump — evaluate if subgraph repo is sufficient
3. USDA FDC full CSV — evaluate if current partial data is sufficient
4. After QC → staging → approved → distillation pipeline
