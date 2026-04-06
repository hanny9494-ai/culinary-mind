#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
import httpx
from bs4 import BeautifulSoup
from PIL import Image

try:
    from ebooklib import epub  # type: ignore
except Exception:
    epub = None


IMG_TAG_RE = re.compile(r"<img[^>]+>", re.I)
MAX_PAGES_PER_OCR_REQUEST = 100


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_manifest(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        books = data.get("books")
    else:
        books = data
    if not isinstance(books, list):
        raise SystemExit(f"Manifest format invalid: {path}")
    return books


def chunked(items: list[int], size: int) -> list[list[int]]:
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


def parse_page_spec(spec: str | None) -> set[int] | None:
    if not spec:
        return None
    pages: set[int] = set()
    for part in spec.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                start, end = end, start
            pages.update(range(start, end + 1))
        else:
            pages.add(int(item))
    return pages


def normalize_book_id(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return cleaned or "book"


def page_filename(page_num: int) -> str:
    return f"page_{page_num:04d}.txt"


def page_output_path(book_dir: Path, page_num: int) -> Path:
    return book_dir / page_filename(page_num)


def book_markdown_path(book_dir: Path) -> Path:
    return book_dir / "book.md"


def write_book_markdown(book_dir: Path, book_id: str) -> Path:
    page_files = sorted(book_dir.glob("page_*.txt"))
    sections: list[str] = [f"# {book_id}\n"]
    for page_file in page_files:
        page_label = page_file.stem.replace("page_", "")
        body = page_file.read_text(encoding="utf-8").strip()
        if not body:
            continue
        sections.append(f"## Page {page_label}\n\n{body}\n")
    out_path = book_markdown_path(book_dir)
    out_path.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    return out_path


def clean_markdown_text(text: str) -> str:
    text = IMG_TAG_RE.sub("", text or "")
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text("\n")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text_from_parsing_res_list(page: dict[str, Any]) -> str:
    pruned = page.get("prunedResult") or {}
    items = pruned.get("parsing_res_list") or []
    rows: list[tuple[int, str]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        content = str(item.get("block_content") or "").strip()
        if not content:
            continue
        order = int(item.get("block_order") or item.get("block_id") or idx)
        rows.append((order, content))
    rows.sort(key=lambda row: row[0])
    return "\n\n".join(content for _, content in rows).strip()


def extract_page_text(page: dict[str, Any]) -> str:
    markdown = page.get("markdown") or {}
    markdown_text = clean_markdown_text(str(markdown.get("text") or ""))
    if markdown_text:
        return markdown_text
    return extract_text_from_parsing_res_list(page)


def build_http_client() -> httpx.Client:
    timeout = httpx.Timeout(connect=30.0, read=1800.0, write=300.0, pool=30.0)
    return httpx.Client(timeout=timeout, trust_env=False)


def looks_like_quota_error(message: str) -> bool:
    lowered = message.lower()
    patterns = [
        "quota",
        "rate limit",
        "too many requests",
        "resource_exhausted",
        "exceeded",
        "余额不足",
        "配额",
        "限额",
        "频率限制",
        "429",
    ]
    return any(pattern in lowered for pattern in patterns)


def call_paddle_layout(file_path: Path, server_url: str, token: str, file_type: int) -> dict[str, Any]:
    payload = {
        "file": base64.b64encode(file_path.read_bytes()).decode("ascii"),
        "fileType": file_type,
        "useDocUnwarping": False,
        "useDocOrientationClassify": False,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"token {token}"}
    base_url = server_url.rstrip("/")
    url = base_url if base_url.endswith("/layout-parsing") else f"{base_url}/layout-parsing"
    with build_http_client() as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


def call_with_fallback(
    file_path: Path,
    file_type: int,
    primary_server_url: str,
    primary_token: str,
    primary_label: str,
    fallback_server_url: str | None,
    fallback_token: str | None,
    fallback_label: str | None,
) -> tuple[dict[str, Any], str]:
    try:
        return call_paddle_layout(file_path, primary_server_url, primary_token, file_type), primary_label
    except Exception as exc:
        if not fallback_server_url or not fallback_token or not fallback_label:
            raise
        if not looks_like_quota_error(str(exc)):
            raise
        print(f"[fallback] {primary_label} unavailable ({exc}); switch to {fallback_label}", flush=True)
        return call_paddle_layout(file_path, fallback_server_url, fallback_token, file_type), fallback_label


def get_pdf_page_count(pdf_path: Path) -> int:
    doc = fitz.open(str(pdf_path))
    try:
        return doc.page_count
    finally:
        doc.close()


def write_pdf_subset(source_pdf: Path, selected_pages: set[int], out_pdf: Path) -> list[int]:
    src = fitz.open(str(source_pdf))
    dst = fitz.open()
    ordered_pages = sorted(page for page in selected_pages if 1 <= page <= src.page_count)
    try:
        for page_num in ordered_pages:
            dst.insert_pdf(src, from_page=page_num - 1, to_page=page_num - 1)
        dst.save(str(out_pdf))
    finally:
        dst.close()
        src.close()
    return ordered_pages


def build_pdf_from_images(image_dir: Path, out_pdf: Path, selected_pages: set[int] | None) -> list[int]:
    candidates = [path for path in image_dir.iterdir() if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    page_webps = sorted(path for path in candidates if re.fullmatch(r"page_\d+\.(webp|png|jpg|jpeg)", path.name, re.I))
    image_paths = page_webps or sorted(candidates)
    if not image_paths:
        raise ValueError(f"No images found under {image_dir}")
    if selected_pages is not None:
        filtered: list[Path] = []
        for idx, image_path in enumerate(image_paths, start=1):
            if idx in selected_pages:
                filtered.append(image_path)
        image_paths = filtered
    ordered_pages = list(range(1, len(image_paths) + 1))
    pdf_images: list[Image.Image] = []
    try:
        for image_path in image_paths:
            with Image.open(image_path) as img:
                pdf_images.append(img.convert("RGB"))
        if not pdf_images:
            raise ValueError(f"No images available to build PDF from {image_dir}")
        first, rest = pdf_images[0], pdf_images[1:]
        first.save(out_pdf, "PDF", save_all=True, append_images=rest)
    finally:
        for img in pdf_images:
            img.close()
    return ordered_pages


def process_pdf_book(
    book: dict[str, Any],
    output_root: Path,
    primary_server_url: str,
    primary_token: str,
    primary_label: str,
    fallback_server_url: str | None,
    fallback_token: str | None,
    fallback_label: str | None,
    selected_pages: set[int] | None,
    dry_run: bool,
) -> None:
    book_id = normalize_book_id(str(book["book_id"]))
    pdf_path = Path(str(book["path"])).expanduser()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    book_dir = ensure_dir(output_root / book_id)
    manifest_record = {
        "book_id": book_id,
        "source_type": "pdf",
        "source_path": str(pdf_path),
    }

    with tempfile.TemporaryDirectory(prefix=f"{book_id}_ocr_") as tmp_dir:
        if selected_pages:
            page_map = sorted(selected_pages)
        else:
            page_map = list(range(1, get_pdf_page_count(pdf_path) + 1))

        manifest_record["pages_requested"] = page_map
        if dry_run:
            print(f"[dry-run] pdf {book_id}: {pdf_path} -> {book_dir}")
            (book_dir / "manifest.json").write_text(json.dumps(manifest_record, ensure_ascii=False, indent=2), encoding="utf-8")
            return

        pages_written = sum(1 for page_num in page_map if page_output_path(book_dir, page_num).exists())
        model_used_overall = primary_label
        page_chunks = chunked(page_map, MAX_PAGES_PER_OCR_REQUEST)
        for chunk_index, page_chunk in enumerate(page_chunks, start=1):
            if all(page_output_path(book_dir, page_num).exists() for page_num in page_chunk):
                print(
                    f"[skip] pdf {book_id} chunk {chunk_index}/{len(page_chunks)} pages {page_chunk[0]}-{page_chunk[-1]}",
                    flush=True,
                )
                continue
            request_pdf = pdf_path
            if selected_pages or len(page_map) > MAX_PAGES_PER_OCR_REQUEST:
                subset_pdf = Path(tmp_dir) / f"{book_id}_chunk_{chunk_index:03d}.pdf"
                request_pdf_pages = set(page_chunk)
                write_pdf_subset(pdf_path, request_pdf_pages, subset_pdf)
                request_pdf = subset_pdf

            print(
                f"[ocr] pdf {book_id} chunk {chunk_index}/{len(page_chunks)} pages {page_chunk[0]}-{page_chunk[-1]}",
                flush=True,
            )
            response, model_used = call_with_fallback(
                request_pdf,
                file_type=0,
                primary_server_url=primary_server_url,
                primary_token=primary_token,
                primary_label=primary_label,
                fallback_server_url=fallback_server_url,
                fallback_token=fallback_token,
                fallback_label=fallback_label,
            )
            result = response.get("result", response)
            pages = result.get("layoutParsingResults") or []
            if len(pages) != len(page_chunk):
                raise ValueError(f"Unexpected page count for {book_id}: requested {len(page_chunk)}, got {len(pages)}")

            for idx, page in enumerate(pages):
                actual_page = page_chunk[idx]
                out_path = page_output_path(book_dir, actual_page)
                out_path.write_text(extract_page_text(page) + "\n", encoding="utf-8")
            model_used_overall = model_used

        pages_written = sum(1 for page_num in page_map if page_output_path(book_dir, page_num).exists())

        manifest_record["pages_written"] = pages_written
        manifest_record["model_used"] = model_used_overall
        manifest_record["book_markdown_path"] = str(write_book_markdown(book_dir, book_id))
        (book_dir / "manifest.json").write_text(json.dumps(manifest_record, ensure_ascii=False, indent=2), encoding="utf-8")


def process_image_book(
    book: dict[str, Any],
    output_root: Path,
    primary_server_url: str,
    primary_token: str,
    primary_label: str,
    fallback_server_url: str | None,
    fallback_token: str | None,
    fallback_label: str | None,
    selected_pages: set[int] | None,
    dry_run: bool,
) -> None:
    book_id = normalize_book_id(str(book["book_id"]))
    image_dir = Path(str(book["path"])).expanduser()
    if not image_dir.exists():
        raise FileNotFoundError(f"Image directory not found: {image_dir}")

    book_dir = ensure_dir(output_root / book_id)
    manifest_record = {
        "book_id": book_id,
        "source_type": "images",
        "source_path": str(image_dir),
    }

    if dry_run:
        print(f"[dry-run] images {book_id}: {image_dir} -> {book_dir}")
        (book_dir / "manifest.json").write_text(json.dumps(manifest_record, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    with tempfile.TemporaryDirectory(prefix=f"{book_id}_imgocr_") as tmp_dir:
        temp_pdf = Path(tmp_dir) / f"{book_id}.pdf"
        page_map = build_pdf_from_images(image_dir, temp_pdf, selected_pages)
        manifest_record["pages_requested"] = page_map

        pages_written = sum(1 for page_num in page_map if page_output_path(book_dir, page_num).exists())
        model_used_overall = primary_label
        page_chunks = chunked(page_map, MAX_PAGES_PER_OCR_REQUEST)
        for chunk_index, page_chunk in enumerate(page_chunks, start=1):
            if all(page_output_path(book_dir, page_num).exists() for page_num in page_chunk):
                print(
                    f"[skip] images {book_id} chunk {chunk_index}/{len(page_chunks)} pages {page_chunk[0]}-{page_chunk[-1]}",
                    flush=True,
                )
                continue
            chunk_selected = set(page_chunk)
            chunk_pdf = Path(tmp_dir) / f"{book_id}_chunk_{chunk_index:03d}.pdf"
            build_pdf_from_images(image_dir, chunk_pdf, chunk_selected)
            print(
                f"[ocr] images {book_id} chunk {chunk_index}/{len(page_chunks)} pages {page_chunk[0]}-{page_chunk[-1]}",
                flush=True,
            )
            response, model_used = call_with_fallback(
                chunk_pdf,
                file_type=0,
                primary_server_url=primary_server_url,
                primary_token=primary_token,
                primary_label=primary_label,
                fallback_server_url=fallback_server_url,
                fallback_token=fallback_token,
                fallback_label=fallback_label,
            )
            result = response.get("result", response)
            pages = result.get("layoutParsingResults") or []
            if len(pages) != len(page_chunk):
                raise ValueError(f"Unexpected page count for {book_id}: requested {len(page_chunk)}, got {len(pages)}")

            for idx, page in enumerate(pages):
                actual_page = page_chunk[idx]
                out_path = page_output_path(book_dir, actual_page)
                out_path.write_text(extract_page_text(page) + "\n", encoding="utf-8")
            model_used_overall = model_used

        pages_written = sum(1 for page_num in page_map if page_output_path(book_dir, page_num).exists())

        manifest_record["pages_written"] = pages_written
        manifest_record["model_used"] = model_used_overall
        manifest_record["book_markdown_path"] = str(write_book_markdown(book_dir, book_id))
        (book_dir / "manifest.json").write_text(json.dumps(manifest_record, ensure_ascii=False, indent=2), encoding="utf-8")


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_epub_items_with_ebooklib(epub_path: Path) -> list[str]:
    assert epub is not None
    book = epub.read_epub(str(epub_path))
    texts: list[str] = []
    for item in book.get_items_of_type(9):  # ITEM_DOCUMENT
        content = item.get_content()
        if isinstance(content, bytes):
            html = content.decode("utf-8", errors="replace")
        else:
            html = str(content)
        text = html_to_text(html)
        if text:
            texts.append(text)
    return texts


def extract_epub_items_with_zip(epub_path: Path) -> list[str]:
    texts: list[str] = []
    with zipfile.ZipFile(epub_path) as zf:
        html_names = sorted(
            name for name in zf.namelist() if name.lower().endswith((".html", ".xhtml", ".htm")) and not name.startswith("__MACOSX/")
        )
        for name in html_names:
            html = zf.read(name).decode("utf-8", errors="replace")
            text = html_to_text(html)
            if text:
                texts.append(text)
    return texts


def process_epub_book(book: dict[str, Any], output_root: Path, dry_run: bool) -> None:
    book_id = normalize_book_id(str(book["book_id"]))
    epub_path = Path(str(book["path"])).expanduser()
    if not epub_path.exists():
        raise SystemExit(f"EPUB not found: {epub_path}")

    book_dir = ensure_dir(output_root / book_id)
    manifest_record = {
        "book_id": book_id,
        "source_type": "epub",
        "source_path": str(epub_path),
    }

    if dry_run:
        print(f"[dry-run] epub {book_id}: {epub_path} -> {book_dir}")
        (book_dir / "manifest.json").write_text(json.dumps(manifest_record, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    if epub is not None:
        texts = extract_epub_items_with_ebooklib(epub_path)
        manifest_record["extractor"] = "ebooklib"
    else:
        texts = extract_epub_items_with_zip(epub_path)
        manifest_record["extractor"] = "zipfile_fallback"

    for idx, text in enumerate(texts, start=1):
        (book_dir / page_filename(idx)).write_text(text + "\n", encoding="utf-8")

    manifest_record["pages_written"] = len(texts)
    manifest_record["book_markdown_path"] = str(write_book_markdown(book_dir, book_id))
    (book_dir / "manifest.json").write_text(json.dumps(manifest_record, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class SummaryRow:
    book_id: str
    source_type: str
    status: str
    detail: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch OCR/extract L2a reference books into page txt files plus one combined book.md per book")
    parser.add_argument("--manifest", required=True, help="JSON manifest with books[]")
    parser.add_argument("--output-root", default="~/culinary-mind/output/l2a/ocr_output")
    parser.add_argument("--server-url", default=os.environ.get("PADDLE_SERVER_URL", ""))
    parser.add_argument("--token", default=os.environ.get("PADDLE_API_TOKEN", ""))
    parser.add_argument("--primary-server-url", default=os.environ.get("PADDLE_VL15_SERVER_URL", ""))
    parser.add_argument("--primary-token", default=os.environ.get("PADDLE_VL15_API_TOKEN", ""))
    parser.add_argument("--fallback-server-url", default=os.environ.get("PADDLE_PPSTRUCTURE_SERVER_URL", ""))
    parser.add_argument("--fallback-token", default=os.environ.get("PADDLE_PPSTRUCTURE_API_TOKEN", ""))
    parser.add_argument("--primary-label", default="PaddleOCR-VL-1.5")
    parser.add_argument("--fallback-label", default="PP-StructureV3")
    parser.add_argument("--sample-pages", default=None, help="Page spec like 1-3 or 1,5,9")
    parser.add_argument("--books", default=None, help="Comma-separated book_ids to run")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).expanduser()
    output_root = ensure_dir(Path(args.output_root).expanduser())
    selected_pages = parse_page_spec(args.sample_pages)
    selected_books = {normalize_book_id(item) for item in args.books.split(",")} if args.books else None
    primary_server_url = args.primary_server_url or args.server_url
    primary_token = args.primary_token or args.token
    fallback_server_url = args.fallback_server_url or None
    fallback_token = args.fallback_token or args.token or None

    books = load_manifest(manifest_path)
    summary: list[SummaryRow] = []
    for book in books:
        book_id = normalize_book_id(str(book.get("book_id") or ""))
        if selected_books and book_id not in selected_books:
            continue

        source_type = str(book.get("source_type") or "").lower().strip()
        try:
            if source_type in {"pdf"}:
                if not args.dry_run and (not primary_server_url or not primary_token):
                    raise SystemExit("PDF/image OCR requires --server-url and --token (or env PADDLE_SERVER_URL/PADDLE_API_TOKEN)")
                process_pdf_book(
                    book,
                    output_root,
                    primary_server_url,
                    primary_token,
                    args.primary_label,
                    fallback_server_url,
                    fallback_token,
                    args.fallback_label if fallback_server_url and fallback_token else None,
                    selected_pages,
                    args.dry_run,
                )
            elif source_type in {"images", "image_dir", "webp_dir"}:
                if not args.dry_run and (not primary_server_url or not primary_token):
                    raise SystemExit("PDF/image OCR requires --server-url and --token (or env PADDLE_SERVER_URL/PADDLE_API_TOKEN)")
                process_image_book(
                    book,
                    output_root,
                    primary_server_url,
                    primary_token,
                    args.primary_label,
                    fallback_server_url,
                    fallback_token,
                    args.fallback_label if fallback_server_url and fallback_token else None,
                    selected_pages,
                    args.dry_run,
                )
            elif source_type == "epub":
                process_epub_book(book, output_root, args.dry_run)
            else:
                raise SystemExit(f"Unsupported source_type for {book_id}: {source_type}")
            summary.append(SummaryRow(book_id, source_type, "ok", "done"))
        except Exception as exc:
            summary.append(SummaryRow(book_id, source_type or "unknown", "error", str(exc)))

    print("\nSummary:")
    for row in summary:
        print(f"- {row.book_id} [{row.source_type}] {row.status}: {row.detail}")
    return 0 if all(row.status == "ok" for row in summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
