#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any


for _key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_key, None)
os.environ["no_proxy"] = "localhost,127.0.0.1"

TARGET_CHARS = 3200
MAX_CHARS = 4200


def clean_book_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?m)^## Page \d+\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_into_chunks(text: str, target_chars: int = TARGET_CHARS, max_chars: int = MAX_CHARS) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("\n\n".join(current).strip())
            current = []
            current_len = 0

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            flush()
            start = 0
            while start < len(paragraph):
                end = min(start + max_chars, len(paragraph))
                if end < len(paragraph):
                    split_at = paragraph.rfind("。", start, end)
                    split_at = max(split_at, paragraph.rfind("；", start, end))
                    split_at = max(split_at, paragraph.rfind("\n", start, end))
                    if split_at > start + max_chars // 2:
                        end = split_at + 1
                chunks.append(paragraph[start:end].strip())
                start = end
            continue

        next_len = current_len + len(paragraph) + (2 if current else 0)
        if current and next_len > max_chars:
            flush()
        current.append(paragraph)
        current_len += len(paragraph) + (2 if len(current) > 1 else 0)
        if current_len >= target_chars:
            flush()

    flush()
    return [chunk for chunk in chunks if chunk.strip()]


def summarize(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    lengths = [len(str(item.get("full_text") or "")) for item in chunks if str(item.get("full_text") or "").strip()]
    if not lengths:
        return {"total_chunks": 0, "avg_chars": 0, "min_chars": 0, "max_chars": 0}
    return {
        "total_chunks": len(lengths),
        "avg_chars": round(sum(lengths) / len(lengths), 2),
        "min_chars": min(lengths),
        "max_chars": max(lengths),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare chunks_raw.json and chunks_smart.json from one book.md for Stage4")
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--book-md", required=True)
    parser.add_argument("--stage1-dir", required=True)
    args = parser.parse_args()

    book_md = Path(args.book_md).expanduser()
    stage1_dir = Path(args.stage1_dir).expanduser()
    stage1_dir.mkdir(parents=True, exist_ok=True)

    raw_merged = stage1_dir / "raw_merged.md"
    chunks_raw_path = stage1_dir / "chunks_raw.json"
    chunks_smart_path = stage1_dir / "chunks_smart.json"
    quality_path = stage1_dir / "step4_quality.json"

    text = clean_book_text(book_md.read_text(encoding="utf-8", errors="ignore"))
    raw_merged.write_text(text + "\n", encoding="utf-8")

    chunk_texts = split_into_chunks(text)
    chunks_raw: list[dict[str, Any]] = []
    chunks_smart: list[dict[str, Any]] = []
    for idx, chunk_text in enumerate(chunk_texts):
        base = {
            "chunk_idx": idx,
            "full_text": chunk_text,
            "chapter_num": 1,
            "chapter_title": args.book_id,
            "chapter_start": args.book_id,
            "chapter_end": "END",
            "source_book": args.book_id,
        }
        chunks_raw.append(base)
        chunks_smart.append(
            {
                **base,
                "summary": None,
                "topics": [],
                "chunk_type": None,
            }
        )

    chunks_raw_path.write_text(json.dumps(chunks_raw, ensure_ascii=False, indent=2), encoding="utf-8")
    chunks_smart_path.write_text(json.dumps(chunks_smart, ensure_ascii=False, indent=2), encoding="utf-8")
    quality_path.write_text(json.dumps(summarize(chunks_raw), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"book_id={args.book_id} chunks={len(chunks_smart)} stage1_dir={stage1_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
