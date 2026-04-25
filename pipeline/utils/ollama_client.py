from __future__ import annotations

import json
from typing import Any

import requests


class OllamaError(RuntimeError):
    """Raised when the Ollama API returns an invalid response."""


_BASE_URL = "http://localhost:11434"
_OPTIONS: dict[str, Any] = {"think": False}
# 绕过本地代理（http_proxy会拦截localhost请求导致Ollama连接失败）
_SESSION: requests.Session | None = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.trust_env = False  # 忽略 http_proxy / https_proxy
    return _SESSION


def configure(config: dict[str, Any] | None) -> None:
    """Configure the shared Ollama endpoint from `config/api.yaml`."""
    global _BASE_URL, _OPTIONS
    if not config:
        return
    _BASE_URL = str(config.get("url") or _BASE_URL).rstrip("/")
    options = config.get("options")
    if isinstance(options, dict):
        _OPTIONS = dict(options)


def generate(
    model: str,
    prompt: str,
    format: str = "json",
    timeout: int = 240,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": format,
        "options": _OPTIONS,
    }
    session = _get_session()
    response = session.post(f"{_BASE_URL}/api/generate", json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    text = str(body.get("response") or "").strip()
    if text:
        return text
    thinking = str(body.get("thinking") or "").strip()
    if thinking:
        return thinking
    raise OllamaError(f"Missing response text from Ollama: {json.dumps(body, ensure_ascii=False)[:500]}")
