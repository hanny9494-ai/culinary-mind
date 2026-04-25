#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import requests
import yaml


DEFAULT_ANTHROPIC_VERSION = "2023-06-01"


class ClaudeClientError(RuntimeError):
    """Raised when the Claude proxy request cannot be completed."""


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\$\{([^}]+)\}", lambda match: os.environ.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def load_api_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ClaudeClientError(f"Config root must be an object: {config_path}")
    return _expand_env(payload)


def clone_config(config: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(config)


def select_model_name(config: dict[str, Any], preferred: str = "distill") -> str:
    claude_cfg = config.get("claude") or {}
    models = claude_cfg.get("models") or {}
    explicit = str(claude_cfg.get("model") or "").strip()
    if explicit:
        return explicit
    preferred_model = str(models.get(preferred) or "").strip()
    if preferred_model:
        return preferred_model
    for value in models.values():
        model_name = str(value or "").strip()
        if model_name:
            return model_name
    return ""


def build_runtime_config(
    config: dict[str, Any],
    *,
    model_name: str | None = None,
    model_key: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    runtime = clone_config(config)
    claude_cfg = runtime.setdefault("claude", {})
    if model_name:
        claude_cfg["model"] = model_name
    elif model_key:
        selected = select_model_name(runtime, model_key)
        if selected:
            claude_cfg["model"] = selected
    if max_tokens is not None:
        claude_cfg["max_tokens"] = int(max_tokens)
    return runtime


def _normalize_authorization(api_key: str) -> str:
    token = str(api_key or "").strip()
    if not token:
        return "Bearer"
    if token.lower().startswith("bearer "):
        return token
    if token.lower() == "bearer":
        return "Bearer"
    return f"Bearer {token}"


def call_claude(prompt: str, config: dict[str, Any] | str | Path, system: str | None = None) -> dict[str, Any]:
    runtime = load_api_config(config) if isinstance(config, (str, Path)) else clone_config(config)
    claude_cfg = runtime.get("claude") or {}

    endpoint = str(claude_cfg.get("endpoint") or "").strip()
    api_key = str(claude_cfg.get("api_key") or "").strip()
    model = select_model_name(runtime)
    timeout_sec = int(claude_cfg.get("timeout_sec") or 90)
    max_retries = max(1, int(claude_cfg.get("max_retries") or 3))
    max_tokens = int(claude_cfg.get("max_tokens") or 1000)
    anthropic_version = str(claude_cfg.get("anthropic_version") or DEFAULT_ANTHROPIC_VERSION)

    if not endpoint:
        raise ClaudeClientError("Missing claude.endpoint in config")
    if not model:
        raise ClaudeClientError("Missing Claude model in config")

    headers = {
        "Content-Type": "application/json",
        "Authorization": _normalize_authorization(api_key),
        "anthropic-version": anthropic_version,
    }
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout_sec)
            response.raise_for_status()
            data = response.json()
            text_parts = []
            for block in data.get("content", []):
                block_text = block.get("text")
                if isinstance(block_text, str):
                    text_parts.append(block_text)
            usage = data.get("usage") or {}
            return {
                "content": "\n".join(part for part in text_parts if part).strip(),
                "in_tokens": int(usage.get("input_tokens") or 0),
                "out_tokens": int(usage.get("output_tokens") or 0),
            }
        except (requests.RequestException, ValueError, TypeError) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            time.sleep(min(15, 2 * attempt))

    raise ClaudeClientError(f"Claude request failed after {max_retries} attempts: {last_error}")
