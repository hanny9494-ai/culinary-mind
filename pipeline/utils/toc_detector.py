#!/usr/bin/env python3
"""
TOC自动检测模块 — 三层fallback：
  层1: PDF bookmark (PyMuPDF)
  层2: qwen-vl扫前30页识别目录页
  层3: 返回空列表（调用方走auto-chapter-split）
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import fitz
import requests


# ── 层1: PDF bookmark ────────────────────────────────────────────────────────

def _extract_bookmarks(pdf_path: Path) -> list[dict]:
    doc = fitz.open(str(pdf_path))
    toc = doc.get_toc()  # [[level, title, page], ...]
    doc.close()
    if not toc:
        return []
    return [{"title": t.strip(), "page": p, "level": l} for l, t, p in toc if t.strip()]


# ── 层2: qwen-vl扫描前30页 ──────────────────────────────────────────────────

TOC_VISION_PROMPT = """这是一本书的某一页截图。请判断这是不是目录页(Table of Contents)。

判断标准：
- 目录页通常有多行"标题...页码"的格式
- 可能是中文、英文、法文或混合语言
- 可能分多栏

如果不是目录页，只输出：{"is_toc": false}

如果是目录页，提取所有章节条目，输出JSON：
{
  "is_toc": true,
  "entries": [
    {"title": "章节标题", "page": 页码数字, "level": 1},
    {"title": "子章节标题", "page": 页码数字, "level": 2}
  ]
}

规则：
- level 1 = 大章节/PART标题
- level 2 = 子章节/小节
- page必须是整数
- 只提取真实的目录条目，不要提取页眉页脚"""


def _call_vision_toc(img_bytes: bytes, api_key: str, api_url: str, model: str) -> list[dict]:
    """调用 qwen-vl 判断单页是否目录页，是则返回 entries。"""
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": TOC_VISION_PROMPT},
            ],
        }],
        "max_tokens": 4000,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(api_url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()

    # 清洗 markdown 代码块
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if not data.get("is_toc"):
        return []
    return data.get("entries", [])


def _dedupe_entries(entries: list[dict]) -> list[dict]:
    """按 title+page 去重。"""
    seen = set()
    result = []
    for e in entries:
        key = (e.get("title", "").strip(), e.get("page", 0))
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result


def _scan_toc_pages_vision(
    pdf_path: Path, api_key: str, api_url: str, model: str, max_pages: int = 30
) -> tuple[list[dict], list[int]]:
    """扫描PDF前N页，找目录页并提取entries。返回 (entries, toc_page_numbers)。"""
    doc = fitz.open(str(pdf_path))
    matrix = fitz.Matrix(150 / 72, 150 / 72)

    all_entries = []
    toc_pages = []
    for i in range(min(max_pages, doc.page_count)):
        pix = doc[i].get_pixmap(matrix=matrix, alpha=False)
        img_bytes = pix.tobytes("png")

        entries = _call_vision_toc(img_bytes, api_key, api_url, model)
        if entries:
            all_entries.extend(entries)
            toc_pages.append(i + 1)  # 1-indexed
            print(f"  TOC检测: 第{i+1}页是目录页，提取{len(entries)}条")

    doc.close()
    return _dedupe_entries(all_entries), toc_pages


# ── 主入口 ───────────────────────────────────────────────────────────────────

def detect_toc(
    pdf_path: Path,
    dashscope_api_key: str = "",
    dashscope_url: str = "",
    dashscope_model: str = "",
) -> tuple[list[dict], str]:
    """
    三层检测TOC，逐层fallback。
    返回 (entries, source) — source 为 "bookmark" / "vision" / "none"
    """
    # 层1: PDF bookmark
    entries = _extract_bookmarks(pdf_path)
    if entries:
        print(f"  TOC来源: PDF bookmark ({len(entries)}条)")
        return entries, "bookmark"

    # 层2: qwen-vl视觉扫描
    if dashscope_api_key and dashscope_url:
        print(f"  TOC层1(bookmark)为空，尝试层2(qwen-vl扫描前30页)...")
        entries, toc_pages = _scan_toc_pages_vision(
            pdf_path, dashscope_api_key, dashscope_url, dashscope_model
        )
        if entries:
            pages_str = ", ".join(f"p{p}" for p in toc_pages)
            print(f"  TOC来源: qwen-vl目录页扫描 ({pages_str})，{len(entries)}条")
            return entries, "vision"

    # 层3: 无TOC
    print("  TOC检测: 未找到目录结构，将使用auto-chapter-split")
    return [], "none"


# ── TOC → mc_toc.json 格式转换 ──────────────────────────────────────────────

def generate_toc_config(entries: list[dict], book_id: str) -> list[dict]:
    """
    将flat entries转换为mc_toc.json兼容格式。
    level 1 → chapter, level 2 → section
    """
    chapters = []
    current_chapter = None

    for e in entries:
        title = e.get("title", "").strip()
        level = e.get("level", 1)
        page = e.get("page", 0)

        if level == 1 or current_chapter is None:
            if current_chapter is not None:
                chapters.append(current_chapter)
            current_chapter = {
                "chapter_num": len(chapters) + 1,
                "chapter_title": title,
                "start_page": page,
                "sections": [],
            }
        else:
            if current_chapter is not None:
                current_chapter["sections"].append(title)

    if current_chapter is not None:
        chapters.append(current_chapter)

    return chapters


def print_toc_candidate(chapters: list[dict], source: str, toc_pages: list[int] | None = None):
    """打印人类可读的TOC候选摘要。"""
    pages_info = ""
    if toc_pages:
        pages_info = f" ({', '.join(f'p{p}' for p in toc_pages)})"

    print(f"\n=== TOC候选（需人工审阅）===")
    print(f"来源: {source}{pages_info}")
    print()
    for ch in chapters:
        print(f"[{ch['chapter_num']}] {ch['chapter_title']} (p{ch.get('start_page', '?')})")
        for sec in ch.get("sections", []):
            print(f"    {sec}")
    print()
    print("确认后写入 config/mc_toc.json")
    print("⚠️ agent不能自动写入mc_toc.json，必须等人工确认")


def save_toc_candidate(chapters: list[dict], output_dir: Path, book_id: str, source: str):
    """保存候选TOC到 output/{book_id}/toc_candidate.json。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate = {
        "book_id": book_id,
        "source": source,
        "chapters": chapters,
    }
    path = output_dir / "toc_candidate.json"
    path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n候选TOC已保存: {path}")
    return path
