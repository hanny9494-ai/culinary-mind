# Research: Exhaustive Survey of Open-Source Food Databases

**Date**: 2026-03-26
**Researcher**: researcher agent
**Purpose**: Identify ALL viable external databases for L0-L6 layers. 67 resources evaluated.

---

## Category 1: Ingredient / Chemical Composition

| # | Name | URL | Size | License | Layer | Value | Import |
|---|------|-----|------|---------|-------|-------|--------|
| 1.1 | Phenol-Explorer | phenol-explorer.eu | 37K+ values, 500+ foods | Free academic | L2a + L0 color/oxidation | HIGH | LOW |
| 1.2 | KNApSAcK | knapsackfamily.com | 50K+ species-metabolite pairs | Free academic | L2a chemistry | HIGH | MEDIUM |
| 1.3 | PhytoHub | phytohub.eu | 1,800+ phytochemicals | Free open | L2a | MEDIUM | LOW |
| 1.4 | HMDB Food | hmdb.ca | 220K+ metabolites | CC | L2a + L0 | MEDIUM | MEDIUM |
| 1.5 | FoodMine | github barabasi-lab | ML-predicted for 8K foods | Academic | L2a + L0 | MED-HIGH | LOW |

## Category 2: Flavor / Aroma / Taste

| # | Name | URL | Size | License | Layer | Value | Import |
|---|------|-----|------|---------|-------|-------|--------|
| 2.1 | TGSC | thegoodscentscompany.com | 20K+ compounds | Unclear | FT + L0 aroma | VERY HIGH | MED-HIGH |
| 2.2 | BitterDB | bitterdb.agri.huji.ac.il | 1,041 compounds | Free academic | FT + L0 taste | HIGH | LOW |
| 2.3 | SuperSweet | charite.de/sweet | 14K+ compounds | Free academic | FT + L0 taste | MED-HIGH | LOW |
| 2.4 | VCF | vcf-online.nl | 10K+ volatiles | **Commercial $2K/yr** | L0 aroma | HIGH | N/A |
| 2.5 | Leffingwell | leffingwell.com | 3K materials | **Commercial** | FT | MEDIUM | N/A |
| 2.6 | AromaDb | bioinfo.imtech.res.in | 1,230 compounds | Free academic | L2a + FT | MEDIUM | LOW |

## Category 3: Food Safety

| # | Name | URL | Size | License | Layer | Value | Import |
|---|------|-----|------|---------|-------|-------|--------|
| 3.1 | ComBase | combase.cc | 60K+ records | Free open | L0 food_safety | VERY HIGH | MEDIUM |
| 3.2 | EFSA OpenFoodTox | efsa.europa.eu | 5K+ substances | Open | L0 food_safety | MEDIUM | LOW |
| 3.3 | FDA EAFUS | fda.gov | 3K substances | Public domain | L2c + L0 | MEDIUM | LOW |
| 3.4 | Codex GSFA | fao.org | Intl additive regs | Public | L2c + L0 | MEDIUM | MEDIUM |

## Category 4: Regional Food Composition

| # | Name | Size | Format | License | Layer | Value |
|---|------|------|--------|---------|-------|-------|
| 4.1 | Japanese MEXT | 2,500+ foods | XLSX | Public | L2a Asian | HIGH |
| 4.2 | Korean RDA | 3,000+ foods | Web+download | Public | L2a fermentation | HIGH |
| 4.3 | Indian IFCT | 528 foods | **Book/app only** | NIN | L2a spice | HIGH |
| 4.4 | NUTTAB/AUSNUT | 5,740 foods | Excel | CC BY 4.0 | L2a | MEDIUM |
| 4.5 | UK CoFID | 3,300 foods | Excel | Open Gov | L2a + L0 thermal | MED-HIGH |
| 4.6 | TACO Brazil | 597 foods | **PDF Portuguese** | Public | L2a | LOW |
| 4.7 | Thai INMU | 2,200 foods | **Web only** | Public | L2a | MEDIUM |

## Category 5: Recipe Databases

| # | Name | Size | License | Layer | Value |
|---|------|------|---------|-------|-------|
| 5.1 | RecipeDB (IIT) | 118K recipes + flavor compounds | CC BY-NC | L2b + FT | HIGH |
| 5.2 | FoodLLM-Data | 200K+ Chinese recipes | Apache 2.0 | L2b + L6 | VERY HIGH 🔥 |
| 5.3 | Chinese-Recipes-KG | 10K recipes as KG | Free | L2b | MEDIUM |
| 5.4 | Cookpad | 1.5M+ Japanese | **Discontinued** | L2b | N/A |
| 5.5 | RecipeQA | 20K QA pairs | Academic | L3 | LOW-MED |

## Category 6: Enzyme & Protein

| # | Name | Size | License | Layer | Value |
|---|------|------|---------|-------|-------|
| 6.1 | BRENDA | 7K+ enzymes, 500K data points | Free academic | L0 enzyme | VERY HIGH |
| 6.2 | UniProt | 250M+ proteins (filter) | CC BY 4.0 | L0 protein | MEDIUM |
| 6.3 | CAZy/dbCAN2 | 500K enzyme modules | Academic | L0 carb + enzyme | MEDIUM |

## Category 7: NLP Tools

| # | Name | License | Layer | Value |
|---|------|---------|-------|-------|
| 7.1 | NYT Ingredient Tagger | Apache 2.0 | Pipeline L2b | MEDIUM |
| 7.2 | HuggingFace Food NER | MIT/Apache | Pipeline | MEDIUM |
| 7.3 | FoodIE | MIT | Pipeline L0 | HIGH as tool |
| 7.4 | Cooking Action Ontology | **Scattered in papers** | L6 | MED-HIGH |

## Category 8: Physical/Thermal

| # | Name | Status | Layer | Value |
|---|------|--------|-------|-------|
| 8.1 | ASHRAE thermal | **Paid $200+** | L0 thermal | HIGH |
| 8.2 | Singh & Heldman | **Copyrighted** | L0 thermal + mass | HIGH |
| 8.3 | NIST WebBook | Free, per-query | L0 thermal + aroma | MED-HIGH |

## Category 9: Taste Perception

| # | Name | Status | Layer | Value |
|---|------|--------|-------|-------|
| 9.1 | Umami Info Center | **Web articles only** | FT + L0 taste | MED-HIGH |

## Category 10: Other

| # | Name | Status | Layer | Value |
|---|------|--------|-------|-------|
| 10.1 | FAO FAOSTAT | Free CSV download | L2a supply chain | LOW-MED |
| 10.2 | Allergome | **Web-only, scrape** | L2a + L0 | MED-HIGH |
| 10.3 | GlobalFungi/FungalTraits | Free CSV | L0 fermentation | MEDIUM |
| 10.4 | Food-101 / ISIA-500 | Free / Unstable | Future vision | LOW |
| 10.5 | Nutrition5k / YouCook2 | Free | Future L1 | LOW |

---

## Priority Matrix

### Tier 1: MUST HAVE
ComBase, BRENDA, Phenol-Explorer, BitterDB, TGSC, RecipeDB, Japanese MEXT

### Tier 2: HIGH VALUE
KNApSAcK, SuperSweet, Korean Food DB, FoodMine, FoodLLM-Data, ASHRAE (from books)

### Tier 3: GOOD TO HAVE
HMDB food subset, NIST WebBook, UK CoFID, EFSA OpenFoodTox, NYT Tagger
