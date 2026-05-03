from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path
from unittest import mock

import httpx


ROOT = Path(__file__).resolve().parents[1]
PYTHON_FILES = [
    ROOT / "scripts" / "agent_pipeline.py",
    ROOT / "scripts" / "l0_formula_gemini.py",
    ROOT / "scripts" / "y_s1" / "import_l0_neo4j.py",
    ROOT / "src" / "evaluation" / "run_ragas.py",
]


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://api.lingyaai.cn")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)


def reload_module(name: str):
    if name in sys.modules:
        return importlib.reload(sys.modules[name])
    return importlib.import_module(name)


def test_import_l0_neo4j_embedding_call():
    """L0 import embedder routes through local Ollama qwen3-embedding:8b.

    repo-curator 2026-05-02 reverted the embedding path from Lingya/Gemini
    back to local Ollama (free, on-host). Chat / completion still goes
    through Lingya in other modules — only embeddings stay local.
    """
    mod = reload_module("scripts.y_s1.import_l0_neo4j")

    def fake_post(self, url, headers=None, json=None, timeout=None):
        # Ollama runs locally and uses no Authorization header.
        assert url.endswith("/api/embed"), f"unexpected URL: {url}"
        assert "127.0.0.1" in url or "localhost" in url, f"non-local URL: {url}"
        assert headers is None or "Authorization" not in (headers or {})
        assert json["model"] == "qwen3-embedding:8b"
        assert isinstance(json["input"], list)
        assert all(isinstance(item, str) for item in json["input"])
        assert timeout >= 600
        return FakeResponse({"embeddings": [[0.1] * 4096]})

    with mock.patch("httpx.Client.post", new=fake_post):
        with httpx.Client(trust_env=False, timeout=600) as client:
            result = mod.get_embeddings_gemini(["hello"], client)

    assert result == [[0.1] * 4096]
    assert mod.EMBED_DIM == 4096
    assert mod.EMBED_MODEL == "qwen3-embedding:8b"
    # Legacy aliases still resolve to the new local-Ollama values.
    assert mod.GEMINI_EMBED_DIM == 4096
    assert mod.GEMINI_EMBED_MODEL == "qwen3-embedding:8b"


def test_get_embeddings_ollama_length_mismatch_raises():
    """P1.3 — wrong-length Ollama response should raise ValueError, not silently truncate."""
    mod = reload_module("scripts.y_s1.import_l0_neo4j")

    def fake_post_short(self, url, headers=None, json=None, timeout=None):
        # Return only 1 embedding for 3 inputs — old code would zip() and lose 2.
        return FakeResponse({"embeddings": [[0.1] * 4096]})

    with mock.patch("httpx.Client.post", new=fake_post_short):
        with httpx.Client(trust_env=False, timeout=600) as client:
            try:
                mod.get_embeddings_ollama(["a", "b", "c"], client)
            except ValueError as e:
                assert "1" in str(e) and "3" in str(e)
                return
            raise AssertionError("expected ValueError on length mismatch")


def test_run_ragas_judge_call():
    with mock.patch.dict(
        os.environ,
        {"L0_API_KEY": "test-key", "L0_API_ENDPOINT": "https://api.lingyaai.cn"},
    ):
        mod = reload_module("src.evaluation.run_ragas")

        def fake_post(self, url, headers=None, json=None, timeout=None):
            assert url.endswith("/v1/chat/completions")
            assert headers["Authorization"].startswith("Bearer ")
            assert json["model"] == "gemini-3.1-pro-preview-thinking"
            assert json["messages"][0]["role"] == "user"
            assert timeout >= 600
            return FakeResponse({"choices": [{"message": {"content": "0.85"}}]})

        with mock.patch("httpx.Client.post", new=fake_post):
            with httpx.Client(trust_env=False, timeout=600) as client:
                score = mod.llm_judge(client, "Score this answer.")

        assert score == 0.85


def test_agent_pipeline_extractor_call():
    with mock.patch.dict(
        os.environ,
        {"L0_API_KEY": "test-key", "L0_API_ENDPOINT": "https://api.lingyaai.cn"},
    ):
        mod = reload_module("scripts.agent_pipeline")

        def fake_post(self, url, headers=None, json=None, timeout=None):
            assert url.endswith("/v1/chat/completions")
            assert headers["Authorization"].startswith("Bearer ")
            assert json["model"] == "gemini-3.1-pro-preview-thinking"
            assert json["messages"][0]["role"] == "user"
            assert timeout >= 600
            return FakeResponse({
                "choices": [{
                    "message": {
                        "content": (
                            '{"formula_type":"algebraic_law",'
                            '"sympy_expression":"x + 1"}'
                        )
                    }
                }]
            })

        with mock.patch("httpx.Client.post", new=fake_post):
            state = mod.AgentState("x plus one")
            result = mod.extractor_agent(state, "legacy-key")

        assert result.parsed_json["formula_type"] == "algebraic_law"
        assert ("google." + "generativeai") not in sys.modules


def test_no_google_genai_imports():
    genai_import = "import google." + "generativeai"
    google_api_url = "generativelanguage." + "googleapis.com"
    for path in PYTHON_FILES:
        source = path.read_text(encoding="utf-8")
        assert genai_import not in source
        assert google_api_url not in source


def test_trust_env_false():
    client_pattern = re.compile(r"httpx\.Client\((?P<args>.*?)\)", re.DOTALL)
    for path in PYTHON_FILES:
        source = path.read_text(encoding="utf-8")
        for match in client_pattern.finditer(source):
            assert "trust_env=False" in match.group("args")


# ── PR #21 post-merge gap (B1, B2) — repo-curator dispatch_1777814971880 ──

def test_lingya_chat_transport_retry_then_success():
    """B1 — _post_lingya_chat / post_lingya_chat must retry on httpx.RequestError
    (not just on 429/5xx). First call raises transport error, second succeeds.
    """
    import time as _time
    mod = reload_module("scripts._lingya_chat")

    call_count = {"n": 0}

    def fake_post(self, url, headers=None, json=None, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.RequestError("simulated network jitter", request=httpx.Request("POST", url))
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    # Skip the real backoff sleep so the test stays fast.
    with mock.patch("httpx.Client.post", new=fake_post), \
         mock.patch.object(_time, "sleep", lambda _s: None), \
         mock.patch.object(mod.time, "sleep", lambda _s: None):
        with httpx.Client(trust_env=False, timeout=600) as client:
            resp = mod.post_lingya_chat(
                client,
                "https://api.lingyaai.cn/v1/chat/completions",
                {"Authorization": "Bearer x", "Content-Type": "application/json"},
                {"model": "gemini-3.1-pro-preview-thinking", "messages": []},
                backoff=(0, 0, 0),
            )

    assert call_count["n"] == 2, f"expected 2 calls (1 fail + 1 success), got {call_count['n']}"
    assert resp.json()["choices"][0]["message"]["content"] == "ok"


def test_get_embeddings_ollama_dim_mismatch_raises():
    """B2 — get_embeddings_ollama must raise ValueError when Ollama returns a
    vector of the wrong dimension (e.g. 512 instead of 4096).
    """
    mod = reload_module("scripts.y_s1.import_l0_neo4j")

    def fake_post_wrong_dim(self, url, headers=None, json=None, timeout=None):
        # Right count (1 vector for 1 input), wrong dim (512 instead of 4096).
        return FakeResponse({"embeddings": [[0.1] * 512]})

    with mock.patch("httpx.Client.post", new=fake_post_wrong_dim):
        with httpx.Client(trust_env=False, timeout=600) as client:
            try:
                mod.get_embeddings_ollama(["hello"], client)
            except ValueError as e:
                msg = str(e)
                assert "512" in msg, f"expected dim 512 in error, got: {msg}"
                assert "4096" in msg, f"expected expected-dim 4096 in error, got: {msg}"
                return
            raise AssertionError("expected ValueError on dim mismatch")
