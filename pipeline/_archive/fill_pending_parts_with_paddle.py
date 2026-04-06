#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from typing import Any

import fitz
import httpx


IMG_TAG_RE = re.compile(r'<img[^>]+src="([^"]+)"[^>]*>')


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


def get_pdf_page_count(pdf_path: Path) -> int:
    doc = fitz.open(str(pdf_path))
    try:
        return doc.page_count
    finally:
        doc.close()


def split_pdf(pdf_path: Path, dest_dir: Path, chunk_size: int) -> list[tuple[Path, int, int]]:
    ensure_dir(dest_dir)
    total_pages = get_pdf_page_count(pdf_path)
    parts: list[tuple[Path, int, int]] = []
    for start_page in range(1, total_pages + 1, chunk_size):
        end_page = min(start_page + chunk_size - 1, total_pages)
        suffix = f"{start_page:04d}_{end_page:04d}"
        out_path = dest_dir / f"{pdf_path.stem}_{suffix}.pdf"
        src = fitz.open(str(pdf_path))
        dst = fitz.open()
        try:
            dst.insert_pdf(src, from_page=start_page - 1, to_page=end_page - 1)
            dst.save(str(out_path))
        finally:
            dst.close()
            src.close()
        parts.append((out_path, start_page, end_page))
    return parts


def normalize_block_type(label: str) -> str:
    lowered = label.strip().lower()
    mapping = {
        "doc_title": "title",
        "title": "title",
        "section_header": "title",
        "text": "text",
        "paragraph": "text",
        "list": "text",
        "formula": "equation",
        "interline_equation": "interline_equation",
        "equation": "equation",
        "table": "table",
        "figure": "image",
        "image": "image",
        "chart": "image",
    }
    return mapping.get(lowered, lowered or "text")


def build_text_block(block: dict[str, Any]) -> dict[str, Any]:
    content = str(block.get("block_content") or "").strip()
    bbox = block.get("block_bbox") or [0, 0, 0, 0]
    return {
        "type": normalize_block_type(str(block.get("block_label") or "")),
        "bbox": bbox,
        "lines": [
            {
                "bbox": bbox,
                "spans": [{"bbox": bbox, "score": 1.0, "content": content, "type": "text"}],
                "index": 0,
            }
        ]
        if content
        else [],
        "index": block.get("block_order") or block.get("block_id") or 0,
    }


def decode_image_bytes(value: str) -> bytes:
    if value.startswith("http://") or value.startswith("https://"):
        with httpx.Client(timeout=httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)) as client:
            response = client.get(value)
            response.raise_for_status()
            return response.content
    if value.startswith("data:"):
        value = value.split(",", 1)[1]
    return base64.b64decode(value)


def save_markdown_images(markdown_text: str, images: dict[str, str], image_dir: Path) -> tuple[str, list[str]]:
    ensure_dir(image_dir)
    saved_paths: list[str] = []
    replacements: dict[str, str] = {}
    for idx, (img_key, img_data) in enumerate(images.items(), start=1):
        out_name = f"paddle_{idx:04d}.jpg"
        out_path = image_dir / out_name
        out_path.write_bytes(decode_image_bytes(img_data))
        replacements[img_key] = f"images/{out_name}"
        saved_paths.append(f"images/{out_name}")

    def replacer(match: re.Match[str]) -> str:
        source = match.group(1)
        local_path = replacements.get(source, source)
        return f"![]({local_path})"

    normalized = IMG_TAG_RE.sub(replacer, markdown_text)
    return normalized, saved_paths


def call_paddle_layout(pdf_path: Path, server_url: str, token: str) -> dict[str, Any]:
    payload = {
        "file": base64.b64encode(pdf_path.read_bytes()).decode("ascii"),
        "fileType": 0,
        "useDocUnwarping": False,
        "useDocOrientationClassify": False,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"token {token}"}
    url = f"{server_url.rstrip('/')}/layout-parsing"
    timeout = httpx.Timeout(connect=30.0, read=1800.0, write=30.0, pool=30.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


def convert_result_to_outputs(
    response: dict[str, Any],
    part_dir: Path,
    part_id: str,
    page_start: int,
) -> tuple[Path, Path]:
    result = response.get("result", response)
    pages = result.get("layoutParsingResults") or []
    markdown_parts: list[str] = []
    pdf_info: list[dict[str, Any]] = []
    image_counter = 0

    for page_idx, page in enumerate(pages):
        markdown = page.get("markdown") or {}
        markdown_text = str(markdown.get("text") or "")
        images = markdown.get("images") or {}

        page_image_dir = ensure_dir(part_dir / "images")
        if images:
            remapped_images: dict[str, str] = {}
            for img_key, img_data in images.items():
                image_counter += 1
                out_name = f"p{page_idx + 1:04d}_img{image_counter:03d}.jpg"
                out_path = page_image_dir / out_name
                out_path.write_bytes(decode_image_bytes(img_data))
                remapped_images[img_key] = f"images/{out_name}"
            markdown_text = IMG_TAG_RE.sub(
                lambda match: f"![]({remapped_images.get(match.group(1), match.group(1))})",
                markdown_text,
            )
        markdown_parts.append(markdown_text.strip())

        pruned = page.get("prunedResult") or {}
        width = int(pruned.get("width") or 0)
        height = int(pruned.get("height") or 0)
        blocks = [build_text_block(item) for item in pruned.get("parsing_res_list") or [] if isinstance(item, dict)]
        image_refs = sorted(set(IMG_TAG_RE.findall(markdown_text)))
        for image_ref in image_refs:
            blocks.append({"type": "image", "image_path": image_ref})

        pdf_info.append(
            {
                "page_idx": page_idx,
                "page_size": [width, height],
                "preproc_blocks": blocks,
                "discarded_blocks": [],
                "para_blocks": blocks,
            }
        )

    md_path = part_dir / f"{part_id}.md"
    md_path.write_text(("\n\n".join(item for item in markdown_parts if item)).strip() + "\n", encoding="utf-8")
    content_list_path = part_dir / f"{part_id}_content_list.json"
    save_json(content_list_path, {"pdf_info": pdf_info, "_backend": "paddleocr-vl", "_version_name": "v1.5"})
    return md_path, content_list_path


def combine_markdown(output_dir: Path, entries: list[dict[str, Any]]) -> None:
    blocks: list[str] = []
    for idx, entry in enumerate(sorted(entries, key=lambda item: int(item.get("page_start") or 0)), start=1):
        md_path = Path(str(entry.get("md_path") or ""))
        if not md_path.exists():
            continue
        text = md_path.read_text(encoding="utf-8", errors="ignore").strip()
        if text:
            blocks.append(f"<!-- mineru part {idx}: {md_path.name} -->\n{text}")
    (output_dir / "raw_mineru.md").write_text(("\n\n".join(blocks)).strip() + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fill pending Stage1 OCR parts using PaddleOCR-VL service")
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--max-pages-per-file", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser()
    parts_dir = output_dir / "mineru_parts"
    progress_path = output_dir / "mineru_parts_progress.json"
    progress = load_json(progress_path, {"parts": []})
    entries = list(progress.get("parts") or [])
    existing_ids = {str(item.get("part_id") or "") for item in entries}

    part_pdfs = sorted(parts_dir.glob(f"{args.book_id}_part*.pdf"))
    if not part_pdfs:
        raise SystemExit(f"No part PDFs found under {parts_dir}")

    for pdf_path in part_pdfs:
        part_match = re.search(r"_part(\d+)\.pdf$", pdf_path.name)
        if not part_match:
            continue
        base_index = int(part_match.group(1))
        base_part_id = f"part{base_index}"
        base_entry = next((item for item in entries if str(item.get("part_id") or "") == base_part_id), None)
        if base_entry and Path(str(base_entry.get("md_path") or "")).exists():
            continue

        done_same_prefix = [item for item in entries if str(item.get("part_id") or "").startswith(f"{base_part_id}_")]
        if done_same_prefix:
            continue

        if base_entry:
            page_start = int(base_entry.get("page_start") or 1)
        else:
            previous = [item for item in entries if int(item.get("page_start") or 0) > 0]
            previous_max = max((int(item.get("page_end") or 0) for item in previous), default=0)
            page_start = previous_max + 1

        subparts = split_pdf(pdf_path, parts_dir / f"{base_part_id}_paddle_tmp", args.max_pages_per_file)
        current_start = page_start
        for sub_idx, (sub_pdf, sub_start_local, sub_end_local) in enumerate(subparts, start=1):
            page_count = sub_end_local - sub_start_local + 1
            current_end = current_start + page_count - 1
            part_id = base_part_id if len(subparts) == 1 else f"{base_part_id}_{sub_idx}"
            if part_id in existing_ids:
                current_start = current_end + 1
                continue
            print(f"[paddle] {args.book_id} {part_id} pages {current_start}-{current_end}", flush=True)
            response = call_paddle_layout(sub_pdf, args.server_url, args.token)
            part_dir = ensure_dir(parts_dir / part_id)
            md_path, _content_list_path = convert_result_to_outputs(response, part_dir, part_id, current_start)
            entries.append(
                {
                    "part_id": part_id,
                    "path": str(sub_pdf),
                    "page_start": current_start,
                    "page_end": current_end,
                    "pages": page_count,
                    "status": "done",
                    "md_path": str(md_path),
                    "updated_at": "",
                }
            )
            existing_ids.add(part_id)
            current_start = current_end + 1

    entries = sorted(entries, key=lambda item: int(item.get("page_start") or 0))
    save_json(progress_path, {"parts": entries})
    combine_markdown(output_dir, entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
