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
    with mock.patch.dict(
        os.environ,
        {"L0_API_KEY": "test-key", "L0_API_ENDPOINT": "https://api.lingyaai.cn"},
    ):
        mod = reload_module("scripts.y_s1.import_l0_neo4j")

        def fake_post(self, url, headers=None, json=None, timeout=None):
            assert url.endswith("/v1/embeddings")
            assert headers["Authorization"].startswith("Bearer ")
            assert headers["Authorization"] != "test-key"
            assert json["model"] == "gemini-embedding-001"
            assert isinstance(json["input"], list)
            assert all(isinstance(item, str) for item in json["input"])
            assert timeout >= 600
            return FakeResponse({"data": [{"embedding": [0.1] * 3072}]})

        with mock.patch("httpx.Client.post", new=fake_post):
            with httpx.Client(trust_env=False, timeout=600) as client:
                result = mod.get_embeddings_gemini(["hello"], client)

        assert result == [[0.1] * 3072]


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
