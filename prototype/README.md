# P1-33 Neo4j Prototype

This prototype locks the D66 schema v2 labels and indexes, loads a small culinary knowledge graph, embeds local nodes through Ollama, and runs the first ingredient -> L0 -> PHN -> MF -> ToolFunction smoke path.

## Reproduce

Run from the repository root unless a command says otherwise.

```bash
# 1. Start Neo4j
cd prototype/neo4j
docker compose up -d
sleep 30

# Optional health checks
docker compose ps
curl -I http://localhost:7474

# 2. Initialize schema
docker compose exec -T neo4j cypher-shell -u neo4j -p cmind_p1_33_proto < init/schema.cypher

# 3. Load seeds
docker compose exec -T neo4j cypher-shell -u neo4j -p cmind_p1_33_proto < init/seed_ingredients.cypher
docker compose exec -T neo4j cypher-shell -u neo4j -p cmind_p1_33_proto < init/seed_phenomena.cypher
docker compose exec -T neo4j cypher-shell -u neo4j -p cmind_p1_33_proto < init/seed_tools.cypher

# 4. Import the L0 subset
cd ../..
python prototype/neo4j/import_l0.py --limit 50

# 5. Generate embeddings with local Ollama
python prototype/neo4j/embed_nodes.py

# 6. Run the end-to-end smoke test
python prototype/smoke_test.py

# 7. Run tests
pytest prototype/tests/ -v
```

The Neo4j browser is available at `http://localhost:7474`.

Credentials:

- User: `neo4j`
- Password: `cmind_p1_33_proto`

## What Gets Loaded

- 11 `CKG_` labels with unique constraints.
- 4 vector indexes, all `4096` dimensions with `cosine` similarity.
- 4 fulltext indexes and 5 regular indexes.
- 10 generic ingredients plus 5 `level=cut` ingredient hierarchy nodes.
- 5 PHN nodes, 18 domains, one `mf_t01` MF, one ToolFunction, and five equipment anchors.
- Around 50 L0 records selected by ingredient keywords from `output/phase1/l0_clean.jsonl`.

## Troubleshooting

**Neo4j healthcheck is still starting**

Wait another 30-60 seconds and run:

```bash
cd prototype/neo4j
docker compose ps
docker compose logs neo4j --tail=80
```

**APOC or GDS plugin load fails**

Remove only the prototype Docker volumes and recreate the container:

```bash
cd prototype/neo4j
docker compose down -v
docker compose up -d
```

The compose file uses the `neo4j:5.26-community` image and official `NEO4J_PLUGINS` installer so APOC and GDS plugin versions match the server. `neo4j:5.20-community` was avoided because the current GDS plugin resolver no longer provides a compatible artifact for that patch line.

**Ollama connection refused**

Start Ollama and make sure the embedding model exists:

```bash
ollama serve
ollama pull qwen3-embedding:8b
python prototype/neo4j/embed_nodes.py --dry-run
```

`embed_nodes.py` connects directly to `http://localhost:11434/api/embeddings`, clears proxy environment variables, and uses `requests.Session(trust_env=False)`.

**Vector indexes are not ONLINE**

Check index state:

```bash
cd prototype/neo4j
docker compose exec -T neo4j cypher-shell -u neo4j -p cmind_p1_33_proto \
  "SHOW INDEXES YIELD name, type, state WHERE type = 'VECTOR' RETURN name, state"
```

If an index is still populating, wait and rerun. If it failed, inspect Neo4j logs and rerun `init/schema.cypher`; all schema statements are idempotent.

**L0 import can be rerun**

`import_l0.py` uses `MERGE` and writes `prototype/neo4j/_import_progress.json`. Rerunning the command is safe.

**Embedding can be rerun**

`embed_nodes.py` only selects nodes whose `embedding` is missing or empty, and writes `prototype/neo4j/_embed_progress.json`.
