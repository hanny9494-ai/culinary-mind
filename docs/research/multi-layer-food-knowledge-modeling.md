# Research: Multi-Layer Food Knowledge Modeling

**Date**: 2026-03-26
**Researcher**: researcher agent
**Purpose**: External resources for Ingredient → Cuisine varieties → Flavor → Aesthetic preference

---

## Executive Summary

**No one has built this end-to-end.** Fragments exist covering 1-2 links only.

---

## Key Findings

### 1. Ahn et al. Flavor Network (2011) — CRITICAL
- **Western cuisines: POSITIVE food pairing** — shared flavor compounds attract
- **East Asian cuisines: NEGATIVE food pairing** — shared compounds AVOIDED (contrast-seeking)
- Cantonese likely follows East Asian pattern
- Methodology replicable with FlavorDB2 (free)

### 2. Texture preferences are MOST culturally variable
- East Asian consumers rate "slippery" textures positively; Western consumers don't
- "嫩滑" (tender-smooth) is positive in Cantonese, neutral-to-negative in Western cooking
- FT layer MUST encode texture as cuisine-dependent

### 3. No Chinese sensory ontology exists
- GB/T standards translate ISO terms but don't cover "镬气", "鲜", "口感爽滑"
- We are building something genuinely novel (FT + L6)

### 4. Every existing food KG stops short
- FoodKG: stops at nutrition
- FoodAtlas: stops at food-health
- Flavor Network: stops at compound co-occurrence
- FlavorGraph: stops at pairing scores
- None model cooking transformations or aesthetic evaluation

### 5. FlavorDB2 + FooDB = chemical backbone
- FlavorDB2: ~2,500 molecules → sensory descriptors
- FooDB: ~80,000 compounds → concentrations
- Together: ingredient → compound (with concentration) → perception

---

## Our Moat

```
External data covers:
  Ingredient → Compounds → Generic Sensory Descriptors

Nobody covers:
  Compound × Concentration × Cooking Method
    → Transformed Profile → Cuisine-Specific Evaluation → Aesthetic Judgment
  (L0 science)              (FT flavor targets)          (L6 translation)
```

---

## Recommendations

### IMPORT NOW
1. FlavorDB2 → compound-perception nodes
2. FooDB → ingredient-compound-concentration data
3. Ahn methodology → Cantonese pairing pattern analysis

### BUILD OURSELVES (no external source covers this)
1. Chinese sensory ontology (L6+FT): Civille texture lexicon as backbone + Chinese terms from books
2. Cuisine-specific aesthetic preferences: LLM extraction from 40+ book corpus
3. Cooking transformation effects: Link L0 science to compound changes
