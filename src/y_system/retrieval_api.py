"""Y-S1-2: Retrieval API — FastAPI service for L0 knowledge retrieval.

Supports hybrid retrieval: keyword (Cypher full-text) + vector (Neo4j built-in).
Aligned with LightRAG evaluation/ interface for RAGAS scoring.

Usage:
  uvicorn src.y_system.retrieval_api:app --host 0.0.0.0 --port 8760 --reload

Endpoints:
  POST /retrieve       — main retrieval
  GET  /health         — health check
  GET  /stats          — index stats
"""
from __future__ import annotations

import os
import time
from typing import Any

for k in ["http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY","all_proxy","ALL_PROXY"]:
    os.environ.pop(k, None)
os.environ["no_proxy"] = "localhost,127.0.0.1"

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase
from pydantic import BaseModel, Field

# ─── Config ────────────────────────────────────────────────────────────────────

NEO4J_URI  = os.getenv("NEO4J_URI",  "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "culinary123")

OLLAMA_URL   = "http://localhost:11434"  # used for embedding queries
EMBED_MODEL  = os.getenv("EMBED_MODEL", "nomic-embed-text-v2-moe:latest")  # query embedding only

LINGYAI_ENDPOINT = os.getenv("L0_API_ENDPOINT", "")
LINGYAI_KEY      = os.getenv("L0_API_KEY", "")
ANSWER_MODEL     = os.getenv("ANSWER_MODEL", "claude-sonnet-4-5")  # Claude via LingYai

TOP_K_VECTOR  = 15
TOP_K_KEYWORD = 10
TOP_K_FINAL   = 10   # returned to caller

# ─── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Culinary Mind — Y System Retrieval API",
    description="L0 principle retrieval with vector + keyword hybrid search",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# Lazy singletons
_driver = None
_http   = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    return _driver


def get_http():
    global _http
    if _http is None:
        _http = httpx.Client(trust_env=False, timeout=60)
    return _http


# ─── Pydantic models ────────────────────────────────────────────────────────────

class RetrieveRequest(BaseModel):
    q: str = Field(..., description="User question")
    top_k: int = Field(TOP_K_FINAL, ge=1, le=50)
    return_contexts: bool = Field(True, description="Return full context list for RAGAS")
    domain_filter: str | None = Field(None, description="Optional: filter by domain")
    generate_answer: bool = Field(True, description="Generate LLM answer from contexts")


class Context(BaseModel):
    chunk_id:  str
    source:    str   # source_book
    score:     float
    text:      str   # scientific_statement
    domain:    str
    retrieval_method: str  # "vector" | "keyword" | "hybrid"


class RetrieveResponse(BaseModel):
    question: str
    answer:   str
    contexts: list[Context]
    latency_ms: int
    total_candidates: int


# ─── Embedding ──────────────────────────────────────────────────────────────────

def embed_query(text: str) -> list[float]:
    resp = get_http().post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text[:2000]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


# ─── Retrieval ──────────────────────────────────────────────────────────────────

def vector_search(query_vec: list[float], top_k: int,
                  domain_filter: str | None) -> list[dict]:
    """Vector similarity search via Neo4j built-in index."""
    where_clause = f"WHERE p.domain = '{domain_filter}'" if domain_filter else ""
    query = f"""
    CALL db.index.vector.queryNodes('principles_embedding', $top_k, $embedding)
    YIELD node AS p, score
    {where_clause}
    RETURN p.id AS chunk_id,
           p.statement AS text,
           p.source_book AS source,
           p.domain AS domain,
           p.confidence AS confidence,
           score
    ORDER BY score DESC
    LIMIT $top_k
    """
    with get_driver().session() as s:
        result = s.run(query, embedding=query_vec, top_k=top_k)
        return [dict(r) for r in result]


def keyword_search(query: str, top_k: int, domain_filter: str | None) -> list[dict]:
    """Full-text keyword search via Cypher CONTAINS (fallback if FTS index absent)."""
    # Extract keywords: split and filter stopwords
    stopwords = {"为什么","怎么","什么","的","了","是","在","和","与","how","why","what",
                 "is","are","the","a","an","of","to","for","in","that","this"}
    words = [w for w in query.lower().split() if w not in stopwords and len(w) > 1]
    if not words:
        return []

    # Build CONTAINS conditions for top 3 words
    conditions = " OR ".join(
        f"toLower(p.statement) CONTAINS '{w}'" for w in words[:3]
    )
    domain_clause = f"AND p.domain = '{domain_filter}'" if domain_filter else ""
    cypher = f"""
    MATCH (p:Principle)
    WHERE ({conditions}) {domain_clause}
    RETURN p.id AS chunk_id,
           p.statement AS text,
           p.source_book AS source,
           p.domain AS domain,
           p.confidence AS confidence,
           0.5 AS score
    LIMIT $top_k
    """
    with get_driver().session() as s:
        result = s.run(cypher, top_k=top_k)
        return [dict(r) for r in result]


def hybrid_merge(vector_results: list[dict], keyword_results: list[dict],
                 top_k: int) -> list[dict]:
    """RRF (Reciprocal Rank Fusion) merge."""
    seen = {}
    for rank, r in enumerate(vector_results):
        cid = r["chunk_id"]
        seen[cid] = r.copy()
        seen[cid]["rrf_score"] = 1.0 / (60 + rank + 1)
        seen[cid]["retrieval_method"] = "vector"

    for rank, r in enumerate(keyword_results):
        cid = r["chunk_id"]
        rrf_add = 1.0 / (60 + rank + 1)
        if cid in seen:
            seen[cid]["rrf_score"] += rrf_add
            seen[cid]["retrieval_method"] = "hybrid"
        else:
            seen[cid] = r.copy()
            seen[cid]["rrf_score"] = rrf_add
            seen[cid]["retrieval_method"] = "keyword"

    merged = sorted(seen.values(), key=lambda x: x["rrf_score"], reverse=True)
    return merged[:top_k]


# ─── Answer generation ──────────────────────────────────────────────────────────

def generate_answer(question: str, contexts: list[dict]) -> str:
    """Generate answer from contexts using Claude via LingYai API (primary)."""
    context_text = "\n\n".join(
        f"[{i+1}] ({c['source']}) {c['text']}"
        for i, c in enumerate(contexts[:8])
    )
    prompt = f"""你是一个烹饪科学专家。根据以下科学原理回答问题。
只使用提供的原理作为依据，如果原理不足以回答，明确说明。

## 问题
{question}

## 科学原理依据
{context_text}

## 回答（中文，简洁专业，引用原理编号）
"""
    # Primary: Claude via LingYai API (OpenAI-compatible)
    if LINGYAI_ENDPOINT and LINGYAI_KEY:
        try:
            resp = get_http().post(
                f"{LINGYAI_ENDPOINT}/chat/completions",
                headers={"Authorization": f"Bearer {LINGYAI_KEY}"},
                json={
                    "model": ANSWER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 768,
                },
                timeout=90,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"[Answer generation failed: {e}]"

    return "[No answer generated — set L0_API_ENDPOINT/L0_API_KEY env vars]"


# ─── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    try:
        with get_driver().session() as s:
            result = s.run("MATCH (p:Principle) RETURN count(p) AS n")
            n = result.single()["n"]
        return {"status": "ok", "principle_count": n}
    except Exception as e:
        raise HTTPException(503, f"Neo4j unavailable: {e}")


@app.get("/stats")
def stats():
    with get_driver().session() as s:
        total     = s.run("MATCH (p:Principle) RETURN count(p) AS n").single()["n"]
        by_domain = s.run("""
            MATCH (p:Principle)
            RETURN p.domain AS domain, count(p) AS n
            ORDER BY n DESC
        """)
        domains = [{"domain": r["domain"], "count": r["n"]} for r in by_domain]
    return {"total_principles": total, "by_domain": domains}


@app.post("/retrieve", response_model=RetrieveResponse)
def retrieve(req: RetrieveRequest):
    t0 = time.time()

    # 1. Embed query
    try:
        query_vec = embed_query(req.q)
    except Exception as e:
        raise HTTPException(503, f"Embedding failed: {e}")

    # 2. Vector search
    vec_results = vector_search(query_vec, TOP_K_VECTOR, req.domain_filter)

    # 3. Keyword search
    kw_results  = keyword_search(req.q, TOP_K_KEYWORD, req.domain_filter)

    # 4. Hybrid merge
    merged = hybrid_merge(vec_results, kw_results, req.top_k)
    total_candidates = len(vec_results) + len(kw_results)

    # 5. Build context objects
    contexts = [
        Context(
            chunk_id = r["chunk_id"],
            source   = r["source"],
            score    = float(r.get("rrf_score", r.get("score", 0.0))),
            text     = r["text"],
            domain   = r["domain"],
            retrieval_method = r.get("retrieval_method", "hybrid"),
        )
        for r in merged
    ]

    # 6. Generate answer
    answer = ""
    if req.generate_answer and contexts:
        answer = generate_answer(req.q, [c.model_dump() for c in contexts])

    latency_ms = int((time.time() - t0) * 1000)

    if not req.return_contexts:
        contexts = []

    return RetrieveResponse(
        question=req.q,
        answer=answer,
        contexts=contexts,
        latency_ms=latency_ms,
        total_candidates=total_candidates,
    )


# Allow direct run for quick testing
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.y_system.retrieval_api:app", host="0.0.0.0", port=8760, reload=True)
