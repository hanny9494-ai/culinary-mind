#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import fitz
import requests


PROMPT = """Extract the full text from this book page into clean Markdown.

Rules:
- Preserve all readable text.
- Use Markdown headings for obvious headings.
- Preserve lists and tables as Markdown when visible.
- Do not summarize or translate.
- If a page is blank or only decorative, return an HTML comment like <!-- blank page -->.
- Ignore watermarks or scanner artifacts when they are clearly not part of the book.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DashScope VLM OCR with resume support")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--pages-json", required=True)
    parser.add_argument("--merged-md", required=True)
    parser.add_argument("--model", default="qwen-vl-max")
    parser.add_argument("--api-url", default="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--sleep", type=float, default=0.3)
    parser.add_argument("--max-retries", type=int, default=6)
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_pages(path: Path) -> dict[int, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    pages = data.get("pages") if isinstance(data, dict) else data
    if not isinstance(pages, list):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for item in pages:
        try:
            page_number = int(item["page_number"])
        except Exception:
            continue
        out[page_number] = item
    return out


def save_pages(path: Path, pdf: Path, model: str, pages: dict[int, dict[str, Any]], started_at: str) -> None:
    ensure_dir(path)
    ordered = [pages[idx] for idx in sorted(pages)]
    usage = {
        "prompt_tokens": sum(int((item.get("usage") or {}).get("prompt_tokens") or 0) for item in ordered),
        "completion_tokens": sum(int((item.get("usage") or {}).get("completion_tokens") or 0) for item in ordered),
        "total_tokens": sum(int((item.get("usage") or {}).get("total_tokens") or 0) for item in ordered),
    }
    payload = {
        "source_pdf": str(pdf),
        "model": model,
        "started_at": started_at,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "page_count": len(ordered),
        "usage": usage,
        "pages": ordered,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def render_page_png(pdf_path: Path, page_index: int, dpi: int) -> bytes:
    doc = fitz.open(str(pdf_path))
    try:
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def call_vlm(session: requests.Session, api_url: str, api_key: str, model: str, image_bytes: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                ],
            }
        ],
        "temperature": 0,
    }
    response = session.post(
        api_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=300,
    )
    response.raise_for_status()
    return response.json()


def build_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def extract_markdown(payload: dict[str, Any]) -> tuple[str, dict[str, int]]:
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("missing choices in response")
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    text = ""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        text = "\n".join(part for part in parts if part.strip())
    text = text.strip()
    if not text:
        raise RuntimeError("empty OCR content")
    usage = payload.get("usage") or {}
    usage_out = {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }
    return text, usage_out


def heading_catalog(pdf_path: Path) -> dict[str, str]:
    doc = fitz.open(str(pdf_path))
    pattern = re.compile(r"^[A-Z][A-Z '&/\\-]+[A-Z]$")
    ignored = {"BY THE SAME AUTHOR", "CONTENTS", "BLOOMSBURY PUBLISHING"}
    found: dict[str, str] = {}
    try:
        for page_index in range(doc.page_count):
            text = doc.load_page(page_index).get_text("text")
            for raw in text.splitlines():
                line = " ".join(raw.strip().split())
                if not line or ":" in line:
                    continue
                if len(line) < 3 or len(line) > 45:
                    continue
                if "OCEANOFPDF" in line:
                    continue
                if not pattern.match(line):
                    continue
                if line in ignored:
                    continue
                found.setdefault(normalize(line), line)
    finally:
        doc.close()
    return found


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def normalize_markdown(page_markdown: str, headings: dict[str, str]) -> str:
    out: list[str] = []
    for raw in page_markdown.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        if "OceanofPDF" in stripped:
            continue
        key = normalize(stripped.rstrip(":"))
        if key in headings and not stripped.startswith("#"):
            out.append(f"# {headings[key]}")
            continue
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def write_merged(path: Path, ordered_pages: list[dict[str, Any]], headings: dict[str, str]) -> None:
    ensure_dir(path)
    parts: list[str] = []
    for item in ordered_pages:
        page_number = int(item["page_number"])
        markdown = normalize_markdown(str(item.get("markdown") or ""), headings)
        parts.append(f"<!-- page {page_number} -->\n{markdown}".strip())
    merged = "\n\n".join(part for part in parts if part.strip()) + "\n"
    path.write_text(merged, encoding="utf-8")


def main() -> int:
    args = parse_args()
    pdf_path = Path(args.pdf).expanduser()
    pages_json = Path(args.pages_json).expanduser()
    merged_md = Path(args.merged_md).expanduser()
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY is not set")
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    os.environ["no_proxy"] = "localhost,127.0.0.1"
    os.environ["http_proxy"] = ""
    os.environ["https_proxy"] = ""

    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    existing = load_pages(pages_json)
    headings = heading_catalog(pdf_path)

    doc = fitz.open(str(pdf_path))
    try:
        total_pages = doc.page_count
    finally:
        doc.close()

    pending = [
        page_number
        for page_number in range(1, total_pages + 1)
        if not (existing.get(page_number) and str(existing[page_number].get("markdown") or "").strip())
    ]
    lock = threading.Lock()

    def worker(page_number: int) -> tuple[int, dict[str, Any]]:
        image_bytes = render_page_png(pdf_path, page_number - 1, args.dpi)
        session = build_session()
        last_error: str | None = None
        try:
            for attempt in range(1, args.max_retries + 1):
                try:
                    payload = call_vlm(session, args.api_url, api_key, args.model, image_bytes)
                    markdown, usage = extract_markdown(payload)
                    return page_number, {
                        "page_number": page_number,
                        "markdown": markdown,
                        "usage": usage,
                        "model": args.model,
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    print(f"[retry] page {page_number} attempt {attempt}/{args.max_retries}: {last_error}", flush=True)
                    time.sleep(min(20, attempt * 2))
            raise RuntimeError(last_error or f"page {page_number} failed")
        finally:
            session.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {executor.submit(worker, page_number): page_number for page_number in pending}
        for future in concurrent.futures.as_completed(future_map):
            page_number = future_map[future]
            page_number, page_data = future.result()
            with lock:
                existing[page_number] = page_data
                save_pages(pages_json, pdf_path, args.model, existing, started_at)
                write_merged(merged_md, [existing[idx] for idx in sorted(existing)], headings)
            print(f"[ok] page {page_number}/{total_pages}", flush=True)
            time.sleep(args.sleep)

    ordered = [existing[idx] for idx in sorted(existing)]
    save_pages(pages_json, pdf_path, args.model, existing, started_at)
    write_merged(merged_md, ordered, headings)
    print(f"[done] pages={len(ordered)} merged={merged_md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
