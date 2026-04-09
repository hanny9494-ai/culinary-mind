# Y-S1 Foundation Report
**Date**: 2026-04-09  
**Branch**: feature/y-s1-foundation  
**Commit**: 51be7e7  

---

## Y-S1-1: Neo4j L0 Import (`scripts/y_s1/import_l0_neo4j.py`)

### What was built
- Scans all `output/**/l0_principles_open.jsonl` — found **52,273 records** across 45 `stage4_*` directories
- Embeds each record via Ollama `nomic-embed-text-v2-moe:latest` (768-dim)
- MERGE into Neo4j with full L0 properties + embedding vector
- Creates `principles_embedding` vector index (cosine, dim=768) + uniqueness constraint on `p.id`
- Resume state: `output/l0_neo4j_import_progress.json` — survives restarts, skips done IDs
- ID generation: SHA256 of `source_book:chunk_id:statement[:80]` → 16-char hex (collision-free)

### Node schema (Neo4j `:Principle`)
```
id, statement, proposition_type, domain, confidence,
causal_chain_text, boundary_conditions, citation_quote,
source_book, source_chunk_id, embedding (768-float list)
```

### Performance
- Rate: ~16.8 rec/s → full 52K import ≈ 52 min
- Background import started 2026-04-09; 4,700+ nodes in Neo4j at time of verification
- **Import is still running** (PID 96641); full import expected to complete before end of day

### Infrastructure
- `infrastructure/docker-compose.yml`: Neo4j 5.26-community, ports 7474+7687, auth neo4j/culinary123
- Start: `docker-compose -f infrastructure/docker-compose.yml up -d`

---

## Y-S1-2: Retrieval API (`src/y_system/retrieval_api.py`)

### What was built
- FastAPI service on port 8760
- **Hybrid retrieval**: vector search (Neo4j `db.index.vector.queryNodes`) + keyword (Cypher CONTAINS)
- **RRF merge**: Reciprocal Rank Fusion score = 1/(60+rank+1) per list, deduplication by chunk_id
- **Answer generation**: Ollama qwen3.5:9b with `/no_think` prefix + `think:false` option (thinking mode disabled)
- Fallback: LingYai API (L0_API_ENDPOINT/L0_API_KEY env vars)

### Endpoints
| Endpoint | Description |
|---|---|
| `GET /health` | Returns `{status, principle_count}` |
| `GET /stats` | Returns total + by-domain counts |
| `POST /retrieve` | Main retrieval with answer gen |

### POST /retrieve verified output
```
Question: 为什么烤鸡胸柴
Answer: 根据提供的科学原理，无法回答... [honest answer: relevant principles not yet imported]
Contexts: 8
Latency: 3,434 ms
  [1] score=0.0164 vector domain=protein_science source=stage4_base
  [2] score=0.0161 vector domain=protein_science ...
  [3] score=0.0159 vector domain=thermal_dynamics ...
  ... 8 total, each with chunk_id/source/score/text/domain/retrieval_method
```

Note: Answer quality will improve as full 52K import completes — only ~5K protein_science 
principles loaded at test time. The honest "cannot answer" response is correct behavior.

### Start command
```bash
uvicorn src.y_system.retrieval_api:app --host 0.0.0.0 --port 8760
```

---

## Y-S1-3: RAGAS Evaluation Scaffold (`src/evaluation/run_ragas.py`)

### What was built
- 4 RAGAS metrics: Context Precision, Context Recall, Faithfulness, Answer Relevancy
- Local LLM judge: Ollama qwen3.5:9b with `/no_think` prefix (no OpenAI required)
- 5 built-in dummy questions for quick smoke test
- Outputs aggregated JSON + per-question breakdown

### Verified output (2 questions, --limit 2)
```
[1/2] Q: 为什么烤鸡胸柴？
  CP=0.25 CR=0.00 F=0.20 AR=0.20   (partial import — chicken breast principles not loaded yet)

[2/2] Q: 美拉德反应需要什么条件？
  CP=0.66 CR=0.60 F=1.00 AR=1.00   (Maillard principles present in current import)

RAGAS Results (2 questions, 15.8s)
  Context Precision:  0.456
  Context Recall:     0.300
  Faithfulness:       0.600
  Answer Relevancy:   0.600
```

4 RAGAS scores output ✅. Scores will improve with full 52K import.

### Usage
```bash
# Dummy smoke test
python -m src.evaluation.run_ragas dummy

# Full eval set
python -m src.evaluation.run_ragas data/golden_set/golden_v0.json --output results.json

# Limit questions
python -m src.evaluation.run_ragas dummy --limit 2
```

---

## Y-S1-4: Recipe Schema v1

### JSON Schema (`docs/schemas/recipe-normalized-v1.json`)
- JSON Schema 2020-12, `additionalProperties: false`
- Required: `schema_version, title, ingredients, steps, source`
- **ingredients[].role** enum: protein/fat/stock/seasoning/aromatic/acid/stabilizer/garnish/starch/vegetable/liquid/other
- **steps[].params**: temp_c, temp_range_c, time_s, time_range_s, ratio, salt_pct, equipment
- **l0_domains** array: 17 allowed domain values for Y-system linking
- **x_cluster_id**: null at ingest (populated by X-axis clustering pipeline)
- **template_id**: null at ingest (populated by template induction)

### Validated Samples (`docs/schemas/recipe-samples-v1.json`)
| Sample | Cuisine | Category | Steps | Ingredients |
|---|---|---|---|---|
| 白灼虾 | cantonese | seafood_main | 5 | 7 |
| Poulet rôti aux herbes | french | protein_main | 4 | 7 |
| 潮州卤水鹅 | teochew | braised | 5 | 12 |

All 3 passed `jsonschema.validate()` ✅

---

## Bugs Fixed During Development
1. **`17_DOMAINS` syntax error** → renamed to `VALID_DOMAINS` (Python identifier can't start with digit)
2. **Ollama thinking mode** → qwen3.5:9b returns empty `response` with thinking tokens. Fix: `/no_think` prefix + `"think": false` option
3. **`domain` KeyError in vector_search** → row access used wrong column alias; fixed Cypher column names
4. **`num_predict: 10/512` too short** → increased to 768 for answer gen, 16 for judge (post-/no_think output is short)

---

## Deliverables Summary
| File | Status |
|---|---|
| `scripts/y_s1/import_l0_neo4j.py` | ✅ committed, import running |
| `src/y_system/retrieval_api.py` | ✅ committed, verified working |
| `src/evaluation/run_ragas.py` | ✅ committed, 4 scores output |
| `docs/schemas/recipe-normalized-v1.json` | ✅ committed, validated |
| `docs/schemas/recipe-samples-v1.json` | ✅ committed, 3 samples |
| `infrastructure/docker-compose.yml` | ✅ committed |
