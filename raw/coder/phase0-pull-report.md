# Phase 0 — External Dataset Pull Report

**Date**: 2026-04-08
**Total size**: 55.5 MB
**Summary**: 4 done/documented, 2 pending manual download

## Dataset Status

### ✅ FoodOn
- **Status**: done
- **Size**: 38.6 MB
- **Files**: `foodon.owl` (38.6MB OWL ontology), `foodon.obo`
- **Notes**: v2025-02-01 master branch from raw.githubusercontent.com

### ✅ FlavorGraph
- **Status**: done
- **Size**: 27 MB
- **Files**: git clone --depth=1, commit 8d3472d0823f
- **Notes**: 1561 molecules × 6000 ingredients + 300D embeddings

### ✅ FoodKG
- **Status**: done
- **Size**: 96 MB
- **Files**: git clone --depth=1 (foodkg.github.io repo with subgraphs + tooling)
- **Notes**: Full 67M triple dump requires separate tooling — evaluate after QC

### ⏳ Recipe1M+
- **Status**: pending — requires registration
- **Action**: Jeff registers at http://pic2recipe.csail.mit.edu/
- **Files needed**: `layer1.json` + `det_ingrs.json` (~4GB text only, NOT images)

### ⏳ RecipeNLG
- **Status**: pending — requires manual browser download
- **Action**: Jeff downloads `dataset.zip` from https://recipenlg.cs.put.poznan.pl/
- **Target**: `data/external/raw/recipenlg/dataset.zip` (~480MB zip / ~1.5GB CSV)
- **Notes**: HuggingFace version is script-based (no direct parquet URL); source site requires manual click

### ✅ USDA FoodData Central
- **Status**: done (existing data)
- **Size**: 2.2 MB (partial JSONL at data/external/usda-fdc/)
- **Notes**: Previously downloaded. Full CSV zip (~750MB) available at fdc.nal.usda.gov if needed.

## Constraints Verified
- ✅ All files in `data/external/raw/` only
- ✅ Production databases untouched (L0/L2a/L2b/Neo4j)
- ✅ No loaders written
- ✅ No data cleaning performed

## Actions Required by Jeff
1. **Recipe1M+**: Register at http://pic2recipe.csail.mit.edu/ and share download link
2. **RecipeNLG**: Download from https://recipenlg.cs.put.poznan.pl/ → `data/external/raw/recipenlg/dataset.zip`
