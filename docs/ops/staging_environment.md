# P2-Ops1 — Neo4j Staging Environment

> **Status:** Spec only. Production currently runs single Neo4j instance.
> **Goal:** Separate `dev` / `staging` / `prod` environments before P3 production import.

## Why staging

- Before P3 large-batch import (food tree + cookbook + Phase 2 recipes), we need a safe rehearsal target.
- Quality audit (`data_quality_audit.py`) + integration tests (`tests/integration/test_pipeline_e2e.py`) should run against staging first.
- Rollback (`neo4j_snapshot.py rollback`) is destructive — we MUST never test it on prod.

## Environments

| Env     | Port  | Auth                              | Purpose                                                  |
|---------|-------|-----------------------------------|----------------------------------------------------------|
| dev     | 7687  | `neo4j / cmind_p1_33_proto`       | Current host, single-instance, development               |
| staging | 7688  | `neo4j / ${CMIND_NEO4J_STAGING_PW}` | Pre-prod rehearsal, snapshot-restored from prod nightly |
| prod    | 7689  | `neo4j / ${CMIND_NEO4J_PROD_PW}`  | Production, write-protected; only successful staging promotions land here |

## Deployment plan

1. **Docker compose (recommended)** under `infra/neo4j/docker-compose.yaml`:
   ```yaml
   services:
     neo4j-staging:
       image: neo4j:5.20
       ports: ["7688:7687"]
       environment:
         NEO4J_AUTH: neo4j/${CMIND_NEO4J_STAGING_PW}
         NEO4J_PLUGINS: '["apoc"]'
       volumes:
         - ./data/staging:/data
   ```
2. **Secrets**: load from `.env` (gitignored) — never inline in compose.
3. **Promotion**: `neo4j_snapshot.py snapshot --tag prod_$(date)` → copy to staging volume → `neo4j_snapshot.py rollback` against staging endpoint.

## Operational checklist before P3 bulk import

- [ ] Staging container running
- [ ] APOC + plugins installed on all envs
- [ ] `data_quality_audit.py` passes against staging
- [ ] Integration tests pass against staging
- [ ] Snapshot taken of prod (always before any write)
- [ ] Promotion validated end-to-end

## Snapshot/rollback workflow

```bash
# Daily snapshot (cron)
python scripts/quality/neo4j_snapshot.py snapshot --tag prod_nightly_$(date +%Y%m%d)

# List
python scripts/quality/neo4j_snapshot.py list

# Rollback (intentional, requires confirm flag)
python scripts/quality/neo4j_snapshot.py rollback --tag prod_nightly_20260514 --i-know-what-im-doing
```

## Env vars

```bash
# ~/.zshrc (do NOT commit)
export CMIND_NEO4J_DEV_URI="bolt://localhost:7687"
export CMIND_NEO4J_STAGING_URI="bolt://localhost:7688"
export CMIND_NEO4J_PROD_URI="bolt://localhost:7689"

export CMIND_NEO4J_DEV_PW="cmind_p1_33_proto"
export CMIND_NEO4J_STAGING_PW="..."
export CMIND_NEO4J_PROD_PW="..."
```

Scripts should read these and never hardcode URIs/passwords.

## Outstanding (deferred to P3)

- Actually spin up staging container (architect to design infra/neo4j layout per D-LATER)
- Migrate all hard-coded `bolt://localhost:7687` strings to read env var
- CI integration: PR must pass tests against staging before merge

— Generated 2026-05-14, P2-Ops1
