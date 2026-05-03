import os

for _proxy_key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_proxy_key, None)

import argparse
import json
from collections import defaultdict
from pathlib import Path

from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parents[2]
L0_PATH = ROOT / "output" / "phase1" / "l0_clean.jsonl"
PROGRESS_PATH = ROOT / "prototype" / "neo4j" / "_import_progress.json"
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "cmind_p1_33_proto")

INGREDIENT_KEYWORDS = {
    "chicken": ("chicken", "鸡肉", "烤鸡", "禽类"),
    "onion": ("onion", "洋葱"),
    "garlic": ("garlic", "大蒜", "蒜"),
    "tomato": ("tomato", "番茄"),
    "beef": ("beef", "牛肉", "牛腩", "牛腱"),
    "rice": ("rice", "稻米", "大米", "米饭"),
    "butter": ("butter", "黄油"),
    "egg": ("egg", "鸡蛋", "蛋白", "蛋黄"),
    "flour": ("flour", "面粉"),
    "salt": ("salt", "盐", "盐水"),
}

PHN_RULES = (
    ("phn_maillard_browning", ("maillard", "wok_hei", "browning", "brown", "美拉德", "褐变")),
    ("phn_caramelization", ("caramel", "焦糖")),
    (
        "phn_thermal_protein_denaturation",
        ("protein_thermal_denaturation", "thermal_protein_denaturation", "protein", "denaturation", "蛋白", "变性"),
    ),
    ("phn_starch_gelatinization", ("starch_gelatinization", "starch", "gelatinization", "淀粉", "糊化")),
    ("phn_salt_diffusion", ("osmotic_diffusion", "brining", "curing", "salt", "diffusion", "盐", "渗透", "扩散")),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a P1-33 L0 subset into Neo4j.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum L0 records to import.")
    parser.add_argument("--dry-run", action="store_true", help="Select records but do not write to Neo4j.")
    return parser.parse_args()


def load_progress() -> dict:
    if not PROGRESS_PATH.exists():
        return {
            "l0_loaded": 0,
            "l0_phn_edges": 0,
            "ingredient_l0_edges_skipped": 0,
        }
    with PROGRESS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_progress(progress: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def statement_matches(statement: str) -> list[str]:
    haystack = statement.lower()
    matched: list[str] = []
    for slug, keywords in INGREDIENT_KEYWORDS.items():
        if any(keyword.lower() in haystack for keyword in keywords):
            matched.append(slug)
    return matched


def collect_phn_ids(record: dict) -> list[str]:
    tokens: list[str] = []
    for tag in record.get("phenomenon_tags") or []:
        tokens.append(str(tag))
    for score in record.get("phn_scores") or []:
        if isinstance(score, (list, tuple)) and score:
            tokens.append(str(score[0]))
    tokens.append(str(record.get("scientific_statement") or ""))
    tokens.append(str(record.get("causal_chain_text") or ""))

    haystack = " ".join(tokens).lower()
    phn_ids = []
    for phn_id, keywords in PHN_RULES:
        if any(keyword.lower() in haystack for keyword in keywords):
            phn_ids.append(phn_id)
    return list(dict.fromkeys(phn_ids))


def select_records(limit: int) -> list[dict]:
    selected: dict[str, dict] = {}
    per_ingredient = defaultdict(int)
    seen_chunk_by_ingredient: dict[str, set[str]] = defaultdict(set)

    with L0_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            if len(selected) >= limit:
                break
            record = json.loads(line)
            statement = record.get("scientific_statement") or ""
            ingredient_slugs = statement_matches(statement)
            if not ingredient_slugs:
                continue

            source_chunk_id = str(record.get("source_chunk_id") or record.get("_rec_idx") or len(selected))
            l0_id = f"l0_{source_chunk_id}"
            for slug in ingredient_slugs:
                if per_ingredient[slug] >= 5:
                    continue
                if source_chunk_id in seen_chunk_by_ingredient[slug]:
                    continue
                seen_chunk_by_ingredient[slug].add(source_chunk_id)
                per_ingredient[slug] += 1
                if l0_id not in selected:
                    record["_matched_ingredient"] = slug
                    record["_matched_ingredients"] = ingredient_slugs
                    record["_target_phn_ids"] = collect_phn_ids(record)
                    selected[l0_id] = record
                break

            if len(selected) >= limit or all(per_ingredient[slug] >= 5 for slug in INGREDIENT_KEYWORDS):
                break

    return list(selected.values())


def import_record(tx, record: dict) -> dict:
    source_chunk_id = str(record.get("source_chunk_id") or record.get("_rec_idx"))
    l0_id = f"l0_{source_chunk_id}"
    phn_ids = record.get("_target_phn_ids") or []
    primary_phn_id = phn_ids[0] if phn_ids else None
    domain = record.get("domain") or "unclassified"

    result = tx.run(
        """
        MERGE (l0:CKG_L0_Principle {id: $id})
        SET l0.scientific_statement = $scientific_statement,
            l0.domain = $domain,
            l0.primary_phn_id = $primary_phn_id,
            l0.proposition_type = $proposition_type,
            l0.causal_chain_text = $causal_chain_text,
            l0.confidence = $confidence,
            l0.source_book = $source_book,
            l0.citation_quote = $citation_quote,
            l0.version = 1,
            l0.status = 'draft',
            l0.updated_at = datetime(),
            l0.created_at = coalesce(l0.created_at, datetime())
        MERGE (d:CKG_Domain {name: $domain})
        ON CREATE SET d.name_zh = $domain
        MERGE (l0)-[:PRIMARY_DOMAIN]->(d)
        WITH l0
        UNWIND $phn_ids AS phn_id
        MATCH (phn:CKG_PHN {phn_id: phn_id})
        MERGE (l0)-[r:EXHIBITS_PHENOMENON]->(phn)
        SET r.score = 0.8,
            r.evidence = 'keyword match from phenomenon_tags/phn_scores',
            r.method = 'p1_33_import_l0'
        RETURN count(r) AS edge_count
        """,
        id=l0_id,
        scientific_statement=record.get("scientific_statement") or "",
        domain=domain,
        primary_phn_id=primary_phn_id,
        proposition_type=record.get("proposition_type") or "",
        causal_chain_text=record.get("causal_chain_text") or "",
        confidence=float(record.get("confidence") or 0.0),
        source_book=record.get("_book_id") or "",
        citation_quote=record.get("citation_quote") or "",
        phn_ids=phn_ids,
    )
    edge_count = result.single()["edge_count"]
    return {"l0_loaded": 1, "l0_phn_edges": edge_count}


def main() -> None:
    args = parse_args()
    records = select_records(args.limit)
    by_ingredient = defaultdict(int)
    phn_edges = 0
    for record in records:
        by_ingredient[record.get("_matched_ingredient")] += 1
        phn_edges += len(record.get("_target_phn_ids") or [])

    print(f"Selected {len(records)} L0 records from {L0_PATH}")
    print("Ingredient coverage:", dict(sorted(by_ingredient.items())))
    print(f"Potential EXHIBITS_PHENOMENON edges: {phn_edges}")

    if args.dry_run:
        return

    progress = load_progress()
    loaded = 0
    edge_count = 0
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        with driver.session(database="neo4j") as session:
            for record in records:
                counts = session.execute_write(import_record, record)
                loaded += counts["l0_loaded"]
                edge_count += counts["l0_phn_edges"]
                progress = {
                    "l0_loaded": loaded,
                    "l0_phn_edges": edge_count,
                    "ingredient_l0_edges_skipped": loaded,
                }
                write_progress(progress)

    print(f"Imported {loaded} L0 nodes and {edge_count} PHN edges.")
    print(f"Progress checkpoint: {PROGRESS_PATH}")


if __name__ == "__main__":
    main()
