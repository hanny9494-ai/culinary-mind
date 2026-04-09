#!/usr/bin/env python3
"""Y-S1-1: Import L0 50K atomic propositions into Neo4j.

Schema:
  Node: (p:Principle {id, statement, proposition_type, domain, confidence,
                       causal_chain_text, boundary_conditions, citation_quote,
                       source_book, source_chunk_id, embedding})
  Labels: :Principle + :Domain_<domain> (e.g., :Domain_protein_science)
  Vector index: principles_embedding on Principle.embedding (dim=768)

Usage:
  python scripts/y_s1/import_l0_neo4j.py [--dry-run] [--limit N] [--no-resume]
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

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "output"

NEO4J_URI  = os.getenv("NEO4J_URI",  "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "culinary123")

OLLAMA_URL   = "http://localhost:11434"
EMBED_MODEL  = os.getenv("EMBED_MODEL", "nomic-embed-text-v2-moe:latest")
EMBED_DIM    = 768

BATCH_SIZE    = 50
PROGRESS_PATH = REPO_ROOT / "output" / "l0_neo4j_import_progress.json"

VALID_DOMAINS = {
    "protein_science", "carbohydrate", "lipid_science", "fermentation",
    "food_safety", "water_activity", "enzyme", "color_pigment",
    "equipment_physics", "maillard_caramelization", "oxidation_reduction",
    "salt_acid_chemistry", "taste_perception", "aroma_volatiles",
    "thermal_dynamics", "mass_transfer", "texture_rheology",
}


def principle_id(record: dict, source_book: str) -> str:
    key = f"{source_book}:{record.get('source_chunk_id','')}:{record.get('scientific_statement','')[:80]}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def iter_l0_records() -> Iterator[tuple[str, dict]]:
    """Yield (source_book, record) from all l0_principles_open.jsonl files."""
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


def get_embedding(texts: list[str], client: httpx.Client) -> list[list[float]]:
    """Embed texts via Ollama one at a time."""
    embeddings = []
    for text in texts:
        resp = client.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text[:2000]},  # truncate
            timeout=30,
        )
        resp.raise_for_status()
        emb = resp.json()["embedding"]
        embeddings.append(emb)
    return embeddings


def setup_neo4j(driver) -> int:
    """Create constraints and vector index. Return actual embedding dimension."""
    # First, detect actual embedding dim from Ollama
    http = httpx.Client(trust_env=False, timeout=30)
    try:
        resp = http.post(f"{OLLAMA_URL}/api/embeddings",
                        json={"model": EMBED_MODEL, "prompt": "test"})
        actual_dim = len(resp.json()["embedding"])
        print(f"  Detected embedding dim: {actual_dim}")
    except Exception as e:
        actual_dim = EMBED_DIM
        print(f"  Could not detect dim ({e}), using {actual_dim}")
    finally:
        http.close()

    with driver.session() as s:
        s.run("""
            CREATE CONSTRAINT principle_id_unique IF NOT EXISTS
            FOR (p:Principle) REQUIRE p.id IS UNIQUE
        """)

        result = s.run("SHOW INDEXES WHERE name = 'principles_embedding'")
        if not result.single():
            s.run(f"""
                CREATE VECTOR INDEX principles_embedding IF NOT EXISTS
                FOR (p:Principle) ON (p.embedding)
                OPTIONS {{indexConfig: {{
                  `vector.dimensions`: {actual_dim},
                  `vector.similarity_function`: 'cosine'
                }}}}
            """)
            print(f"  Vector index 'principles_embedding' created (dim={actual_dim})")
        else:
            print("  Vector index already exists")

    return actual_dim


def import_batch_fn(tx, batch: list[dict]) -> int:
    query = """
    UNWIND $rows AS row
    MERGE (p:Principle {id: row.id})
    SET p.statement          = row.statement,
        p.proposition_type   = row.proposition_type,
        p.domain             = row.domain,
        p.confidence         = row.confidence,
        p.causal_chain_text  = row.causal_chain_text,
        p.boundary_conditions= row.boundary_conditions,
        p.citation_quote     = row.citation_quote,
        p.source_book        = row.source_book,
        p.source_chunk_id    = row.source_chunk_id,
        p.embedding          = row.embedding
    RETURN count(p) AS n
    """
    result = tx.run(query, rows=batch)
    return result.single()["n"]


def add_domain_labels(tx, batch: list[dict]) -> None:
    """Add domain labels separately (APOC or dynamic labels)."""
    for row in batch:
        for label in row["domain_labels"]:
            tx.run(
                "MATCH (p:Principle {id: $id}) CALL apoc.create.addLabels(p, [$label]) YIELD node RETURN node",
                id=row["id"], label=label
            )


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
    parser.add_argument("--no-embed",  action="store_true",
                        help="Skip embedding (import without vectors — for testing)")
    args = parser.parse_args()

    print(f"Connecting to Neo4j at {NEO4J_URI}...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"ERROR: Cannot connect to Neo4j: {e}")
        sys.exit(1)
    print("  Connected.")

    actual_dim = EMBED_DIM
    if not args.dry_run:
        print("Setting up schema...")
        actual_dim = setup_neo4j(driver)

    done_ids: set[str] = set() if args.no_resume else load_progress()
    print(f"Resume: {len(done_ids)} already imported")

    print("Scanning L0 files...")
    all_records = list(iter_l0_records())
    print(f"  Found {len(all_records)} records")

    pending = [(book, rec) for book, rec in all_records
               if principle_id(rec, book) not in done_ids]
    if args.limit:
        pending = pending[:args.limit]
    print(f"  Pending: {len(pending)} records")

    if args.dry_run:
        print("\n[dry-run] First 3 records:")
        for book, rec in pending[:3]:
            pid = principle_id(rec, book)
            print(f"  {pid} | {book} | {rec['scientific_statement'][:70]}...")
        driver.close()
        return

    http_client = httpx.Client(trust_env=False, timeout=60)
    total_imported = 0
    t0 = time.time()

    for batch_start in range(0, len(pending), BATCH_SIZE):
        batch = pending[batch_start:batch_start + BATCH_SIZE]
        texts = [
            (rec.get("scientific_statement") or rec.get("causal_chain_text") or "")
            for _, rec in batch
        ]

        # Embed
        if args.no_embed:
            embeddings = [[0.0] * actual_dim for _ in batch]
        else:
            try:
                embeddings = get_embedding(texts, http_client)
            except Exception as e:
                print(f"  [warn] Embedding failed at {batch_start}: {e} — using zeros")
                embeddings = [[0.0] * actual_dim for _ in batch]

        # Build rows
        rows = []
        for (book, rec), emb in zip(batch, embeddings):
            pid = principle_id(rec, book)
            domain = rec.get("domain", "unclassified")
            safe_domain = domain.replace("-", "_").replace(" ", "_")
            domain_labels = [f"Domain_{safe_domain}"]
            if domain not in VALID_DOMAINS:
                domain_labels.append("Domain_unclassified")
            rows.append({
                "id":                 pid,
                "statement":          rec.get("scientific_statement", ""),
                "proposition_type":   rec.get("proposition_type", ""),
                "domain":             domain,
                "confidence":         float(rec.get("confidence", 0.7)),
                "causal_chain_text":  rec.get("causal_chain_text", ""),
                "boundary_conditions": json.dumps(rec.get("boundary_conditions", []),
                                                  ensure_ascii=False),
                "citation_quote":     rec.get("citation_quote", ""),
                "source_book":        book,
                "source_chunk_id":    rec.get("source_chunk_id", ""),
                "embedding":          emb,
                "domain_labels":      domain_labels,
            })

        with driver.session() as s:
            s.execute_write(import_batch_fn, rows)
            # Add domain labels (best-effort, APOC may not be available)
            try:
                s.execute_write(add_domain_labels, rows)
            except Exception:
                pass  # APOC not required for core functionality

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
    print(f"Progress: {PROGRESS_PATH}")


if __name__ == "__main__":
    main()
