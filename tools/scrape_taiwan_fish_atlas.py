#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.fa.gov.tw/book/fishlibrary/files/assets/basic-html"
THUMB_BASE_URL = "https://www.fa.gov.tw/book/fishlibrary/files/assets/flash/pages"
DEFAULT_DELAY = 0.0
MAX_RETRIES = 5


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    return session


def fetch_html(session: requests.Session, label: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(f"{BASE_URL}/page-{label}.html", timeout=60)
            response.raise_for_status()
            return response.text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(min(2.0, 0.25 * attempt))
    raise RuntimeError(f"Failed to fetch HTML for page {label}") from last_error


def extract_page_text(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for node in soup.select("#pageContainer p.textItem"):
        text = node.get_text(" ", strip=True)
        if text:
            items.append(text)

    background = None
    bg = soup.select_one("#pageContainer img")
    if bg and bg.get("src"):
        background = bg["src"]

    page_label = None
    pager = soup.select_one("#pageLabel")
    if pager:
        page_label = pager.get_text(" ", strip=True)

    return {
        "page_label": page_label,
        "background_src": background,
        "text_items": items,
        "text": "\n".join(items),
    }


def fetch_thumb(session: requests.Session, physical_index: int) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(f"{THUMB_BASE_URL}/page{physical_index:04d}_s.jpg", timeout=60)
            response.raise_for_status()
            return response.content
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(min(2.0, 0.25 * attempt))
    raise RuntimeError(f"Failed to fetch thumbnail for physical page {physical_index}") from last_error


def iter_page_labels(last_numeric_page: int) -> list[str]:
    labels = ["I", "II"]
    labels.extend(str(i) for i in range(1, last_numeric_page + 1))
    return labels


def process_page(
    output_dir: Path,
    label: str,
    physical_index: int,
    include_images: bool,
) -> dict[str, Any]:
    session = build_session()
    raw_html_dir = ensure_dir(output_dir / "raw_html")
    images_dir = ensure_dir(output_dir / "images")
    html_path = raw_html_dir / f"page-{label}.html"
    image_path = images_dir / f"page{physical_index:04d}_s.jpg"

    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
    else:
        html = fetch_html(session, label)
        html_path.write_text(html, encoding="utf-8")

    parsed = extract_page_text(html)

    if include_images and not image_path.exists():
        image_bytes = fetch_thumb(session, physical_index)
        image_path.write_bytes(image_bytes)

    return {"label": label, "physical_index": physical_index, **parsed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape Taiwan fish atlas basic HTML pages and accessible page thumbnails")
    parser.add_argument("--output-dir", default="~/culinary-engine/data/external/taiwan_fish_atlas")
    parser.add_argument("--last-page", type=int, default=502)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--max-pages", type=int, default=None, help="Limit pages for testing")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    output_dir = ensure_dir(Path(args.output_dir).expanduser())
    raw_html_dir = ensure_dir(output_dir / "raw_html")
    images_dir = ensure_dir(output_dir / "images")
    _ = raw_html_dir, images_dir

    labels = iter_page_labels(args.last_page)
    if args.max_pages is not None:
        labels = labels[: args.max_pages]

    pages: list[dict[str, Any] | None] = [None] * len(labels)
    failures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(process_page, output_dir, label, physical_index, not args.skip_images): (idx, label, physical_index)
            for idx, (physical_index, label) in enumerate(enumerate(labels, start=1))
        }
        for completed_count, future in enumerate(as_completed(futures), start=1):
            idx, label, physical_index = futures[future]
            try:
                record = future.result()
                pages[idx] = record
                print(
                    f"[page] {completed_count}/{len(labels)} label={label} physical={physical_index} text_items={len(record['text_items'])}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {"label": label, "physical_index": physical_index, "error": f"{type(exc).__name__}: {exc}"}
                )
                print(f"[error] label={label} physical={physical_index} {exc}", flush=True)
            if args.delay:
                time.sleep(args.delay)

    final_pages = [page for page in pages if page is not None]

    write_json(output_dir / "pages.json", final_pages)
    with (output_dir / "pages.jsonl").open("w", encoding="utf-8") as fh:
        for page in final_pages:
            fh.write(json.dumps(page, ensure_ascii=False) + "\n")

    write_json(
        output_dir / "manifest.json",
        {
            "source": "https://www.fa.gov.tw/book/fishlibrary/",
            "strategy": "basic-html pages + accessible flash thumbnail images",
            "page_count": len(final_pages),
            "last_numeric_page": args.last_page,
            "includes_images": not args.skip_images,
            "workers": args.workers,
            "failure_count": len(failures),
        },
    )
    write_json(output_dir / "failures.json", failures)
    print(f"Done. pages={len(final_pages)} failures={len(failures)} output={output_dir}", flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
