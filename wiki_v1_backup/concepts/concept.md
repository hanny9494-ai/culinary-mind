---
last_updated: '2026-04-04T16:09:15.093954+00:00'
mention_count: 33.0
related:
- '[[CLAUDE.md]]'
- '[[README.md]]'
- '[[STATUS.md]]'
- '[[docs/culinary_engine_architecture_v5.docx]]'
- '[[l0-l2-linking-research.md]]'
- '[[l2a_atom_schema_v2.md]]'
- '[[recipe_schema_v1.md]]'
- '[[stage5_recipe_extract_design.md]]'
- '[[system_architecture_evaluation.md]]'
- '[[stage4_open_extract_design.md]]'
- '[[roadmap_priorities_v2.md]]'
- '[[research/l0-l2-linking-research.md]]'
- '[[research/search-grounded-llms-for-ingredient-data.md]]'
- '[[Architecture/L2a.md]]'
- '[[ONBOARD.md]]'
- '[[wiki/ARCHITECTURE.md]]'
- '[[research_architecture-briefing-for-cc-lead.md]]'
- '[[e2e_inference_design.md]]'
- '[[research/notebooklm-youtube-food-extraction.md]]'
- '[[research/multi-layer-food-knowledge-modeling.md]]'
sources:
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
- curate-cycle-2026-04-04
status: active
title: concepts — concept
---

# concepts — concept


## Updates (2026-04-04)
- Project identity: Culinary Engine is a cooking science reasoning engine with core formula: ingredient parameters × flavor goals × scientific principles = infinite recipes. Target users: professional chefs, restaurant owners, R&D teams. Not recipe retrieval but causal-chain scientific reasoning + Cantonese cuisine aesthetic transformation.
- System positioning: target users are professional chefs/restaurant owners/R&D teams. Core capability: causal-chain scientific reasoning + Cantonese cuisine aesthetic transformation (NOT recipe retrieval). Core formula: ingredient parameters × flavor targets × scientific principles = infinite recipes
- No existing system does automatic recipe-step-to-scientific-principle linking. This is the project's unique value proposition. Literature gap confirmed: Recipe flow graphs (Yamakata 2020) are structural parsing only; Procedural text understanding (Bosselut 2018) does state tracking but no chemistry.
- L2a is the most granularity-sensitive layer: it is a parameterized ingredient node with regional, seasonal, and processing-state dimensions, bridging L2b recipes and L0 scientific principles. It is NOT a USDA nutrition table nor a recipe ingredient list.
- USDA Foundation Foods provides min/max/median values for nutrients, suitable for calibrating boundary_conditions aligned with L0 boundary_conditions
- FoodAtlas granularity is food-class level (e.g., 'chicken') not body-part or regional variety level — aligns with L2a atom granularity. Variety-level chemical differences require FooDB + literature supplementation.
- SubRecipe is the atomic unit: defined by having an independent formula (own ingredients + own seasoning). sub_recipe_id format: SR-xxx
- ingredients.role vocabulary: main/seasoning/fat/acid/aromatics/liquid/thickener/emulsifier/cure/spice/color/umami/herb/binder/flavor/condiment
- Unit standardization: teaspoon→5ml, tablespoon→15ml, cup→240ml, oz→28g, inch→2.5cm. All metric (g/ml/cm)
- Four ingredient source types in Recipe layer: components[] = SubRecipe refs with formula; main_ingredients[] = processed but no independent formula; garnish[] = zero-operation decoration; refs[] = external SubRecipe defined elsewhere (e.g., book appendix Basic Recipes)
- Component role vocabulary: main/carrier/accompaniment/sauce/marinade/seasoning/filling/base
- r-NE label mapping to schema: F(ingredient)+Q(quantity) → formula.ingredients; Ac(action)+D(time)+Sf(state) → process[]; T(tool) → equipment[]
- L0 is the judge: every extracted recipe parameter (temperature, time, ratio) must have scientific basis in L0 principles. If recipe parameter conflicts with L0, mark as needs_review. This is the core value of L2b (recipe calibration library)
- Ingredient substitution future capability (P4): EaT-PIM flow graph embedding + L0 causal chain = scientifically valid substitution recommendations. Example: 'replace sea bass with grouper' → L0 knows protein denaturation temperatures differ → adjust steaming time
- Data layer naming convention: L0=scientific principles, L2b=recipe calibration library, L3=inference engine/reasoning layer, L6=translation layer
- qualifier field in ingredients is optional, only valid values: 'to_taste' or 'approx', only when qty=null
- Stage3 limitation: 306 questions determine what can be extracted; only top-3 chunks per question distilled; questions reflect human bias toward known domains
- Stage4 is chunk-driven extraction (vs Stage3 question-driven): LLM reads each chunk directly and autonomously discovers scientific principles
- Metaphor: 306-question distillation is the skeleton, open scan is the muscle — they are complementary
- Unique value proposition: No existing system does automatic recipe-step-to-scientific-principle linking. Recipe flow graphs (Yamakata 2020) do structural parsing only; Procedural text understanding (Bosselut 2018) does state tracking but no chemistry. This gap is the project's core differentiator.
- Gemini 2.5+ supports structured JSON output with search grounding enabled simultaneously
- Core architectural principles: wiki is compiled never manually edited (raw/ → LLM → wiki/), memory is compass (points to wiki, doesn't store content), User Sovereignty (AI recommends, Jeff decides), CC Lead orchestrates doesn't execute (coding → coder, pipeline → pipeline-runner)
- Competitive moat identified: External data covers Ingredient → Compounds → Generic Sensory Descriptors. Our unique chain: Compound × Concentration × Cooking Method → Transformed Profile → Cuisine-Specific Evaluation → Aesthetic Judgment (L0 → FT → L6)
- FT (flavor target layer) and L6 together are globally novel — no external source can provide them. East Asian cuisines (including Cantonese) favor contrast pairing (Ahn 2011). Texture preference is the dimension with greatest cultural variation. No machine-readable Chinese sensory ontology exists for concepts like 镬气, 鲜, 口感爽滑
- L0 scientific principles triggered for cold seafood dish: citrus acid protein denaturation (ceviche principle: pH ≤ 3.5, 20-30 min for complete denaturation), cold dish food safety (seafood must be heated ≥63°C OR acid pH ≤ 4.0 for sufficient time), acid effect on umami (pH 3.2-3.8 enhances IMP/GMP release), capsaicin cold sensitivity (TRPV1 receptor less sensitive at low temp → increase spice level for cold dishes), texture (acid denaturation more elastic than heat denaturation but >45min becomes rubbery)
- FT flavor target matrix for cold sour-spicy seafood appetizer: sourness 4/5 (primary), spiciness 3/5 (accent), umami 4/5 (seafood base), sweetness 2/5 (balance acid), texture_target = tender + slightly firm (moderate protein denaturation), aroma_target = citrus front + seafood natural + chili tail
- NotebookLM role in culinary-engine: NOT a pipeline component. Used as a quality anchor — Jeff manually loads 30-50 core documentaries, uses interactive Q&A to find highest-density content and calibrate automated pipeline extraction quality.
- No existing system has built end-to-end food knowledge modeling: Ingredient → Cuisine varieties → Flavor → Aesthetic preference. All existing KGs cover only 1-2 links in this chain.
- Texture preferences are the MOST culturally variable sensory dimension. East Asian consumers rate 'slippery' textures positively; Western consumers do not. '嫩滑' (tender-smooth) is positive in Cantonese, neutral-to-negative in Western cooking.
- No Chinese sensory ontology exists. GB/T standards translate ISO terms but do not cover '镬气', '鲜', '口感爽滑'. Building FT + L6 layers is genuinely novel work.
- FoodKG stops at nutrition; FoodAtlas stops at food-health; Flavor Network stops at compound co-occurrence; FlavorGraph stops at pairing scores. None model cooking transformations or aesthetic evaluation.
- Our competitive moat: nobody covers 'Compound × Concentration × Cooking Method → Transformed Profile → Cuisine-Specific Evaluation → Aesthetic Judgment'. This spans L0 science, FT flavor targets, and L6 translation layers.
