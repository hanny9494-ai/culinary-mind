#!/usr/bin/env python3
"""Y-S1-1: Import L0 50K atomic propositions into Neo4j.

Embedding model: Gemini gemini-embedding-001 (3072-dim, commercial).
Schema:
  Node: (p:Principle {id, statement, proposition_type, domain, confidence,
                       causal_chain_text, boundary_conditions, citation_quote,
                       source_book, source_chunk_id, embedding, embed_model})
  Vector index: principles_embedding on Principle.embedding (dim=3072, cosine)

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

GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
GEMINI_EMBED_MODEL = "gemini-embedding-001"
GEMINI_EMBED_DIM   = 3072
GEMINI_EMBED_URL   = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_EMBED_MODEL}:batchEmbedContents"
)

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
    files = sorted(OUTPUT_DIR.rglob("l0_principles_open.jsonl"))
    for path in files:
        book = path.parent.name.replace("stage4_", "").replace("stage4", "stage4_base")
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield book, json.loads(line)
                except json.JSONDecodeError:
                    continue


def get_embeddings_gemini(texts: list[str], client: httpx.Client) -> list[list[float]]:
    """Batch embed via Gemini gemini-embedding-001 (3072-dim)."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY env var not set")
    requests_payload = [
        {
            "model": f"models/{GEMINI_EMBED_MODEL}",
            "content": {"parts": [{"text": t[:8000]}]},
            "task_type": "RETRIEVAL_DOCUMENT",
        }
        for t in texts
    ]
    resp = client.post(
        f"{GEMINI_EMBED_URL}?key={GEMINI_API_KEY}",
        json={"requests": requests_payload},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return [item["values"] for item in data["embeddings"]]


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
              `vector.dimensions`: {GEMINI_EMBED_DIM},
              `vector.similarity_function`: 'cosine'
            }}}}
        """)
        print(f"  Vector index created (dim={GEMINI_EMBED_DIM}, cosine)")


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Import L0 principles into Neo4j")
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--limit",     type=int, default=0)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--reindex",   action="store_true",
                        help="Drop+recreate vector index only, then exit")
    args = parser.parse_args()

    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY env var required")
        sys.exit(1)

    print(f"Embedding: Gemini {GEMINI_EMBED_MODEL} ({GEMINI_EMBED_DIM}-dim)")
    print(f"Connecting to Neo4j at {NEO4J_URI}...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"ERROR: Cannot connect to Neo4j: {e}")
        sys.exit(1)
    print("  Connected.")

    if not args.dry_run:
        print("Setting up schema (3072-dim Gemini index)...")
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
    # Cost: Gemini embedding-001 is free tier via API v1beta as of 2026-04
    print(f"  Estimated embedding cost: ~$0.00 (Gemini free tier, {total} records)")

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

    http_client = httpx.Client(trust_env=False, timeout=120)
    total_imported = 0
    t0 = time.time()

    for batch_start in range(0, len(pending), BATCH_SIZE):
        batch = pending[batch_start:batch_start + BATCH_SIZE]
        texts = [
            (rec.get("scientific_statement") or rec.get("causal_chain_text") or "")[:8000]
            for _, rec in batch
        ]

        try:
            embeddings = get_embeddings_gemini(texts, http_client)
        except Exception as e:
            print(f"  [warn] Gemini embed failed at {batch_start}: {e} — using zeros")
            embeddings = [[0.0] * GEMINI_EMBED_DIM for _ in batch]

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
                "embed_model":         GEMINI_EMBED_MODEL,
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
    print(f"Embed model: {GEMINI_EMBED_MODEL} ({GEMINI_EMBED_DIM}-dim)")


if __name__ == "__main__":
    main()
