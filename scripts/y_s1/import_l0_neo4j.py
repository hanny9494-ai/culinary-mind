#!/usr/bin/env python3
"""Y-S1-1: Import L0 50K atomic propositions into Neo4j.

Embedding model: local Ollama qwen3-embedding:8b (4096-dim, free, on-host).
Chat / completion calls elsewhere in the codebase still go through Lingya
(see config/api.yaml ▸ `gemini:`); only embeddings stay local because the
L0 ingest issues tens of thousands of vector requests where paid APIs would
be wasteful (repo-curator decision 2026-05-02).

Schema:
  Node: (p:Principle {id, statement, proposition_type, domain, confidence,
                       causal_chain_text, boundary_conditions, citation_quote,
                       source_book, source_chunk_id, embedding, embed_model})
  Vector index: principles_embedding on Principle.embedding (dim=4096, cosine)

Usage:
  python scripts/y_s1/import_l0_neo4j.py [--dry-run] [--limit N] [--no-resume]
  python scripts/y_s1/import_l0_neo4j.py --reindex   # Drop+recreate vector index only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Iterator

for k in ["http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY","all_proxy","ALL_PROXY"]:
    os.environ.pop(k, None)
os.environ["no_proxy"] = "localhost,127.0.0.1"

import httpx
from neo4j import GraphDatabase

REPO_ROOT  = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "output"

NEO4J_URI  = os.getenv("NEO4J_URI",  "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "culinary123")

# ── Embedding: local Ollama qwen3-embedding:8b ────────────────────────────────
# repo-curator 2026-05-02: embeddings stay on-host (free, fast, already
# validated by scripts/phn_embedding_router.py). The Lingya/Gemini paid
# embedding tier from the original PR #21 has been reverted; only chat/
# completion calls in other files keep using Lingya.
OLLAMA_URL              = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/embed")
EMBED_MODEL             = "qwen3-embedding:8b"
EMBED_DIM               = 4096
OLLAMA_TIMEOUT_SECONDS  = 600
OLLAMA_MAX_RETRIES      = 3
OLLAMA_BACKOFF_SECONDS  = (5, 15, 45)

# Legacy aliases — historical callers still import these names. Pointed at
# the new local-Ollama values so consumers transparently use 4096-dim vectors.
GEMINI_EMBED_MODEL      = EMBED_MODEL
GEMINI_EMBED_DIM        = EMBED_DIM

BATCH_SIZE    = 100
PROGRESS_PATH = REPO_ROOT / "output" / "l0_neo4j_import_progress.json"

VALID_DOMAINS = {
    "protein_science", "carbohydrate", "lipid_science", "fermentation",
    "food_safety", "water_activity", "enzyme", "color_pigment",
    "equipment_physics", "maillard_caramelization", "oxidation_reduction",
    "salt_acid_chemistry", "taste_perception", "aroma_volatiles",
    "thermal_dynamics", "mass_transfer", "texture_rheology",
}


def principle_id(record: dict, source_book: str) -> str:
    key = (
        f"{source_book}:{record.get('source_chunk_id','')}:"
        f"{record.get('scientific_statement','')[:80]}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def iter_l0_records() -> Iterator[tuple[str, dict]]:
    # SI enforcement: L0 records sometimes embed Skill-A-style parameter
    # sub-records with raw units (°F, BTU, psi, cup, lb). We normalise
    # those to SI at ingest time so downstream queries can rely on
    # consistent units. `enforce_si(strict=False)` returns (None,
    # 'unconvertible') for unknown units — we annotate the record rather
    # than drop it.
    from pipeline.etl.common import UnitNormalizer
    _un = UnitNormalizer()

    def _enforce_params(rec: dict) -> None:
        params = rec.get("parameters") or []
        if not isinstance(params, list):
            return
        for p in params:
            if not isinstance(p, dict):
                continue
            v, u = p.get("value"), p.get("unit")
            if v is None or u is None:
                continue
            nv, nu = _un.enforce_si(v, u)
            if nv is not None and nu != "unconvertible":
                # preserve original for provenance, add SI-canonical.
                p.setdefault("_raw_value", v)
                p.setdefault("_raw_unit", u)
                p["value"] = nv
                p["unit"]  = nu
            else:
                p["_unit_unconvertible"] = True

    files = sorted(OUTPUT_DIR.rglob("l0_principles_open.jsonl"))
    for path in files:
        book = path.parent.name.replace("stage4_", "").replace("stage4", "stage4_base")
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Schema version fallback: pre-versioning records default to v1.0
                # (see docs/schemas/CHANGELOG.md, 2026-04-23 baseline).
                rec.setdefault("_v", "1.0")
                _enforce_params(rec)
                yield book, rec


def _post_ollama_embed(
    client: httpx.Client,
    payload: dict,
) -> httpx.Response:
    """POST to Ollama /api/embed with retry/backoff on 5xx/transport errors.

    Ollama runs locally; auth is not used. 5xx HTTP responses and transport
    exceptions are retried up to OLLAMA_MAX_RETRIES with exponential backoff.
    """
    last_exc: Exception | None = None
    for attempt in range(OLLAMA_MAX_RETRIES + 1):
        try:
            resp = client.post(
                OLLAMA_URL,
                json=payload,
                timeout=OLLAMA_TIMEOUT_SECONDS,
            )
            if resp.status_code >= 500 and attempt < OLLAMA_MAX_RETRIES:
                time.sleep(OLLAMA_BACKOFF_SECONDS[attempt])
                continue
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < OLLAMA_MAX_RETRIES:
                time.sleep(OLLAMA_BACKOFF_SECONDS[attempt])
                continue
            raise

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Ollama embedding request failed (unreachable)")


def get_embeddings_ollama(texts: list[str], client: httpx.Client) -> list[list[float]]:
    """Batch embed via local Ollama qwen3-embedding:8b (4096-dim).

    Texts are truncated to 8000 chars (matching the previous Gemini bound).
    Returns a list of float vectors aligned with `texts`.
    """
    payload = {
        "model": EMBED_MODEL,
        "input": [t[:8000] for t in texts],
    }
    resp = _post_ollama_embed(client, payload)
    resp.raise_for_status()
    data = resp.json()
    embeddings = data.get("embeddings")
    if not isinstance(embeddings, list):
        raise RuntimeError(f"Ollama response missing 'embeddings' list: {data}")
    if len(embeddings) != len(texts):
        raise ValueError(f"Ollama returned {len(embeddings)} embeddings for {len(texts)} inputs")
    for embedding in embeddings:
        if len(embedding) != EMBED_DIM:
            raise ValueError(f"Ollama returned dim={len(embedding)}, expected {EMBED_DIM}")
    return embeddings


# Legacy alias — historical callers and tests still import this name.
# Implementation moved to local Ollama; see get_embeddings_ollama for details.
def get_embeddings_gemini(texts: list[str], client: httpx.Client) -> list[list[float]]:
    return get_embeddings_ollama(texts, client)


def gemini_embed_one(text: str) -> list[float]:
    """Single-text embedding helper (legacy name; routes through Ollama)."""
    with httpx.Client(trust_env=False, timeout=OLLAMA_TIMEOUT_SECONDS) as c:
        return get_embeddings_ollama([text], c)[0]


def setup_neo4j(driver) -> None:
    with driver.session() as s:
        s.run("""
            CREATE CONSTRAINT principle_id_unique IF NOT EXISTS
            FOR (p:Principle) REQUIRE p.id IS UNIQUE
        """)
        try:
            s.run("DROP INDEX principles_embedding IF EXISTS")
            print("  Dropped old vector index")
        except Exception:
            pass
        s.run(f"""
            CREATE VECTOR INDEX principles_embedding IF NOT EXISTS
            FOR (p:Principle) ON (p.embedding)
            OPTIONS {{indexConfig: {{
              `vector.dimensions`: {EMBED_DIM},
              `vector.similarity_function`: 'cosine'
            }}}}
        """)
        print(f"  Vector index created (dim={EMBED_DIM}, cosine)")


def import_batch_fn(tx, batch: list[dict]) -> int:
    query = """
    UNWIND $rows AS row
    MERGE (p:Principle {id: row.id})
    SET p.statement           = row.statement,
        p.proposition_type    = row.proposition_type,
        p.domain              = row.domain,
        p.confidence          = row.confidence,
        p.causal_chain_text   = row.causal_chain_text,
        p.boundary_conditions = row.boundary_conditions,
        p.citation_quote      = row.citation_quote,
        p.source_book         = row.source_book,
        p.source_chunk_id     = row.source_chunk_id,
        p.embedding           = row.embedding,
        p.embed_model         = row.embed_model
    RETURN count(p) AS n
    """
    result = tx.run(query, rows=batch)
    return result.single()["n"]


def load_progress() -> set[str]:
    if PROGRESS_PATH.exists():
        return set(json.loads(PROGRESS_PATH.read_text()))
    return set()


def save_progress(done_ids: set[str]) -> None:
    PROGRESS_PATH.write_text(json.dumps(list(done_ids)))


def _ollama_health_check() -> tuple[bool, str]:
    """Smoke-test the embedding endpoint at startup so the run fails fast if
    Ollama is down (rather than logging zero-vector warnings for thousands of
    records). Returns (ok, message).
    """
    try:
        with httpx.Client(trust_env=False, timeout=10) as c:
            resp = c.post(OLLAMA_URL, json={"model": EMBED_MODEL, "input": ["ping"]})
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code} from {OLLAMA_URL}"
        embs = resp.json().get("embeddings") or []
        if not embs or not isinstance(embs[0], list) or len(embs[0]) != EMBED_DIM:
            actual = len(embs[0]) if embs and isinstance(embs[0], list) else 0
            return False, f"unexpected embedding shape (got dim={actual}, want {EMBED_DIM})"
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Import L0 principles into Neo4j")
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--limit",     type=int, default=0)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--reindex",   action="store_true",
                        help="Drop+recreate vector index only, then exit")
    args = parser.parse_args()

    # Embedding now runs on local Ollama — verify reachability before doing
    # heavy work, but only when we actually plan to embed (skip on --dry-run
    # and --reindex which never call the embedder).
    if not args.dry_run and not args.reindex:
        ok, msg = _ollama_health_check()
        if not ok:
            print(f"ERROR: Ollama embedding endpoint unreachable: {msg}")
            print(f"       Tried {OLLAMA_URL} with model {EMBED_MODEL}")
            print(f"       Start Ollama (`ollama serve`) and ensure {EMBED_MODEL} is pulled.")
            sys.exit(1)

    print(f"Embedding: Ollama {EMBED_MODEL} ({EMBED_DIM}-dim, local)")
    print(f"Connecting to Neo4j at {NEO4J_URI}...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"ERROR: Cannot connect to Neo4j: {e}")
        sys.exit(1)
    print("  Connected.")

    if not args.dry_run:
        print(f"Setting up schema ({EMBED_DIM}-dim Ollama qwen3 index)...")
        setup_neo4j(driver)

    if args.reindex:
        print("Reindex complete.")
        driver.close()
        return

    done_ids: set[str] = set() if args.no_resume else load_progress()
    print(f"Resume: {len(done_ids)} already imported")

    print("Scanning L0 files...")
    all_records = list(iter_l0_records())
    total = len(all_records)
    print(f"  Found {total} records")
    print(f"  Estimated embedding cost: $0.00 (local Ollama {EMBED_MODEL}, {total} records)")

    pending = [(book, rec) for book, rec in all_records
               if principle_id(rec, book) not in done_ids]
    if args.limit:
        pending = pending[:args.limit]
    print(f"  Pending: {len(pending)} records")

    if args.dry_run:
        print("\n[dry-run] First 3 records:")
        for book, rec in pending[:3]:
            pid = principle_id(rec, book)
            print(f"  {pid} | {book} | {rec.get('scientific_statement','')[:70]}...")
        driver.close()
        return

    http_client = httpx.Client(trust_env=False, timeout=OLLAMA_TIMEOUT_SECONDS)
    total_imported = 0
    t0 = time.time()

    for batch_start in range(0, len(pending), BATCH_SIZE):
        batch = pending[batch_start:batch_start + BATCH_SIZE]
        texts = [
            (rec.get("scientific_statement") or rec.get("causal_chain_text") or "")[:8000]
            for _, rec in batch
        ]

        embeddings = get_embeddings_ollama(texts, http_client)

        rows = []
        for (book, rec), emb in zip(batch, embeddings):
            pid = principle_id(rec, book)
            domain = rec.get("domain", "unclassified")
            rows.append({
                "id":                  pid,
                "statement":           rec.get("scientific_statement", ""),
                "proposition_type":    rec.get("proposition_type", ""),
                "domain":              domain,
                "confidence":          float(rec.get("confidence", 0.7)),
                "causal_chain_text":   rec.get("causal_chain_text", ""),
                "boundary_conditions": json.dumps(
                    rec.get("boundary_conditions", []), ensure_ascii=False),
                "citation_quote":      rec.get("citation_quote", ""),
                "source_book":         book,
                "source_chunk_id":     rec.get("source_chunk_id", ""),
                "embedding":           emb,
                "embed_model":         EMBED_MODEL,
            })

        with driver.session() as s:
            s.execute_write(import_batch_fn, rows)

        total_imported += len(rows)
        for book, rec in batch:
            done_ids.add(principle_id(rec, book))
        save_progress(done_ids)

        elapsed = time.time() - t0
        rate = total_imported / elapsed if elapsed > 0 else 0
        remaining = len(pending) - batch_start - len(rows)
        eta_min = remaining / rate / 60 if rate > 0 else 0
        print(f"  [{total_imported}/{len(pending)}] {rate:.1f} rec/s  ETA {eta_min:.0f}min",
              flush=True)

    http_client.close()
    driver.close()
    print(f"\nImport complete: {total_imported} new records")
    print(f"Total done: {len(done_ids)}")
    print(f"Embed model: {EMBED_MODEL} ({EMBED_DIM}-dim, local)")


if __name__ == "__main__":
    main()
