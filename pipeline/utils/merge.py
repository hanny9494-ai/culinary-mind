from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PLACEHOLDER_RE = re.compile(r"!\[.*?\]\(([^)]+)\)")
PAGE_IMAGE_RE = re.compile(r"(?:^|/)p(\d+)_img\d+\.(?:png|jpg|jpeg)$", re.IGNORECASE)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _iter_pdf_pages(content_list: Any):
    if isinstance(content_list, dict):
        pdf_info = content_list.get("pdf_info") or []
    elif isinstance(content_list, list):
        pdf_info = content_list
    else:
        pdf_info = []
    for page in pdf_info:
        if isinstance(page, dict):
            yield page


def _collect_image_paths(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"image_path", "img_path"} and isinstance(value, str):
                out.append(Path(value).name)
            else:
                _collect_image_paths(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_image_paths(item, out)


def _discover_content_lists(paths: list[str | Path]) -> list[Path]:
    discovered: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            discovered.extend(sorted(path.rglob("*_content_list.json")))
        elif path.exists():
            discovered.append(path)
    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in discovered:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return deduped


def _load_part_offsets(content_list_paths: list[Path]) -> dict[str, int]:
    offsets: dict[str, int] = {}
    for path in content_list_paths:
        part_id = path.stem.removesuffix("_content_list")
        progress_path = path.parents[2] / "mineru_parts_progress.json"
        progress = _load_json(progress_path, {"parts": []})
        for part in progress.get("parts", []):
            if str(part.get("part_id") or "") != part_id:
                continue
            offsets[part_id] = int(part.get("page_start") or 1)
            break
    return offsets


def _build_image_page_map(content_list_paths: list[Path]) -> dict[str, int]:
    part_offsets = _load_part_offsets(content_list_paths)
    image_page_map: dict[str, int] = {}
    for path in content_list_paths:
        part_id = path.stem.removesuffix("_content_list")
        page_start = part_offsets.get(part_id, 1)
        content_list = _load_json(path, {})
        for page in _iter_pdf_pages(content_list):
            page_num = int(page.get("page_num") or 0)
            if page_num <= 0:
                page_num = page_start + int(page.get("page_idx") or 0)
            image_paths: list[str] = []
            _collect_image_paths(page, image_paths)
            for image_name in image_paths:
                image_page_map.setdefault(Path(image_name).name, page_num)
    return image_page_map


def _format_table_item(table: dict[str, Any], page_num: int, book_page_label: str | None) -> str | None:
    markdown = str((table or {}).get("markdown") or "").strip()
    if not markdown:
        return None
    title = str((table or {}).get("title") or "").strip()
    notes = str((table or {}).get("notes") or "").strip()
    suffix = f"pdf-page {page_num}"
    if book_page_label:
        suffix += f", book-page {book_page_label}"
    header = f"<!-- qwen-vl {suffix} table"
    if title:
        header += f": {title}"
    header += " -->"
    block = f"{header}\n{markdown}"
    if notes:
        block += f"\n\n> Note: {notes}"
    return block


def _format_figure_item(figure: dict[str, Any], page_num: int, book_page_label: str | None) -> str | None:
    description = str((figure or {}).get("description") or "").strip()
    if not description:
        return None
    figure_type = str((figure or {}).get("type") or "figure").strip() or "figure"
    suffix = f"pdf-page {page_num}"
    if book_page_label:
        suffix += f", book-page {book_page_label}"
    return f"> [{figure_type} {suffix}] {description}"


def _format_text_block_item(content: str, page_num: int, book_page_label: str | None) -> str | None:
    text = str(content or "").strip()
    if not text:
        return None
    suffix = f"pdf-page {page_num}"
    if book_page_label:
        suffix += f", book-page {book_page_label}"
    return f"> [text_block {suffix}] {text}"


def _build_page_items(entry: dict[str, Any]) -> list[str]:
    if entry.get("error"):
        return []
    parsed = entry.get("parsed") or {}
    page_num = int(entry.get("pdf_page_num") or entry.get("page_num") or 0)
    book_page_label = entry.get("book_page_label")
    items: list[str] = []
    for table in parsed.get("tables") or []:
        item = _format_table_item(table, page_num, book_page_label)
        if item:
            items.append(item)
    for figure in parsed.get("figures") or []:
        item = _format_figure_item(figure, page_num, book_page_label)
        if item:
            items.append(item)
    for text_block in parsed.get("text_blocks") or []:
        item = _format_text_block_item(str(text_block), page_num, book_page_label)
        if item:
            items.append(item)
    return items


def _summarize_page_items(items: list[str]) -> str:
    snippets: list[str] = []
    for item in items:
        text = re.sub(r"<!--.*?-->", "", item, flags=re.DOTALL)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            snippets.append(text)
        if len(snippets) >= 3:
            break
    summary = " ".join(snippets).strip()
    return summary[:357].rstrip() + "..." if len(summary) > 360 else summary


def _build_summary_fallback(page_num: int, occurrence: int, items: list[str], book_page_label: str | None) -> str:
    suffix = f"pdf-page {page_num}"
    if book_page_label:
        suffix += f", book-page {book_page_label}"
    summary = _summarize_page_items(items)
    if summary:
        return (
            f"> [第{occurrence}个图片/表格，来自同页内容汇总，{suffix}] "
            f"同页视觉内容已超过逐项分配数量，请参考本页已提取内容。摘要：{summary}"
        )
    return f"> [第{occurrence}个图片/表格，来自同页内容汇总，{suffix}] 同页已有视觉内容，但当前摘要为空。"


def _build_warning_fallback(page_num: int | None, reason: str | None, book_page_label: str | None) -> str:
    if page_num is None:
        page_label = "页码未知"
    else:
        page_label = f"页码{page_num}"
        if book_page_label:
            page_label += f" / 书页{book_page_label}"
    reason_label = {
        "qwen_error": "qwen识别失败",
        "no_qwen_page": "qwen结果缺失",
        "no_visual_items": "该页未提取到可分配视觉内容",
        "no_page_mapping": "MinerU页码映射缺失",
    }.get(reason or "", "内容待补充")
    return f"> [图片/表格，{page_label}，内容待补充] {reason_label}。"


def _build_vision_page_map(vision_path: Path) -> dict[int, dict[str, Any]]:
    data = _load_json(vision_path, {"pages": []})
    page_map: dict[int, dict[str, Any]] = {}
    for entry in data.get("pages", []):
        if not isinstance(entry, dict):
            continue
        page_num = int(entry.get("pdf_page_num") or entry.get("page_num") or 0)
        if page_num > 0:
            page_map[page_num] = entry
    return page_map


def merge_mineru_vision(
    mineru_md: str | Path,
    vision_json: str | Path,
    content_lists: list[str | Path],
) -> str:
    mineru_path = Path(mineru_md)
    vision_path = Path(vision_json)
    mineru_text = mineru_path.read_text(encoding="utf-8", errors="ignore")
    content_list_paths = _discover_content_lists(content_lists)
    image_page_map = _build_image_page_map(content_list_paths)
    vision_page_map = _build_vision_page_map(vision_path)
    page_item_cache = {page_num: _build_page_items(entry) for page_num, entry in vision_page_map.items()}
    page_consumed = {page_num: 0 for page_num in vision_page_map}

    report = {
        "total_placeholders": 0,
        "direct_replacements": 0,
        "page_exhaustion_fallbacks": 0,
        "warning_fallbacks": 0,
    }

    def replacer(match: re.Match[str]) -> str:
        image_name = Path(match.group(1)).name
        report["total_placeholders"] += 1
        page_num = image_page_map.get(image_name)
        if page_num is None:
            report["warning_fallbacks"] += 1
            return _build_warning_fallback(None, "no_page_mapping", None)
        entry = vision_page_map.get(page_num)
        book_page_label = entry.get("book_page_label") if entry else None
        if not entry:
            report["warning_fallbacks"] += 1
            return _build_warning_fallback(page_num, "no_qwen_page", book_page_label)
        if entry.get("error"):
            report["warning_fallbacks"] += 1
            return _build_warning_fallback(page_num, "qwen_error", book_page_label)
        items = page_item_cache.get(page_num) or []
        if not items:
            report["warning_fallbacks"] += 1
            return _build_warning_fallback(page_num, "no_visual_items", book_page_label)
        consume_idx = page_consumed.get(page_num, 0)
        if consume_idx < len(items):
            page_consumed[page_num] = consume_idx + 1
            report["direct_replacements"] += 1
            return items[consume_idx]
        report["page_exhaustion_fallbacks"] += 1
        return _build_summary_fallback(page_num, consume_idx + 1, items, book_page_label)

    merged = PLACEHOLDER_RE.sub(replacer, mineru_text)

    trailing_blocks: list[str] = []
    for page_num, items in sorted(page_item_cache.items()):
        consumed = page_consumed.get(page_num, 0)
        for item in items[consumed:]:
            trailing_blocks.append(item)
    if trailing_blocks:
        merged = f"{merged.rstrip()}\n\n<!-- unassigned vision leftovers -->\n\n" + "\n\n".join(trailing_blocks)

    return merged.strip() + "\n"
