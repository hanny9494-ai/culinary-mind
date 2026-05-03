import os

for _proxy_key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_proxy_key, None)

import argparse
import json
import time
from pathlib import Path
from typing import Any

import requests
from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parents[2]
PROGRESS_PATH = ROOT / "prototype" / "neo4j" / "_embed_progress.json"
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "cmind_p1_33_proto")
OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODEL = "qwen3-embedding:8b"
TIMEOUT_SECONDS = 600
RETRY_DELAYS = (5, 10, 20)

TEXT_FIELDS = {
    "CKG_L0_Principle": ("scientific_statement", "causal_chain_text"),
    "CKG_PHN": ("name_zh", "definition"),
    "CKG_FT": ("aesthetic_term_zh",),
    "CKG_L6_Term": ("text_zh", "text_en"),
}

PROGRESS_KEYS = {
    "CKG_L0_Principle": "processed_l0",
    "CKG_PHN": "processed_phn",
    "CKG_FT": "processed_ft",
    "CKG_L6_Term": "processed_l6",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed empty CKG nodes with local Ollama.")
    parser.add_argument("--label", choices=sorted(TEXT_FIELDS), help="Only embed one label.")
    parser.add_argument("--limit", type=int, help="Maximum nodes to process across selected labels.")
    parser.add_argument("--dry-run", action="store_true", help="List work but do not call Ollama or write Neo4j.")
    return parser.parse_args()


def initial_progress() -> dict:
    return {
        "processed_l0": 0,
        "processed_phn": 0,
        "processed_ft": 0,
        "processed_l6": 0,
        "failed": [],
    }


def load_progress() -> dict:
    if not PROGRESS_PATH.exists():
        return initial_progress()
    with PROGRESS_PATH.open("r", encoding="utf-8") as fh:
        loaded = json.load(fh)
    progress = initial_progress()
    progress.update(loaded)
    return progress


def write_progress(progress: dict) -> None:
    PROGRESS_PATH.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def make_text(label: str, props: dict[str, Any]) -> str:
    values = [str(props.get(field) or "").strip() for field in TEXT_FIELDS[label]]
    return " | ".join(value for value in values if value)


def fetch_nodes(session, label: str, limit: int | None) -> list[dict]:
    fields = ", ".join(f"n.{field} AS {field}" for field in TEXT_FIELDS[label])
    limit_clause = "LIMIT $limit" if limit is not None else ""
    query = f"""
    MATCH (n:{label})
    WHERE n.embedding IS NULL OR size(n.embedding) = 0
    RETURN elementId(n) AS element_id, {fields}
    ORDER BY elementId(n)
    {limit_clause}
    """
    result = session.run(query, limit=limit)
    return [dict(record) for record in result]


def request_embedding(http: requests.Session, text: str) -> list[float]:
    last_error: Exception | None = None
    for attempt, delay in enumerate((*RETRY_DELAYS, None), start=1):
        try:
            response = http.post(
                OLLAMA_URL,
                json={"model": MODEL, "prompt": text},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            embedding = data.get("embedding")
            if not isinstance(embedding, list):
                raise ValueError(f"Ollama response missing embedding: {data}")
            if len(embedding) != 4096:
                raise ValueError(f"Expected 4096 dimensions, got {len(embedding)}")
            return [float(value) for value in embedding]
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if delay is None:
                break
            print(f"Embedding attempt {attempt} failed: {exc}; retrying in {delay}s")
            time.sleep(delay)
    raise RuntimeError(f"Embedding failed after 3 retries: {last_error}")


def write_embedding(tx, element_id: str, embedding: list[float]) -> None:
    tx.run(
        """
        MATCH (n)
        WHERE elementId(n) = $element_id
        SET n.embedding = $embedding
        """,
        element_id=element_id,
        embedding=embedding,
    )


def show_vector_indexes(session) -> list[dict]:
    rows = session.run(
        """
        SHOW INDEXES
        YIELD name, type, state, labelsOrTypes, properties, options
        WHERE type = 'VECTOR'
        RETURN name, state, labelsOrTypes, properties, options
        ORDER BY name
        """
    )
    return [dict(row) for row in rows]


def main() -> None:
    args = parse_args()
    labels = [args.label] if args.label else list(TEXT_FIELDS)
    progress = load_progress()

    http = requests.Session()
    http.trust_env = False

    processed_total = 0
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        with driver.session(database="neo4j") as session:
            for label in labels:
                remaining = None
                if args.limit is not None:
                    remaining = max(args.limit - processed_total, 0)
                    if remaining == 0:
                        break
                nodes = fetch_nodes(session, label, remaining)
                print(f"{label}: {len(nodes)} nodes need embedding")
                if args.dry_run:
                    continue

                for node in nodes:
                    text = make_text(label, node)
                    if not text:
                        progress["failed"].append({"label": label, "element_id": node["element_id"], "error": "empty text"})
                        write_progress(progress)
                        continue
                    try:
                        embedding = request_embedding(http, text)
                        session.execute_write(write_embedding, node["element_id"], embedding)
                        progress[PROGRESS_KEYS[label]] += 1
                        processed_total += 1
                    except Exception as exc:  # noqa: BLE001
                        progress["failed"].append({"label": label, "element_id": node["element_id"], "error": str(exc)})
                    write_progress(progress)

            indexes = show_vector_indexes(session)
            print("Vector index states:")
            for index in indexes:
                print(f"- {index['name']}: {index['state']}")

    if args.dry_run:
        print("Dry run completed; no embeddings written.")
    else:
        print(f"Embedding progress checkpoint: {PROGRESS_PATH}")


if __name__ == "__main__":
    main()
