"""Ollama qwen3-embedding:8b helper skeleton for substitute resolution."""
from __future__ import annotations

import os
from typing import Any

import httpx


for _proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_proxy_var, None)


EMBED_MODEL = "qwen3-embedding:8b"
OLLAMA_ENDPOINT = "http://127.0.0.1:11434"


def embed_texts(texts: list[str], *, endpoint: str = OLLAMA_ENDPOINT, model: str = EMBED_MODEL) -> list[list[float]]:
    payload = {"model": model, "input": texts}
    with httpx.Client(trust_env=False, timeout=600) as client:
        response = client.post(endpoint.rstrip("/") + "/api/embed", json=payload)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
    embeddings = data.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise ValueError("Ollama embedding response length mismatch")
    return embeddings


def resolve_substitute_text(
    text: str,
    all_canonical_ids: set[str],
    embedding_index: Any,
    threshold: float = 0.78,
) -> str | None:
    """Day 1 skeleton for Step 6 substitute matching."""
    normalized = " ".join(text.lower().replace("_", " ").split())
    if normalized.replace(" ", "_") in all_canonical_ids:
        return normalized.replace(" ", "_")
    if embedding_index is None:
        return None
    query_embedding = embed_texts([normalized])[0]
    matches = embedding_index.search(query_embedding, top_k=5)
    if matches and matches[0].score >= threshold:
        return matches[0].canonical_id
    return None
