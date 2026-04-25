from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import requests


class VisionError(RuntimeError):
    """Raised when the DashScope response cannot be parsed."""


VISION_PROMPT = """请逐一提取这一页的每个独立内容元素，用JSON输出。

格式必须归一化为：
{
  "tables": [{"title": "", "markdown": "", "notes": ""}],
  "figures": [{"type": "figure", "description": ""}],
  "text_blocks": ["..."]
}

规则：
- 每个表格单独一个元素。
- 每张图片、示意图或图表单独一个元素。
- 页面上的可见说明文字，如果明显属于视觉元素，可放进 text_blocks。
- 不要抄写普通正文段落。
- 只输出 JSON，不要解释。
"""


def _extract_json_value(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    starts = [(stripped.find("{"), "{"), (stripped.find("["), "[")]
    starts = [(idx, token) for idx, token in starts if idx != -1]
    if not starts:
        raise VisionError("No JSON payload found in vision response")
    start, token = min(starts, key=lambda item: item[0])
    end_token = "}" if token == "{" else "]"
    end = stripped.rfind(end_token)
    if end == -1 or end <= start:
        raise VisionError("Incomplete JSON payload in vision response")
    return json.loads(stripped[start : end + 1])


def _normalize_payload(payload: Any) -> dict[str, Any]:
    tables: list[dict[str, str]] = []
    figures: list[dict[str, str]] = []
    text_blocks: list[str] = []

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            if item_type == "table":
                tables.append({"title": "", "markdown": content, "notes": ""})
            elif item_type == "figure":
                figures.append({"type": str(item.get("figure_type") or "figure"), "description": content})
            else:
                text_blocks.append(content)
        return {"tables": tables, "figures": figures, "text_blocks": text_blocks}

    if not isinstance(payload, dict):
        raise VisionError("Unsupported vision payload type")

    raw_tables = payload.get("tables") or []
    raw_figures = payload.get("figures") or []
    raw_text_blocks = payload.get("text_blocks") or []

    if not isinstance(raw_text_blocks, list):
        raw_text_blocks = [raw_text_blocks]

    for table in raw_tables:
        if not isinstance(table, dict):
            continue
        markdown = str(table.get("markdown") or "").strip()
        if not markdown:
            continue
        tables.append(
            {
                "title": str(table.get("title") or "").strip(),
                "markdown": markdown,
                "notes": str(table.get("notes") or "").strip(),
            }
        )

    for figure in raw_figures:
        if not isinstance(figure, dict):
            continue
        description = str(figure.get("description") or "").strip()
        if not description:
            continue
        figures.append(
            {
                "type": str(figure.get("type") or "figure").strip() or "figure",
                "description": description,
            }
        )

    for text in raw_text_blocks:
        normalized = str(text or "").strip()
        if normalized:
            text_blocks.append(normalized)

    return {"tables": tables, "figures": figures, "text_blocks": text_blocks}


def recognize_page(png_path: str | Path, api_key: str, model: str) -> dict[str, Any]:
    path = Path(png_path)
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64.b64encode(path.read_bytes()).decode('utf-8')}"
                        },
                    },
                ],
            }
        ],
        "max_tokens": 2048,
    }
    response = requests.post(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=180,
    )
    response.raise_for_status()
    body = response.json()
    message = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    parsed = _normalize_payload(_extract_json_value(message))
    parsed["raw_response"] = message
    return parsed
