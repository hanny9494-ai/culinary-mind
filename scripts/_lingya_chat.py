"""Shared Lingya chat-completions HTTP helper."""
from __future__ import annotations

import time

import httpx


def _should_retry_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _backoff_delay(backoff: tuple[float, ...], attempt: int) -> float:
    if not backoff:
        return 0
    if attempt < len(backoff):
        return backoff[attempt]
    return backoff[-1] * (2 ** (attempt - len(backoff) + 1))


def post_lingya_chat(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    payload: dict,
    *,
    max_retries: int = 3,
    timeout: float = 600,
    backoff: tuple[float, ...] = (5, 15, 45),
) -> httpx.Response:
    """POST to Lingya chat with retry on retryable HTTP and transport errors."""
    for attempt in range(max_retries + 1):
        try:
            resp = client.post(url, headers=headers, json=payload, timeout=timeout)
            if _should_retry_status(resp.status_code):
                if attempt < max_retries:
                    time.sleep(_backoff_delay(backoff, attempt))
                    continue
                resp.raise_for_status()
            return resp
        except (httpx.RequestError, httpx.HTTPError):
            if attempt < max_retries:
                time.sleep(_backoff_delay(backoff, attempt))
                continue
            raise

    raise RuntimeError("Lingya chat request failed")
