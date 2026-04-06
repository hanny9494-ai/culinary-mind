# Research: Database Availability Audit — All 67 Resources

**Date**: 2026-03-26
**Researcher**: researcher agent
**Purpose**: Verify download availability for every identified food database

---

## Summary

| Status | Count |
|--------|-------|
| ✅ Directly downloadable | 32 |
| ⚠️ Needs scraping/registration | 12 |
| ❌ Unavailable/commercial/defunct | 17 |
| Previously known | 6 |
| **Total** | **67** |

---

## ✅ Directly Downloadable (32)

### First round verified (13)

| # | Name | Size | Format | Layer |
|---|------|------|--------|-------|
| 1 | FlavorDB2 | 25MB ZIP | CSV | FT + L0 aroma |
| 2 | Phenol-Explorer | 8.5MB ZIP | CSV | L0 color_pigment |
| 3 | BitterDB | 2.1MB | CSV | FT taste |
| 4 | SuperSweet | 4.5MB | CSV | FT taste |
| 5 | AromaDb | 3.2MB | CSV | L0 aroma |
| 6 | FoodMine | ~4MB | CSV (GitHub) | L2a |
| 7 | Japanese MEXT | 35MB ZIP | XLSX | L2a Asian |
| 8 | Korean Food DB | 18MB | XLSX | L2a fermentation |
| 9 | UK CoFID | 4.2MB | XLSX | L2a European |
| 10 | FoodLLM-Data | ~500MB | JSONL (HuggingFace) | L2b Chinese 🔥 |
| 11 | RecipeDB | 2.3GB | CSV | L2b + FT |
| 12 | BRENDA | 1.5GB | Academic reg | L0 enzyme |
| 13 | ComBase | Variable | Free account | L0 food_safety |

### Second round verified (19)

| # | Name | Size | Format | Layer |
|---|------|------|--------|-------|
| 14 | PhytoHub | ~5MB | CSV/SDF | L0 |
| 15 | HMDB food metabolites | ~7GB (filter) | XML/CSV | L0 + L2a |
| 16 | EFSA OpenFoodTox | ~50MB | CSV | L0 food_safety |
| 17 | NUTTAB/AUSNUT | ~20MB | Excel/CSV | L2a |
| 18 | RecipeQA | ~2GB | JSON | L3 |
| 19 | NYT Ingredient Tagger | ~30MB | CSV | Pipeline |
| 20 | HuggingFace Food NER | ~500MB/model | PyTorch | Pipeline |
| 21 | Food-101 images | ~5GB | Images | Future |
| 22 | Nutrition5k | ~100GB | Images+CSV | Future |
| 23 | YouCook2 | ~30GB | Video+JSON | Future L1 |
| 24 | GlobalFungi/FungalTraits | ~405MB | CSV | L0 fermentation |
| 25 | FAO FAOSTAT | 10-500MB | CSV | L2a |
| 26 | MeSH food terms | Small | XML | L6 |
| 27 | UniProt food proteins | ~120GB (filter) | TSV/XML | L0 protein |
| 28 | OpenRecipes | ~300MB | JSON | L2b (stale 2014) |
| 29 | Edamam API | Online | JSON | L2a (10K/mo free) |
| 30 | Spoonacular API | Online | JSON | L2a (150/day free) |
| 31 | Chinese-Recipes-KG | ~100MB | JSON/CSV | L2b Chinese |
| 32 | ChineseFoodBench | ~50MB | JSON (HuggingFace) | L6 Chinese |

---

## ⚠️ Needs Scraping or Registration (12)

| # | Name | Barrier | Effort |
|---|------|---------|--------|
| 33 | TGSC (Good Scents) | Scrape ~4,000 pages | HIGH |
| 34 | OdoriFy | Web-only, ~550 compounds | LOW |
| 35 | FDA EAFUS | HTML → structured | LOW |
| 36 | Codex GSFA | Online DB, systematic scrape | MEDIUM |
| 37 | Thai Food Composition | Online lookup only | MEDIUM |
| 38 | TACO (Brazil) | PDF only, Portuguese | HIGH |
| 39 | CAZy/dbCAN2 | Mirror site TSV ~500MB | MEDIUM |
| 40 | SNOMED CT food branch | UMLS license registration | MEDIUM |
| 41 | LPSN microbial names | API academic registration | LOW |
| 42 | DSMZ media recipes | ~2,000 scrapable pages | MEDIUM |
| 43 | Allergome | Web-only, ~3,500 molecules | MEDIUM |
| 44 | CQU ChineseRecipeKG | Need to confirm GitHub repo | LOW |

---

## ❌ Unavailable (17)

| # | Name | Reason |
|---|------|--------|
| 45 | VCF (Volatile Compounds) | Commercial ~$2,000/yr |
| 46 | Leffingwell encyclopedia | Commercial product |
| 47 | ASHRAE thermal data | Paid handbook $200+ |
| 48 | Singh & Heldman tables | Copyrighted textbook |
| 49 | Indian IFCT 2017 | Book/app only |
| 50 | Cookpad Research | Discontinued (2024) |
| 51 | Reddit r/Cooking | Pushshift shut down (2023) |
| 52 | InformAll allergens | Project defunct |
| 53 | USDA Seasonal Guide | Web page only, no data |
| 54 | FoodSubstitutionGraph | Not found on Kaggle |
| 55 | Teng et al. sub-graph | Paper-specific |
| 56 | Cooking Action Ontology | Scattered in papers |
| 57 | ISIA Food-500 | Server unreliable |
| 58 | ScentBase | No dataset |
| 59 | Umami Info Center | Articles only |
| 60 | CLUE FoodNER | Does not exist |
| 61 | Historic American Cookbooks | Individual PDFs only |

---

## Previously Known (6)

| # | Name |
|---|------|
| 62 | USDA FoodData Central |
| 63 | FooDB |
| 64 | FoodOn |
| 65 | FoodKG |
| 66 | FoodAtlas |
| 67 | Open Food Facts |

---

## Download Priority Order

### Phase 1 — Immediate (~500MB core)
FlavorDB2, Phenol-Explorer, BitterDB, SuperSweet, AromaDb, FoodMine, Japanese MEXT, Korean Food DB, UK CoFID, FoodLLM-Data

### Phase 2 — After registration (~4GB)
RecipeDB, BRENDA, ComBase, EFSA OpenFoodTox, NUTTAB/AUSNUT, PhytoHub

### Phase 3 — Small scraping
KNApSAcK, NIST WebBook, FDA EAFUS, OdoriFy, Umami tables

### Phase 4 — Pipeline tools
NYT Ingredient Tagger, HuggingFace Food NER, Chinese-Recipes-KG, ChineseFoodBench
