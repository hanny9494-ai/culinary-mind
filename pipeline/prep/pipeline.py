#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
import yaml

from utils.merge import merge_mineru_vision
from utils.mineru_client import MineruError, upload_and_extract
from utils.ollama_client import configure as configure_ollama
from utils.ollama_client import generate as ollama_generate
from utils.vision_client import VisionError, recognize_page


STEP_STATUS = {
    0: "step0_done",
    1: "step1_done",
    2: "step2_done",
    3: "step3_done",
    4: "step4_done",
    5: "completed",
}

STATUS_ORDER = ["pending", "step0_done", "step1_done", "step2_done", "step3_done", "step4_done", "completed"]
PNG_DPI = 150
MC_BODY_START_HEADINGS = {
    "mc_vol2": "TRADITIONAL COOKING",
    "mc_vol3": "MEAT AND SEAFOOD",
    "mc_vol4": "THICKENERS",
}
SPLIT_PROMPT_TEMPLATE = """你要把一本书的单一章节片段切成多个原文 chunk。
只输出 JSON，格式必须是：
{{"chunks": ["chunk text 1", "chunk text 2"]}}

规则：
- 只能摘录输入原文，不能翻译，不能改写，不能总结，不能解释。
- 每个 chunk 必须是来自输入文本的连续原文片段。
- 按语义边界切分。
- 每个 chunk 目标长度约 300-400 字；如果是英文，约 180-260 words。
- 不要跨越章节边界。
- 表格、列表、图注尽量和附近正文放在同一 chunk。
- 不要输出空字符串。
- 不要输出除了 JSON 之外的任何文字。

Chapter boundary:
- Start heading: {chapter_start}
- End before: {chapter_end}

Chapter segment: {chapter_segment}

Chapter title: {chapter_title}

Chapter text:
{chapter_text}
"""
ANNOTATE_PROMPT_TEMPLATE = """你要为一个食品科学 chunk 生成检索用摘要和高精度 topics。
只输出 JSON，格式必须是：
{{
  "summary": "50字以内中文摘要",
  "topics": ["allowed_topic_1", "allowed_topic_2"],
  "chunk_type": "science|recipe|mixed|narrative"
}}

Allowed topics:
{topics}

Strict rules:
- Summary must be concise Chinese and <= 50 characters.
- Topics must be selected only from the allowed list.
- Choose 1-2 topics only.
- Prefer the main mechanism, not peripheral mentions.
- If uncertain, return the single most central topic.
- chunk_type must be exactly one of: "science", "recipe", "mixed", "narrative".
- Use "science" for mechanisms, causal explanations, parameter limits, experiments, or food science facts.
- Use "recipe" for ingredient lists, formulas, procedures, or dish recipes.
- Use "mixed" when science explanation and recipe/procedure content are both substantial.
- Use "narrative" for history, anecdotes, biography, or non-technical storytelling.

Chapter title: {chapter_title}
Section range: {chapter_start} -> {chapter_end}

Chunk:
{chunk_text}
"""


class PipelineError(RuntimeError):
    """Raised for predictable pipeline failures."""


@dataclass
class BookSpec:
    book_id: str
    title: str
    path: Path
    file_type: str

    @property
    def slug(self) -> str:
        return self.book_id.replace("mc_", "")


@dataclass
class Chapter:
    chapter_num: int
    chapter_title: str
    chapter_start: str
    chapter_end: str
    text: str


class FileGrowthWatchdog:
    def __init__(self, path: Path, timeout_minutes: int, label_ref: dict[str, str]) -> None:
        self.path = path
        self.timeout_seconds = max(1, timeout_minutes) * 60
        self.label_ref = label_ref
        self.last_size = self._size()
        self.last_growth = time.time()
        self.stopped = False
        self.timer: threading.Timer | None = None

    def _size(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0

    def _tick(self) -> None:
        if self.stopped:
            return
        current_size = self._size()
        if current_size > self.last_size:
            self.last_size = current_size
            self.last_growth = time.time()
        elif time.time() - self.last_growth > self.timeout_seconds:
            active = self.label_ref.get("active", "unknown")
            print(
                f"[watchdog] output file stalled: {self.path} active={active}",
                file=sys.stderr,
                flush=True,
            )
            os._exit(1)
        self.timer = threading.Timer(30, self._tick)
        self.timer.daemon = True
        self.timer.start()

    def start(self) -> None:
        self.timer = threading.Timer(30, self._tick)
        self.timer.daemon = True
        self.timer.start()

    def stop(self) -> None:
        self.stopped = True
        if self.timer is not None:
            self.timer.cancel()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else default


def save_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json_list(path: Path) -> list[Any]:
    data = load_json(path, [])
    return data if isinstance(data, list) else []


def status_rank(status: str) -> int:
    try:
        return STATUS_ORDER.index(status)
    except ValueError:
        return -1


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\$\{([^}]+)\}", lambda match: os.environ.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise PipelineError(f"YAML root must be an object: {path}")
    return expand_env(data)


def load_book(books_path: Path, book_id: str) -> BookSpec:
    payload = load_yaml(books_path)
    for item in payload.get("books") or []:
        if str(item.get("id") or "") != book_id:
            continue
        return BookSpec(
            book_id=book_id,
            title=str(item.get("title") or book_id),
            path=Path(str(item.get("path") or "")).expanduser(),
            file_type=str(item.get("type") or "pdf").lower(),
        )
    raise PipelineError(f"Book id not found in {books_path}: {book_id}")


def load_topics(domains_path: Path) -> list[str]:
    payload = load_json(domains_path, {})
    topics: list[str] = []
    for item in payload.get("domains") or []:
        topic_id = str(item.get("id") or "").strip()
        if topic_id:
            topics.append(topic_id)
    if not topics:
        raise PipelineError(f"No domain topics found in {domains_path}")
    return topics


def infer_resume_status(book: BookSpec, output_dir: Path) -> str:
    chunks_raw = output_dir / "chunks_raw.json"
    chunks_raw_data = load_json(chunks_raw, []) if chunks_raw.exists() else []
    step4_quality = load_json(output_dir / "step4_quality.json", {}) if (output_dir / "step4_quality.json").exists() else {}
    # Try new path first, fall back to old
    prep_dir = output_dir / "prep"
    stage1_dir_legacy = output_dir / "stage1"
    if (prep_dir / "chunks_smart.json").exists():
        _chunks_dir = prep_dir
    else:
        _chunks_dir = stage1_dir_legacy
    stage1_chunks = _chunks_dir / "chunks_smart.json"
    stage1_failures = _chunks_dir / "annotation_failures.json"
    stage1_chunks_data = load_json(stage1_chunks, []) if stage1_chunks.exists() else []
    stage1_failures_data = load_json(stage1_failures, []) if stage1_failures.exists() else []

    if (
        isinstance(stage1_chunks_data, list)
        and isinstance(chunks_raw_data, list)
        and len(stage1_chunks_data) > 0
        and len(stage1_chunks_data) == len(chunks_raw_data)
        and isinstance(stage1_failures_data, list)
        and len(stage1_failures_data) == 0
    ):
        return "completed"
    # step4_done 要求 step4_quality.json 存在且通过质检
    if (
        isinstance(chunks_raw_data, list)
        and len(chunks_raw_data) > 0
        and step4_quality
        and int(step4_quality.get("total_chunks") or 0) == len(chunks_raw_data)
        and int(step4_quality.get("lt50_chars") or 0) == 0
    ):
        return "step4_done"
    # chunks_raw存在但没有step4_quality → Step4未完成，回退到step3_done
    if isinstance(chunks_raw_data, list) and len(chunks_raw_data) > 0 and not step4_quality:
        return "step3_done"
    if (output_dir / "raw_merged.md").exists():
        return "step3_done"
    if (output_dir / "raw_vision.json").exists():
        return "step2_done"
    if (output_dir / "raw_mineru.md").exists():
        return "step1_done"
    if book.file_type == "epub" and (output_dir / f"{book.slug}.pdf").exists():
        return "step0_done"
    return "pending"


def write_progress(output_dir: Path, book: BookSpec, status: str) -> None:
    progress = {
        "book_id": book.book_id,
        "status": status,
        "updated_at": now_iso(),
        "inferred_from_outputs": True,
    }
    save_json(output_dir / "stage1_progress.json", progress)


def check_command_exists(name: str) -> None:
    from shutil import which

    if not which(name):
        raise PipelineError(f"Required command not found: {name}")


def resolve_work_pdf(book: BookSpec, output_dir: Path, dry_run: bool) -> Path:
    if book.file_type == "pdf":
        return book.path
    if book.file_type != "epub":
        raise PipelineError(f"Unsupported file type: {book.file_type}")
    out_pdf = output_dir / f"{book.slug}.pdf"
    if out_pdf.exists():
        return out_pdf
    if dry_run:
        return out_pdf
    check_command_exists("ebook-convert")
    subprocess.run(["ebook-convert", str(book.path), str(out_pdf)], check=True)
    return out_pdf


def get_pdf_page_count(pdf_path: Path) -> int:
    doc = fitz.open(str(pdf_path))
    try:
        return doc.page_count
    finally:
        doc.close()


def render_pdf_pages(pdf_path: Path, pages_dir: Path, dpi: int = PNG_DPI) -> list[Path]:
    ensure_dir(pages_dir)
    doc = fitz.open(str(pdf_path))
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    rendered: list[Path] = []
    try:
        for page_index in range(doc.page_count):
            out_path = pages_dir / f"page_{page_index + 1:04d}.png"
            if not out_path.exists():
                pix = doc.load_page(page_index).get_pixmap(matrix=matrix, alpha=False)
                pix.save(str(out_path))
            rendered.append(out_path)
    finally:
        doc.close()
    return rendered


def collect_image_paths(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"image_path", "img_path"} and isinstance(value, str):
                out.append(Path(value).name)
            else:
                collect_image_paths(value, out)
    elif isinstance(node, list):
        for item in node:
            collect_image_paths(item, out)


def collect_text_spans(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("content"), str):
            text = node["content"].strip()
            if text:
                out.append(text)
        for value in node.values():
            collect_text_spans(value, out)
    elif isinstance(node, list):
        for item in node:
            collect_text_spans(item, out)


def looks_like_page_label(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned or len(cleaned) > 24:
        return False
    if re.fullmatch(r"[ivxlcdmIVXLCDM]+", cleaned):
        return True
    if re.fullmatch(r"\d{1,4}", cleaned):
        return True
    if re.fullmatch(r"[A-Za-z]|\d+\s*[A-Za-z]?", cleaned):
        return True
    return False


def extract_page_label_candidates(page: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ["discarded_blocks", "preproc_blocks"]:
        for block in page.get(key) or []:
            texts: list[str] = []
            collect_text_spans(block, texts)
            joined = " ".join(texts).strip()
            if joined and looks_like_page_label(joined):
                candidates.append(joined)
    seen: set[str] = set()
    deduped: list[str] = []
    for item in candidates:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def load_part_entries(output_dir: Path) -> list[dict[str, Any]]:
    return load_json(output_dir / "mineru_parts_progress.json", {"parts": []}).get("parts", [])


def build_visual_target_pages(output_dir: Path, smart_filter: bool = True) -> list[int]:
    target_pages: set[int] = set()
    skipped_pages = 0
    for part in load_part_entries(output_dir):
        part_id = str(part.get("part_id") or "")
        md_path = Path(str(part.get("md_path") or ""))
        page_start = int(part.get("page_start") or 1)
        if not part_id or not md_path.exists():
            continue
        content_list_path = md_path.parent / f"{part_id}_content_list.json"
        content_list = load_json(content_list_path, {})
        pdf_info = content_list.get("pdf_info") if isinstance(content_list, dict) else content_list
        if not isinstance(pdf_info, list):
            continue
        for page in pdf_info:
            if not isinstance(page, dict):
                continue
            page_idx = int(page.get("page_idx") or 0)
            actual_page = page_start + page_idx
            image_paths: list[str] = []
            collect_image_paths(page, image_paths)
            if not image_paths:
                continue

            if smart_filter:
                blocks = page.get("preproc_blocks", [])
                text_len = 0
                has_table = False
                has_equation = False
                if isinstance(blocks, list):
                    for block in blocks:
                        if not isinstance(block, dict):
                            continue
                        block_type = str(block.get("type") or "")
                        if block_type == "table":
                            has_table = True
                        elif block_type in {"interline_equation", "equation"}:
                            has_equation = True
                        for line in block.get("lines", []) or []:
                            if not isinstance(line, dict):
                                continue
                            for span in line.get("spans", []) or []:
                                if not isinstance(span, dict):
                                    continue
                                text_len += len(str(span.get("content", "")))

                if has_table or has_equation or text_len < 200:
                    target_pages.add(actual_page)
                else:
                    skipped_pages += 1
            else:
                target_pages.add(actual_page)

    if smart_filter and skipped_pages:
        print(
            f"Smart filter: {len(target_pages)} pages need vision, {skipped_pages} skipped (text sufficient)",
            flush=True,
        )
    return sorted(target_pages)


def build_page_metadata_map(output_dir: Path) -> dict[int, dict[str, Any]]:
    meta_map: dict[int, dict[str, Any]] = {}
    for part in load_part_entries(output_dir):
        part_id = str(part.get("part_id") or "")
        md_path = Path(str(part.get("md_path") or ""))
        page_start = int(part.get("page_start") or 1)
        if not part_id or not md_path.exists():
            continue
        content_list_path = md_path.parent / f"{part_id}_content_list.json"
        content_list = load_json(content_list_path, {})
        pdf_info = content_list.get("pdf_info") if isinstance(content_list, dict) else content_list
        if not isinstance(pdf_info, list):
            continue
        for page in pdf_info:
            if not isinstance(page, dict):
                continue
            page_idx = int(page.get("page_idx") or 0)
            actual_page = page_start + page_idx
            candidates = extract_page_label_candidates(page)
            meta_map[actual_page] = {
                "pdf_page_num": actual_page,
                "part_id": part_id,
                "part_page_idx": page_idx,
                "book_page_candidates": candidates,
                "book_page_label": candidates[0] if candidates else None,
            }
    return meta_map


def discover_content_lists(output_dir: Path) -> list[Path]:
    content_lists: list[Path] = []
    for part in load_part_entries(output_dir):
        part_id = str(part.get("part_id") or "")
        md_path = Path(str(part.get("md_path") or ""))
        if not part_id or not md_path.exists():
            continue
        content_list_path = md_path.parent / f"{part_id}_content_list.json"
        if content_list_path.exists():
            content_lists.append(content_list_path)
    return content_lists


def run_step2_vision(pdf_path: Path, output_dir: Path, api_config: dict[str, Any], dry_run: bool) -> Path:
    vision_path = output_dir / "raw_vision.json"
    target_pages = build_visual_target_pages(output_dir)
    if dry_run:
        save_json(
            vision_path,
            {"expected_pages": target_pages[-1] if target_pages else 0, "target_pages": target_pages, "pages": []},
        )
        return vision_path
    api_key = str(api_config.get("api_key") or os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if not api_key:
        raise PipelineError("DASHSCOPE_API_KEY is required for step2")
    model = str(api_config.get("model") or "qwen3-vl-plus")
    page_paths = render_pdf_pages(pdf_path, output_dir / "pages_150dpi", dpi=PNG_DPI)
    page_meta_map = build_page_metadata_map(output_dir)
    existing = load_json(vision_path, {"pages": []})
    page_results = {int(item["page_num"]): item for item in existing.get("pages", []) if "page_num" in item}

    def persist() -> None:
        save_json(
            vision_path,
            {
                "expected_pages": len(page_paths),
                "target_pages": target_pages,
                "updated_at": now_iso(),
                "pages": [page_results[idx] for idx in sorted(page_results)],
            },
        )

    if not target_pages:
        save_json(vision_path, {"expected_pages": len(page_paths), "target_pages": [], "updated_at": now_iso(), "pages": []})
        return vision_path

    for page_num in target_pages:
        png_path = page_paths[page_num - 1]
        page_meta = page_meta_map.get(page_num, {"pdf_page_num": page_num, "book_page_label": None, "book_page_candidates": []})
        if page_num in page_results and page_results[page_num].get("parsed") is not None:
            continue
        try:
            parsed = recognize_page(png_path, api_key, model)
            result = {"page_num": page_num, "image_path": str(png_path), "model": model, "parsed": parsed}
        except Exception as exc:
            result = {"page_num": page_num, "image_path": str(png_path), "error": str(exc)}
        result.update(page_meta)
        page_results[page_num] = result
        persist()
        time.sleep(0.3)
    persist()
    return vision_path


def extract_json_value(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    starts = [(stripped.find("{"), "{"), (stripped.find("["), "[")]
    starts = [(idx, token) for idx, token in starts if idx != -1]
    if not starts:
        raise ValueError("No JSON object or array found")
    start, token = min(starts, key=lambda item: item[0])
    end_token = "}" if token == "{" else "]"
    end = stripped.rfind(end_token)
    if end == -1 or end <= start:
        raise ValueError("No complete JSON payload found")
    return json.loads(stripped[start : end + 1])


def extract_json_object(text: str) -> dict[str, Any]:
    payload = extract_json_value(text)
    if not isinstance(payload, dict):
        raise ValueError("Expected JSON object")
    return payload


def normalize_heading_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    cleaned = re.sub(r"^:+", "", normalized.strip())
    for token in ["’", "'", '"', ".", "!", "?", ",", ":", ";", "(", ")", "/", "-"]:
        cleaned = cleaned.replace(token, " ")
    cleaned = cleaned.replace("A LA", "ALA")
    cleaned = re.sub(r"\s+\d+$", "", cleaned)
    cleaned = re.sub(r"\bSO US\b", "SOUS", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bIA\b", "LA", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().upper()
    return cleaned.replace(" ", "")


def find_heading_positions(lines: list[str]) -> list[tuple[int, str, str]]:
    positions: list[tuple[int, str, str]] = []
    for idx, line in enumerate(lines):
        if not line.startswith("#"):
            continue
        title = re.sub(r"^#+\s+", "", line).strip()
        if title:
            positions.append((idx, title, normalize_heading_key(title)))
    return positions


def looks_like_toc_noise(text: str, section_titles: list[str] | None = None) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    normalized_text = normalize_heading_key(stripped)
    if section_titles:
        section_hits = 0
        for section_title in section_titles:
            key = normalize_heading_key(str(section_title))
            if key and key in normalized_text:
                section_hits += 1
        if section_hits >= 3:
            return True
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    prose_lines = [line for line in lines if len(re.findall(r"\b\w+\b", line)) >= 18]
    prose_paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", stripped) if len(re.findall(r"\b\w+\b", paragraph)) >= 35]
    if prose_paragraphs:
        return False
    short_heading_lines = [line for line in lines if len(re.findall(r"\b\w+\b", line)) <= 12 and not any(ch in line for ch in ".!?")]
    uppercase_lines = [line for line in lines if line == line.upper()]
    return len(prose_lines) <= 1 and (
        len(short_heading_lines) >= max(4, len(lines) // 2) or len(uppercase_lines) >= max(3, len(lines) // 3)
    )


def prose_score(text: str) -> int:
    score = 0
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if len(re.findall(r"\b\w+\b", paragraph)) >= 35 and re.search(r"[.!?。！？]", paragraph):
            score += 1
    return score


def detect_mc_body_start_line(book: BookSpec, markdown_text: str) -> int:
    anchor_title = MC_BODY_START_HEADINGS.get(book.book_id)
    if not anchor_title:
        return 0
    lines = markdown_text.splitlines()
    first_hundred = "\n".join(lines[:100]).upper()
    if "VOLUME 1" not in first_hundred and "VOLUME 2" not in first_hundred:
        return 0
    anchor_key = normalize_heading_key(anchor_title)
    headings = find_heading_positions(lines)
    candidates = [(idx, raw_title) for idx, raw_title, key in headings if key == anchor_key]
    if not candidates:
        return 0
    chosen_idx = candidates[0][0]
    best_score = -1
    for idx, _raw_title in candidates:
        if idx < 150:
            continue
        sample = "\n".join(lines[idx : min(len(lines), idx + 80)]).strip()
        score = prose_score(sample)
        if score > best_score:
            chosen_idx = idx
            best_score = score
    return chosen_idx


def clean_merged_text_for_chunking(book: BookSpec, markdown_text: str) -> str:
    start_line = detect_mc_body_start_line(book, markdown_text)
    if start_line <= 0:
        return markdown_text
    lines = markdown_text.splitlines()
    cleaned = "\n".join(lines[start_line:]).strip()
    return cleaned or markdown_text


def build_toc_section_chapters(book: BookSpec, markdown_text: str, toc_config: dict[str, Any]) -> list[Chapter] | None:
    toc = toc_config.get(book.book_id)
    if not toc:
        return None
    lines = markdown_text.splitlines()
    headings = find_heading_positions(lines)
    chapters: list[Chapter] = []
    cursor = 0

    for chapter_index, chapter_cfg in enumerate(toc):
        chapter_title = str(chapter_cfg["chapter_title"])
        chapter_num = int(chapter_cfg["chapter_num"])
        chapter_key = normalize_heading_key(chapter_title)
        chapter_heading = next(((idx, raw_title) for idx, raw_title, key in headings if idx >= cursor and key == chapter_key), None)
        if not chapter_heading:
            continue
        chapter_start_idx, _ = chapter_heading
        next_chapter_start_idx = len(lines)
        if chapter_index + 1 < len(toc):
            next_chapter_key = normalize_heading_key(str(toc[chapter_index + 1]["chapter_title"]))
            next_heading = next(((idx, raw_title) for idx, raw_title, key in headings if idx > chapter_start_idx and key == next_chapter_key), None)
            if next_heading:
                next_chapter_start_idx = next_heading[0]

        section_positions: list[tuple[int, str]] = []
        search_cursor = chapter_start_idx
        for section_title in chapter_cfg["sections"]:
            section_key = normalize_heading_key(str(section_title))
            match = next(
                ((idx, raw_title) for idx, raw_title, key in headings if idx >= search_cursor and idx < next_chapter_start_idx and key == section_key),
                None,
            )
            if not match:
                continue
            section_positions.append(match)
            search_cursor = match[0] + 1

        if not section_positions:
            chapter_text = "\n".join(lines[chapter_start_idx:next_chapter_start_idx]).strip()
            if chapter_text:
                next_title = toc[chapter_index + 1]["chapter_title"] if chapter_index + 1 < len(toc) else "End of book"
                chapters.append(Chapter(chapter_num, chapter_title, chapter_title, str(next_title), chapter_text))
            cursor = next_chapter_start_idx
            continue

        intro_text = "\n".join(lines[chapter_start_idx:section_positions[0][0]]).strip()
        prepend_intro = intro_text if intro_text and not looks_like_toc_noise(intro_text, chapter_cfg["sections"]) else ""

        for section_idx, (section_start_idx, section_raw_title) in enumerate(section_positions):
            section_end_idx = section_positions[section_idx + 1][0] if section_idx + 1 < len(section_positions) else next_chapter_start_idx
            next_title = (
                section_positions[section_idx + 1][1]
                if section_idx + 1 < len(section_positions)
                else (toc[chapter_index + 1]["chapter_title"] if chapter_index + 1 < len(toc) else "End of book")
            )
            section_text = "\n".join(lines[section_start_idx:section_end_idx]).strip()
            if section_idx == 0 and prepend_intro:
                section_text = f"{prepend_intro}\n\n{section_text}".strip()
            if section_text:
                chapters.append(Chapter(chapter_num, chapter_title, section_raw_title, str(next_title), section_text))
        cursor = next_chapter_start_idx
    return chapters or None


def split_markdown_into_chapters(markdown_text: str) -> list[Chapter]:
    """无TOC配置时，按markdown heading自动切分章节。"""
    stripped = markdown_text.strip()
    if not stripped:
        return []

    lines = stripped.splitlines()
    headings = find_heading_positions(lines)

    if not headings:
        return [Chapter(1, "Full Text", "Start of book", "End of book", stripped)]

    min_level = 6
    for idx, _title, _key in headings:
        level = len(lines[idx]) - len(lines[idx].lstrip("#"))
        if level < min_level:
            min_level = level

    top_headings = []
    for idx, title, key in headings:
        level = len(lines[idx]) - len(lines[idx].lstrip("#"))
        if level <= min_level + 1:
            top_headings.append((idx, title, key))

    if not top_headings:
        return [Chapter(1, "Full Text", "Start of book", "End of book", stripped)]

    def clean_auto_title(title: str) -> str:
        cleaned = re.sub(r"\\[A-Za-z]+", " ", title)
        cleaned = re.sub(r"\$+", " ", cleaned)
        cleaned = re.sub(r"^[^A-Za-zÀ-ÿ\u4e00-\u9fff]+", "", cleaned)
        cleaned = re.sub(
            r"^(Rightarrow|therefore|because|scriptscriptstyle|mathfrak|textdegree|frac|mathrm|textcircled|subset|sim|star)+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"^[^A-Za-zÀ-ÿ\u4e00-\u9fff]+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -#,:;.!?+*/_=()[]{}\\'")
        return cleaned.strip()

    def is_auto_chapter_heading(title: str) -> bool:
        cleaned = clean_auto_title(title)
        if len(cleaned) < 6 or len(cleaned) > 80:
            return False
        alpha_words = re.findall(r"[A-Za-zÀ-ÿ]{3,}", cleaned)
        cjk_words = re.findall(r"[\u4e00-\u9fff]{2,}", cleaned)
        if len(alpha_words) + len(cjk_words) < 2:
            return False
        if re.search(r"\d{4,}", cleaned):
            return False
        normalized = re.sub(r"[^A-Z]", "", cleaned.upper())
        if normalized in {"POINT", "STEP", "STEPT", "SOFTSERVE", "GELATO", "SORBET", "GRANITE"}:
            return False
        return True

    filtered_headings: list[tuple[int, str]] = []
    last_heading_idx = -10_000
    min_heading_gap = 120
    for idx, title, _key in top_headings:
        cleaned_title = clean_auto_title(title)
        if not is_auto_chapter_heading(title):
            continue
        if idx - last_heading_idx < min_heading_gap:
            continue
        filtered_headings.append((idx, cleaned_title))
        last_heading_idx = idx

    if not filtered_headings:
        return [Chapter(1, "Full Text", "Start of book", "End of book", stripped)]

    chapters = []
    if filtered_headings[0][0] > 0:
        preamble = "\n".join(lines[: filtered_headings[0][0]]).strip()
        if preamble and len(preamble) > 200:
            chapters.append(Chapter(0, "Preamble", "Start of book", filtered_headings[0][1], preamble))

    for idx, (start_idx, title) in enumerate(filtered_headings):
        next_idx = filtered_headings[idx + 1][0] if idx + 1 < len(filtered_headings) else len(lines)
        next_title = filtered_headings[idx + 1][1] if idx + 1 < len(filtered_headings) else "End of book"
        text = "\n".join(lines[start_idx:next_idx]).strip()
        if text and len(text) > 200:
            chapters.append(Chapter(idx + 1, title, title, next_title, text))

    # 超大章节二次切分
    MAX_AUTO_CHAPTER_CHARS = 15000
    final = []
    for ch in (chapters or [Chapter(1, "Full Text", "Start of book", "End of book", stripped)]):
        if len(ch.text) <= MAX_AUTO_CHAPTER_CHARS:
            final.append(ch)
        else:
            subs = split_chapter_text_for_model(ch.text, max_chars=MAX_AUTO_CHAPTER_CHARS)
            for si, seg in enumerate(subs):
                if seg.strip() and len(seg.strip()) > 200:
                    final.append(Chapter(
                        ch.chapter_num,
                        f"{ch.chapter_title} (part {si+1})",
                        ch.chapter_start if si == 0 else f"{ch.chapter_title} part {si+1}",
                        ch.chapter_end if si == len(subs) - 1 else f"{ch.chapter_title} part {si+2}",
                        seg.strip(),
                    ))
    return final or [Chapter(1, "Full Text", "Start of book", "End of book", stripped)]


def sanitize_chunk_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    if cleaned.startswith("{") and cleaned.endswith("}"):
        for loader in (json.loads, ast.literal_eval):
            try:
                payload = loader(cleaned)
            except Exception:
                continue
            if isinstance(payload, dict):
                nested_text = payload.get("text")
                if isinstance(nested_text, str) and nested_text.strip():
                    cleaned = nested_text.strip()
                    break
    cleaned = cleaned.replace("\\n", "\n").strip()
    if len(re.findall(r"\b\w+\b", cleaned)) < 12 and not re.search(r"[.!?。！？]", cleaned):
        return ""
    return cleaned


def chunk_word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def chunk_cjk_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def chunk_size_ok(text: str, min_words: int = 120, max_words: int = 320, min_cjk: int = 180, max_cjk: int = 400) -> bool:
    words = chunk_word_count(text)
    cjk = chunk_cjk_count(text)
    if cjk > 0:
        return min_cjk <= cjk <= max_cjk
    return min_words <= words <= max_words


def split_large_block(text: str, max_chars: int) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", text)
    pieces: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        paragraph_len = len(paragraph) + 2
        if current and current_len + paragraph_len > max_chars:
            pieces.append("\n\n".join(current).strip())
            current = [paragraph]
            current_len = paragraph_len
        else:
            current.append(paragraph)
            current_len += paragraph_len
    if current:
        pieces.append("\n\n".join(current).strip())
    return pieces or [text.strip()]


def split_chapter_text_for_model(chapter_text: str, max_chars: int = 4500) -> list[str]:
    lines = chapter_text.splitlines()
    section_blocks: list[str] = []
    current_lines: list[str] = []
    for line in lines:
        if line.startswith("#") and current_lines:
            section_blocks.append("\n".join(current_lines).strip())
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        section_blocks.append("\n".join(current_lines).strip())
    segments: list[str] = []
    current_segment: list[str] = []
    current_len = 0
    for block in section_blocks:
        if not block:
            continue
        block_len = len(block) + 2
        if block_len > max_chars:
            if current_segment:
                segments.append("\n\n".join(current_segment).strip())
                current_segment = []
                current_len = 0
            segments.extend(split_large_block(block, max_chars=max_chars))
            continue
        if current_segment and current_len + block_len > max_chars:
            segments.append("\n\n".join(current_segment).strip())
            current_segment = [block]
            current_len = block_len
        else:
            current_segment.append(block)
            current_len += block_len
    if current_segment:
        segments.append("\n\n".join(current_segment).strip())
    return [segment for segment in segments if segment.strip()] or [chapter_text.strip()]


def extract_chunks_from_payload(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        chunks = payload.get("chunks")
        if isinstance(chunks, list):
            return [str(item).strip() for item in chunks if str(item).strip()]
        response = payload.get("response")
        if isinstance(response, str) and response.strip():
            return extract_chunks_from_payload(extract_json_value(response))
        return []
    if isinstance(payload, list):
        collected: list[str] = []
        for item in payload:
            if isinstance(item, str) and item.strip():
                collected.append(item.strip())
            else:
                collected.extend(extract_chunks_from_payload(item))
        return collected
    return []


def split_oversized_chunk(text: str, max_words: int = 260, max_cjk: int = 400) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if chunk_word_count(text) <= max_words and chunk_cjk_count(text) <= max_cjk:
        return [text]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", text) if part.strip()]
    pieces: list[str] = []
    current_text = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current_text else f"{current_text}\n\n{paragraph}"
        if current_text and (chunk_word_count(candidate) > max_words or chunk_cjk_count(candidate) > max_cjk):
            pieces.append(current_text.strip())
            current_text = paragraph
        else:
            current_text = candidate
    if current_text.strip():
        pieces.append(current_text.strip())
    return [piece for piece in pieces if piece.strip()]


def split_oversized(chunks: list[str], max_len: int = 1200) -> list[str]:
    result: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) <= max_len:
            result.append(chunk)
            continue
        sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", chunk) if part.strip()]
        if len(sentences) <= 1:
            sentences = [part.strip() for part in re.split(r"\n\s*\n", chunk) if part.strip()]
        if len(sentences) <= 1:
            sentences = [part.strip() for part in chunk.splitlines() if part.strip()]
        buf = ""
        for sentence in sentences:
            candidate = f"{buf} {sentence}".strip() if buf else sentence
            if len(candidate) > max_len and buf:
                result.append(buf.strip())
                buf = sentence
            else:
                buf = candidate
        if buf:
            result.append(buf.strip())
    return result


def rebalance_short_chunks(chunks: list[str], min_len: int = 180, max_len: int = 1200) -> list[str]:
    normalized = [chunk.strip() for chunk in chunks if chunk.strip()]
    merged: list[str] = []
    idx = 0
    while idx < len(normalized):
        current = normalized[idx]
        if idx + 1 < len(normalized) and len(current) < min_len:
            candidate = f"{current}\n\n{normalized[idx + 1]}".strip()
            if len(candidate) <= max_len:
                merged.append(candidate)
                idx += 2
                continue
        if merged and len(current) < min_len:
            candidate = f"{merged[-1]}\n\n{current}".strip()
            if len(candidate) <= max_len or len(current) < 120:
                merged[-1] = candidate
                idx += 1
                continue
        if len(current) < 50 and current.lstrip().startswith("#"):
            idx += 1
            continue
        merged.append(current)
        idx += 1
    return merged


def normalize_chunk_sizes(chunks: list[str]) -> list[str]:
    normalized: list[str] = []
    for chunk in chunks:
        cleaned = sanitize_chunk_text(chunk)
        if cleaned:
            normalized.extend(split_oversized_chunk(cleaned))
    merged: list[str] = []
    buffer = ""
    for chunk in normalized:
        candidate = f"{buffer}\n\n{chunk}".strip() if buffer else chunk
        if not buffer:
            buffer = chunk
            continue
        if chunk_size_ok(buffer):
            merged.append(buffer)
            buffer = chunk
            continue
        if chunk_word_count(candidate) <= 300 and chunk_cjk_count(candidate) <= 440:
            buffer = candidate
        else:
            merged.append(buffer)
            buffer = chunk
    if buffer:
        merged.append(buffer)
    return split_oversized(rebalance_short_chunks(merged, min_len=180, max_len=1200), max_len=1200)


def chapter_identity(chapter: Chapter) -> tuple[int, str, str, str]:
    return (chapter.chapter_num, chapter.chapter_title, chapter.chapter_start, chapter.chapter_end)


def split_segment_with_qwen(chapter: Chapter, segment_text: str, split_model: str, segment_label: str, dry_run: bool, max_depth: int = 2) -> list[str]:
    sanitized_segment = sanitize_chunk_text(segment_text)
    if not sanitized_segment:
        return []
    if len(sanitized_segment) < 180 and chunk_word_count(sanitized_segment) < 35:
        return [sanitized_segment]
    if dry_run:
        return normalize_chunk_sizes([sanitized_segment])
    last_error: Exception | None = None
    for _ in range(3):
        try:
            prompt = SPLIT_PROMPT_TEMPLATE.format(
                chapter_title=chapter.chapter_title,
                chapter_start=chapter.chapter_start,
                chapter_end=chapter.chapter_end,
                chapter_segment=segment_label,
                chapter_text=sanitized_segment,
            )
            raw = ollama_generate(split_model, prompt, timeout=600)
            parsed = extract_json_value(raw)
            chunks = extract_chunks_from_payload(parsed)
            if chunks:
                return [chunk for chunk in chunks if chunk.strip()]
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    if max_depth > 0 and len(sanitized_segment) > 1600:
        subsegments = split_chapter_text_for_model(sanitized_segment, max_chars=max(1600, len(sanitized_segment) // 2))
        if len(subsegments) > 1:
            collected: list[str] = []
            total_subsegments = len(subsegments)
            for idx, subsegment in enumerate(subsegments, start=1):
                sub_label = f"{segment_label} / retry {idx}/{total_subsegments}"
                collected.extend(split_segment_with_qwen(chapter, subsegment, split_model, sub_label, dry_run, max_depth - 1))
            if collected:
                return collected
    fallback_chunks = split_oversized_chunk(sanitized_segment, max_words=220, max_cjk=360)
    if fallback_chunks:
        return fallback_chunks
    if last_error is not None:
        raise last_error
    return [sanitized_segment]


def split_chapter_locally(chapter_text: str, max_chars: int = 4500) -> list[str]:
    chapter_segments = split_chapter_text_for_model(chapter_text, max_chars=max_chars)
    combined_chunks: list[str] = []
    for segment_text in chapter_segments:
        sanitized_segment = sanitize_chunk_text(segment_text)
        if not sanitized_segment:
            continue
        local_chunks = split_oversized_chunk(sanitized_segment, max_words=220, max_cjk=360)
        if local_chunks:
            combined_chunks.extend(local_chunks)
        else:
            combined_chunks.append(sanitized_segment)
    return normalize_chunk_sizes(combined_chunks)


MAX_CHAPTER_CHARS_FOR_MODEL = 12000  # 超过12000字的章节走本地切分，避免qwen 2b超时


def split_chapter_with_model(book: BookSpec, chapter: Chapter, split_model: str, dry_run: bool) -> list[str]:
    # 超大章节直接走本地规则切分，不调qwen
    if len(chapter.text) > MAX_CHAPTER_CHARS_FOR_MODEL:
        return normalize_chunk_sizes(
            split_chapter_text_for_model(chapter.text, max_chars=4500)
        )
    chapter_segments = split_chapter_text_for_model(chapter.text)
    if len(chapter_segments) >= 5:
        return split_chapter_locally(chapter.text)
    combined_chunks: list[str] = []
    total_segments = len(chapter_segments)
    for idx, chapter_segment_text in enumerate(chapter_segments, start=1):
        segment_label = f"part {idx}/{total_segments}" if total_segments > 1 else "full chapter"
        combined_chunks.extend(split_segment_with_qwen(chapter, chapter_segment_text, split_model, segment_label, dry_run))
    return normalize_chunk_sizes(combined_chunks)


def summarize_step4_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    lengths = [len(str(item.get("full_text", "") or "")) for item in chunks if str(item.get("full_text", "") or "").strip()]
    if not lengths:
        return {"total_chunks": 0, "avg_chars": 0, "min_chars": 0, "max_chars": 0, "lt50_chars": 0, "lt150_chars": 0}
    return {
        "total_chunks": len(lengths),
        "avg_chars": round(sum(lengths) / len(lengths), 2),
        "min_chars": min(lengths),
        "max_chars": max(lengths),
        "lt50_chars": sum(1 for value in lengths if value < 50),
        "lt150_chars": sum(1 for value in lengths if value < 150),
    }


def repair_short_step4_chunks(chunks: list[dict[str, Any]], min_chars: int = 150, max_chars: int = 1400) -> list[dict[str, Any]]:
    repaired = [dict(item) for item in chunks]
    idx = 0
    while idx < len(repaired):
        current = repaired[idx]
        text = str(current.get("full_text", "") or "").strip()
        if not text or len(text) >= min_chars:
            idx += 1
            continue
        prev_idx = idx - 1 if idx > 0 else None
        next_idx = idx + 1 if idx + 1 < len(repaired) else None
        merged = False

        def same_section(a: dict[str, Any], b: dict[str, Any]) -> bool:
            keys = ["chapter_num", "chapter_title", "chapter_start", "chapter_end", "source_book"]
            return all(a.get(key) == b.get(key) for key in keys)

        heading_like = len(text) <= 120 and "\n" not in text and not re.search(r"[.!?。！？:;]", text)

        if prev_idx is not None and same_section(repaired[prev_idx], current):
            candidate = f"{repaired[prev_idx]['full_text'].rstrip()}\n\n{text}".strip()
            if len(candidate) <= max_chars:
                repaired[prev_idx]["full_text"] = candidate
                repaired.pop(idx)
                merged = True
        if not merged and next_idx is not None and next_idx < len(repaired) and same_section(current, repaired[next_idx]):
            candidate = f"{text}\n\n{repaired[next_idx]['full_text'].lstrip()}".strip()
            if len(candidate) <= max_chars or (heading_like and len(candidate) <= 5000):
                repaired[next_idx]["full_text"] = candidate
                repaired.pop(idx)
                merged = True
        if not merged:
            idx += 1
    for new_idx, item in enumerate(repaired):
        item["chunk_idx"] = new_idx
    return repaired


def check_vision_coverage(output_dir: Path, warn_threshold: float = 0.95) -> None:
    """检查vision识别覆盖率，缺页>5%则警告并报错。"""
    vision_path = output_dir / "raw_vision.json"
    if not vision_path.exists():
        return  # 没有vision需求的书跳过

    data = load_json(vision_path, {"pages": [], "target_pages": []})
    target = set(data.get("target_pages", []))
    actual = set(
        p.get("page_num", p.get("pdf_page_num", 0))
        for p in data.get("pages", [])
    )

    if not target:
        return

    coverage = len(actual & target) / len(target)
    missing = sorted(target - actual)

    if coverage < warn_threshold:
        print(f"⚠️ Vision覆盖率 {coverage:.1%} 低于阈值 {warn_threshold:.0%}")
        print(f"   缺失页: {missing[:20]}{'...' if len(missing) > 20 else ''}")
        raise PipelineError(
            f"Vision覆盖率不足: {len(actual)}/{len(target)} ({coverage:.1%}). "
            f"请先补跑Step2再继续。缺失页: {missing[:10]}"
        )
    elif missing:
        print(f"  Vision覆盖率 {coverage:.1%}，缺失{len(missing)}页: {missing[:10]}")


def run_step4_chunk(
    book: BookSpec,
    output_dir: Path,
    toc_config: dict[str, Any],
    split_model: str,
    dry_run: bool,
    watchdog_minutes: int,
) -> tuple[Path, int]:
    merged_path = output_dir / "raw_merged.md"
    chunks_path = output_dir / "chunks_raw.json"
    failed_path = output_dir / "failed_sections.json"
    quality_path = output_dir / "step4_quality.json"
    if dry_run and not merged_path.exists():
        save_json(chunks_path, [])
        save_json(failed_path, [])
        save_json(quality_path, summarize_step4_chunks([]))
        return chunks_path, 0
    if not merged_path.exists():
        raise PipelineError(f"Missing input for step4: {merged_path}")

    label_ref = {"active": "initializing"}
    watchdog = FileGrowthWatchdog(chunks_path, watchdog_minutes, label_ref) if watchdog_minutes > 0 else None
    if watchdog is not None:
        watchdog.start()
    try:
        merged_text = merged_path.read_text(encoding="utf-8", errors="ignore")
        cleaned = clean_merged_text_for_chunking(book, merged_text)
        chapters = build_toc_section_chapters(book, cleaned, toc_config) or split_markdown_into_chapters(cleaned)
        existing_chunks = load_json_list(chunks_path)
        failed_sections: list[dict[str, Any]] = []
        done_keys = {
            (int(item["chapter_num"]), str(item["chapter_title"]), str(item["chapter_start"]), str(item["chapter_end"]))
            for item in existing_chunks
            if {"chapter_num", "chapter_title", "chapter_start", "chapter_end"} <= set(item)
        }
        next_chunk_idx = max((int(item.get("chunk_idx", -1)) for item in existing_chunks), default=-1) + 1
        for chapter in chapters:
            chapter_key = chapter_identity(chapter)
            if chapter_key in done_keys:
                continue
            label_ref["active"] = f"{chapter.chapter_title} | {chapter.chapter_start} -> {chapter.chapter_end}"
            try:
                for chunk_text in split_chapter_with_model(book, chapter, split_model, dry_run):
                    existing_chunks.append(
                        {
                            "chunk_idx": next_chunk_idx,
                            "full_text": chunk_text,
                            "chapter_num": chapter.chapter_num,
                            "chapter_title": chapter.chapter_title,
                            "chapter_start": chapter.chapter_start,
                            "chapter_end": chapter.chapter_end,
                            "source_book": book.book_id,
                        }
                    )
                    next_chunk_idx += 1
                save_json(chunks_path, existing_chunks)
                done_keys.add(chapter_key)
            except Exception as exc:
                failed_sections.append(
                    {
                        "chapter_num": chapter.chapter_num,
                        "chapter_title": chapter.chapter_title,
                        "chapter_start": chapter.chapter_start,
                        "chapter_end": chapter.chapter_end,
                        "error": str(exc),
                        "updated_at": now_iso(),
                    }
                )
                save_json(failed_path, failed_sections)
        existing_chunks = repair_short_step4_chunks(existing_chunks)
        save_json(chunks_path, existing_chunks)
        quality = summarize_step4_chunks(existing_chunks)
        quality["failed_chapters"] = len(failed_sections)
        save_json(failed_path, failed_sections)
        save_json(quality_path, quality)
    finally:
        if watchdog is not None:
            watchdog.stop()

    quality = load_json(quality_path, {})
    if not dry_run:
        if int(quality.get("total_chunks") or 0) <= 0:
            raise PipelineError("step4 produced 0 chunks")
        if int(quality.get("lt50_chars") or 0) > 0:
            raise PipelineError(f"step4 produced {quality['lt50_chars']} chunks shorter than 50 chars")
    return chunks_path, len(load_json_list(chunks_path))


def refine_annotation_topics(chunk_text: str, topics: list[str]) -> list[str]:
    text = chunk_text.lower()
    keyword_map = {
        "food_safety": ("pathogen", "bacteria", "spore", "toxin", "pasteur", "steril", "contamin", "safe", "safety"),
        "maillard_caramelization": ("maillard", "caramel", "browning"),
        "oxidation_reduction": ("oxid", "reduction"),
        "taste_perception": ("taste", "sensory", "mouthfeel"),
        "aroma_volatiles": ("aroma", "odor", "fragrance", "volatile"),
        "thermal_dynamics": ("heat", "thermal", "temperature", "convection", "conduction", "radiation", "steam"),
        "mass_transfer": ("moisture", "dehydrat", "drying", "diffusion", "migration"),
    }
    refined: list[str] = []
    for topic in topics:
        keywords = keyword_map.get(topic)
        if keywords and not any(keyword in text for keyword in keywords):
            continue
        if topic not in refined:
            refined.append(topic)
    return refined[:2] if refined else topics[:1]


def normalize_chunk_type(value: Any) -> str | None:
    chunk_type = str(value or "").strip().lower()
    return chunk_type if chunk_type in {"science", "recipe", "mixed", "narrative"} else None


def annotate_chunk(chunk: dict[str, Any], annotate_model: str, valid_topics: list[str], dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"summary": "dry-run 摘要", "topics": valid_topics[:1], "chunk_type": None}
    prompt = ANNOTATE_PROMPT_TEMPLATE.format(
        topics=", ".join(valid_topics),
        chapter_title=chunk.get("chapter_title", ""),
        chapter_start=chunk.get("chapter_start", ""),
        chapter_end=chunk.get("chapter_end", ""),
        chunk_text=chunk["full_text"],
    )
    raw = ollama_generate(annotate_model, prompt, timeout=240)
    parsed = extract_json_object(raw)
    summary = str(parsed.get("summary") or "").strip()
    topics = [str(item).strip() for item in parsed.get("topics") or [] if str(item).strip() in valid_topics]
    chunk_type = normalize_chunk_type(parsed.get("chunk_type"))
    if not summary:
        raise PipelineError("Missing summary in annotation response")
    if not topics:
        raise PipelineError("Missing valid topics in annotation response")
    return {
        "summary": summary[:50],
        "topics": refine_annotation_topics(chunk["full_text"], topics),
        "chunk_type": chunk_type,
    }


def run_step5_annotate(
    output_dir: Path,
    annotate_model: str,
    valid_topics: list[str],
    dry_run: bool,
    retry_failures_only: bool,
    watchdog_minutes: int,
) -> tuple[Path, int]:
    chunks_path = output_dir / "chunks_raw.json"
    prep_dir = ensure_dir(output_dir / "prep")
    out_path = prep_dir / "chunks_smart.json"
    failures_path = prep_dir / "annotation_failures.json"
    chunks = load_json_list(chunks_path)
    if dry_run and not chunks:
        save_json(out_path, [])
        save_json(failures_path, [])
        return out_path, 0
    if not chunks:
        raise PipelineError(f"Missing input chunks for step5: {chunks_path}")

    label_ref = {"active": "initializing"}
    watchdog = FileGrowthWatchdog(out_path, watchdog_minutes, label_ref) if watchdog_minutes > 0 else None
    if watchdog is not None:
        watchdog.start()
    try:
        annotated = load_json_list(out_path)
        failures = load_json_list(failures_path)
        annotated_by_id = {int(item["chunk_idx"]): item for item in annotated if "chunk_idx" in item}
        failure_ids = {int(item["chunk_idx"]) for item in failures if "chunk_idx" in item}
        target_ids = failure_ids if retry_failures_only else None
        new_failures: list[dict[str, Any]] = []

        for chunk in chunks:
            chunk_idx = int(chunk["chunk_idx"])
            if retry_failures_only and chunk_idx not in target_ids:
                continue
            if not retry_failures_only and chunk_idx in annotated_by_id:
                continue
            label_ref["active"] = f"chunk {chunk_idx} | {chunk.get('chapter_start', '')}"
            last_error: str | None = None
            for _ in range(3):
                try:
                    merged = dict(chunk)
                    merged.update(annotate_chunk(chunk, annotate_model, valid_topics, dry_run))
                    annotated_by_id[chunk_idx] = merged
                    last_error = None
                    break
                except Exception as exc:
                    last_error = str(exc)
                    time.sleep(1)
            if last_error is not None:
                new_failures.append(
                    {
                        "chunk_idx": chunk_idx,
                        "chapter_num": chunk.get("chapter_num"),
                        "chapter_title": chunk.get("chapter_title"),
                        "error": last_error,
                        "updated_at": now_iso(),
                    }
                )
            save_json(out_path, [annotated_by_id[idx] for idx in sorted(annotated_by_id)])
            save_json(failures_path, new_failures)
    finally:
        if watchdog is not None:
            watchdog.stop()

    annotated = load_json_list(out_path)
    failures = load_json_list(failures_path)
    if not dry_run:
        if len(annotated) == 0:
            raise PipelineError(f"step5 produced 0 annotations from {len(chunks)} chunks — Ollama可能未运行")
        if len(annotated) != len(chunks):
            print(f"[warn] step5: {len(annotated)}/{len(chunks)} annotated, {len(failures)} failures (继续)")
        if failures:
            print(f"[warn] step5: {len(failures)} annotation failures (不阻塞)")
    return out_path, len(annotated)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1 pipeline CLI")
    parser.add_argument("--book-id", required=True, help="Book id from config/books.yaml")
    parser.add_argument("--config", required=True, help="Path to config/api.yaml")
    parser.add_argument("--books", required=True, help="Path to config/books.yaml")
    parser.add_argument("--toc", required=True, help="Path to config/mc_toc.json")
    parser.add_argument("--output-dir", required=True, help="Book-specific output directory")
    parser.add_argument("--start-step", type=int, default=0, choices=range(0, 6), help="First step to run")
    parser.add_argument("--stop-step", type=int, default=5, choices=range(0, 6), help="Last step to run")
    parser.add_argument("--repair-state", action="store_true", help="Repair progress from output files before running")
    parser.add_argument("--retry-annotations", action="store_true", help="Retry only failed annotations from step5")
    parser.add_argument("--watchdog", type=int, default=0, help="Fail if chunk output file stops growing for N minutes")
    parser.add_argument("--dry-run", action="store_true", help="Validate pipeline without calling external APIs")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.start_step > args.stop_step:
        raise PipelineError("--start-step cannot be greater than --stop-step")

    config_path = Path(args.config).expanduser()
    books_path = Path(args.books).expanduser()
    toc_path = Path(args.toc).expanduser()
    output_dir = ensure_dir(Path(args.output_dir).expanduser())
    book = load_book(books_path, args.book_id)
    api_config = load_yaml(config_path)
    toc_config = load_json(toc_path, {})
    valid_topics = load_topics(config_path.parent / "domains_v2.json")

    configure_ollama(api_config.get("ollama"))
    inferred_status = infer_resume_status(book, output_dir)
    if args.repair_state or not (output_dir / "stage1_progress.json").exists():
        write_progress(output_dir, book, inferred_status)

    work_pdf = book.path if book.file_type == "pdf" else output_dir / f"{book.slug}.pdf"
    split_model = str(((api_config.get("ollama") or {}).get("models") or {}).get("split") or "qwen3.5:2b")
    annotate_model = str(((api_config.get("ollama") or {}).get("models") or {}).get("annotate") or "qwen3.5:9b")

    current_status = infer_resume_status(book, output_dir)
    if status_rank(current_status) < status_rank("step0_done") and args.start_step <= 0 <= args.stop_step:
        if not book.path.exists() and not args.dry_run:
            raise PipelineError(f"Input file not found: {book.path}")
        work_pdf = resolve_work_pdf(book, output_dir, args.dry_run)
        write_progress(output_dir, book, "step0_done")
    elif book.file_type == "epub":
        work_pdf = resolve_work_pdf(book, output_dir, args.dry_run)

    for step in range(max(1, args.start_step), min(5, args.stop_step) + 1):
        current_status = infer_resume_status(book, output_dir)
        if status_rank(current_status) >= status_rank(STEP_STATUS[step]) and not (step == 5 and args.retry_annotations):
            continue
        if step == 1:
            if args.dry_run:
                (output_dir / "raw_mineru.md").write_text("<!-- dry-run raw_mineru.md -->\n", encoding="utf-8")
                save_json(output_dir / "mineru_parts_progress.json", {"parts": []})
            else:
                upload_and_extract(work_pdf, output_dir, api_config.get("mineru") or {})
            write_progress(output_dir, book, "step1_done")
        elif step == 2:
            run_step2_vision(work_pdf, output_dir, api_config.get("dashscope") or {}, args.dry_run)
            write_progress(output_dir, book, "step2_done")
        elif step == 3:
            mineru_path = output_dir / "raw_mineru.md"
            vision_path = output_dir / "raw_vision.json"
            if args.dry_run and (not mineru_path.exists() or not vision_path.exists()):
                save_json(output_dir / "raw_merge_report.json", {"dry_run": True})
                (output_dir / "raw_merged.md").write_text("", encoding="utf-8")
            else:
                merged = merge_mineru_vision(mineru_path, vision_path, [str(path) for path in discover_content_lists(output_dir)])
                (output_dir / "raw_merged.md").write_text(merged, encoding="utf-8")
                save_json(output_dir / "raw_merge_report.json", {"merged_at": now_iso()})
            write_progress(output_dir, book, "step3_done")
        elif step == 4:
            # Step2.5: Vision覆盖率检查
            if not args.dry_run:
                check_vision_coverage(output_dir)
            # 强制TOC审核：没有TOC配置的书不允许进入切分
            if not toc_config.get(book.book_id) and not args.dry_run:
                raise PipelineError(
                    f"TOC配置缺失: config/mc_toc.json 中没有 '{book.book_id}' 的条目。\n"
                    f"必须先运行TOC检测 → 人工审阅 → 写入mc_toc.json后才能继续。\n"
                    f"auto-chapter-split已禁用（会把版权页/配方/作者介绍切进去）。"
                )
            _, total_chunks = run_step4_chunk(book, output_dir, toc_config, split_model, args.dry_run, args.watchdog)
            if total_chunks > 0 or args.dry_run:
                write_progress(output_dir, book, "step4_done")
        elif step == 5:
            _, total_annotated = run_step5_annotate(
                output_dir,
                annotate_model,
                valid_topics,
                args.dry_run,
                args.retry_annotations,
                args.watchdog,
            )
            if total_annotated > 0 or args.dry_run:
                write_progress(output_dir, book, "completed")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PipelineError, MineruError, VisionError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
