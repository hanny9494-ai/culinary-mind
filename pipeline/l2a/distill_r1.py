#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI


for _key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_key, None)
os.environ["no_proxy"] = "localhost,127.0.0.1"

MODEL = "qwen3.5-flash"
MAX_CHUNK_BYTES = 8 * 1024

SYSTEM_PROMPT = """你是食材抽取助手。请从书本文本里提取所有明确出现、被介绍、被讨论、被分类、被比较的食材名。

输出要求：
1. 只输出 JSON，不要解释。
2. 顶层格式必须是：
{
  "ingredients": [
    {
      "name_original": "原文里的食材名",
      "name_en": "英文名，没有则 null",
      "name_zh": "中文名，没有则 null",
      "category": "fish|shellfish|crustacean|cephalopod|seaweed|dried_seafood|meat|poultry|vegetable|fruit|mushroom|grain|legume|spice|condiment|fungus|other"
    }
  ]
}
3. 只提取真正的食材、原料、可食生物、海味乾貨，不要提取菜名、地名、品牌、人名、器具、加工动作、抽象概念。
4. 同一个 chunk 内去重。
5. 保留原文语言；若原文是中英混写，name_original 保留最直接的原始写法。
6. 不确定时宁缺勿滥。
"""


def extract_json_block(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model response")
    return text[start : end + 1]


def build_client() -> OpenAI:
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY is not set")
    return OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        http_client=httpx.Client(trust_env=False, timeout=300),
    )


def split_text_by_bytes(text: str, max_chunk_bytes: int = MAX_CHUNK_BYTES) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_bytes = 0

    def flush() -> None:
        nonlocal current, current_bytes
        if current:
            chunks.append("\n\n".join(current).strip())
            current = []
            current_bytes = 0

    for paragraph in paragraphs:
        para = paragraph.strip()
        para_bytes = len(para.encode("utf-8"))
        if para_bytes > max_chunk_bytes:
            flush()
            lines = [line.strip() for line in para.splitlines() if line.strip()]
            temp: list[str] = []
            temp_bytes = 0
            for line in lines:
                line_bytes = len(line.encode("utf-8"))
                if temp and temp_bytes + line_bytes + 2 > max_chunk_bytes:
                    chunks.append("\n".join(temp).strip())
                    temp = [line]
                    temp_bytes = line_bytes
                else:
                    temp.append(line)
                    temp_bytes += line_bytes + (2 if temp_bytes else 0)
            if temp:
                chunks.append("\n".join(temp).strip())
            continue

        sep_bytes = 2 if current else 0
        if current and current_bytes + para_bytes + sep_bytes > max_chunk_bytes:
            flush()
        current.append(para)
        current_bytes += para_bytes + (2 if len(current) > 1 else 0)

    flush()
    return [chunk for chunk in chunks if chunk.strip()]


def call_flash(client: OpenAI, chunk_text: str) -> list[dict[str, Any]]:
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.1,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"请从以下书本文本中提取所有食材名：\n\n{chunk_text}"},
        ],
        extra_body={"enable_thinking": False},
    )
    raw = response.choices[0].message.content or ""
    payload = json.loads(extract_json_block(raw))
    items = payload.get("ingredients") or []
    return [item for item in items if isinstance(item, dict)]


def normalize_item(item: dict[str, Any], source: str) -> dict[str, Any] | None:
    name_original = str(item.get("name_original") or "").strip()
    if not name_original:
        return None
    return {
        "name_original": name_original,
        "name_en": (str(item.get("name_en")).strip() if item.get("name_en") is not None else None) or None,
        "name_zh": (str(item.get("name_zh")).strip() if item.get("name_zh") is not None else None) or None,
        "category": str(item.get("category") or "other").strip() or "other",
        "source": source,
    }


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = (
            str(item.get("source") or "").strip(),
            str(item.get("name_original") or "").strip(),
            str(item.get("name_en") or "").strip(),
            str(item.get("name_zh") or "").strip(),
            str(item.get("category") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return default
    return json.loads(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract L2a ingredient mentions from one book.md using qwen3.5-flash")
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--book-md", required=True)
    parser.add_argument("--output", default="~/culinary-mind/output/l2a/book_ingredients.json")
    parser.add_argument("--cache-dir", default="~/culinary-mind/output/l2a/extract_cache")
    parser.add_argument("--replace-source", action="store_true", help="Replace existing items from this book source before writing output")
    args = parser.parse_args()

    book_md = Path(args.book_md).expanduser()
    output_path = Path(args.output).expanduser()
    cache_dir = Path(args.cache_dir).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{args.book_id}.jsonl"
    source = f"book:{args.book_id}"

    text = book_md.read_text(encoding="utf-8", errors="ignore")
    chunks = split_text_by_bytes(text, MAX_CHUNK_BYTES)
    print(f"book_id={args.book_id} chunks={len(chunks)}", flush=True)

    done_chunks: set[int] = set()
    cached_items: list[dict[str, Any]] = []
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            chunk_index = int(record.get("chunk_index", -1))
            if chunk_index >= 0:
                done_chunks.add(chunk_index)
            for raw_item in record.get("ingredients") or []:
                if isinstance(raw_item, dict):
                    normalized = normalize_item(raw_item, source)
                    if normalized:
                        cached_items.append(normalized)

    client = build_client()

    with cache_path.open("a", encoding="utf-8") as handle:
        for chunk_index, chunk_text in enumerate(chunks):
            if chunk_index in done_chunks:
                print(f"[skip] chunk {chunk_index + 1}/{len(chunks)}", flush=True)
                continue
            print(f"[extract] chunk {chunk_index + 1}/{len(chunks)}", flush=True)
            ingredients = call_flash(client, chunk_text)
            handle.write(
                json.dumps(
                    {
                        "chunk_index": chunk_index,
                        "ingredients": ingredients,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            handle.flush()
            for raw_item in ingredients:
                normalized = normalize_item(raw_item, source)
                if normalized:
                    cached_items.append(normalized)

    existing = load_json(output_path, [])
    if not isinstance(existing, list):
        existing = []
    if args.replace_source:
        existing = [item for item in existing if str(item.get("source") or "") != source]

    merged = dedupe_items(existing + cached_items)
    # Stamp L2a atom schema version on each item — see docs/schemas/l2a-atom-v1.1.md.
    for _item in merged:
        if isinstance(_item, dict):
            _item.setdefault("_v", "1.1")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    source_count = sum(1 for item in merged if str(item.get("source") or "") == source)
    print(f"source={source} items={source_count} output={output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
