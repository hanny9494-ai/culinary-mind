#!/usr/bin/env python3
"""paddleocr_api.py — PaddleOCR-VL 1.5 layout-parsing via AI Studio online API (free).

Usage:
  python3 pipeline/prep/paddleocr_api.py \\
      --pdf /path/to/book.pdf \\
      --output-dir output/toledo_kinetics/prep \\
      [--split-pages 80]   # pages per chunk (API cap ~100)
      [--retries 5]        # retries per chunk
      [--timeout 600]      # seconds per request

Outputs:
  {output_dir}/merged.md          — full merged markdown text
  {output_dir}/doc_{N:04d}.md     — per-page markdown
  {output_dir}/images/            — inline images from markdown.images
  {output_dir}/outputImages/      — layout visualization images
  {output_dir}/_ocr_progress.json — checkpoint (completed chunk indices)

Resume behaviour:
  - If merged.md already exists → skip entirely (already done).
  - Else if _ocr_progress.json lists some chunks completed → skip them,
    continue with the remaining chunks, then rebuild merged.md from
    the persisted doc_*.md files at the end.

API:
  https://t1m0ybsdk3d2hcyc.aistudio-app.com/layout-parsing
  Token: 6c85d029b67e3ea07bd94338dc0f27ce8c54318f
  fileType: 0=PDF, 1=image
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

import requests

API_URL = "https://t1m0ybsdk3d2hcyc.aistudio-app.com/layout-parsing"
TOKEN = "6c85d029b67e3ea07bd94338dc0f27ce8c54318f"

# ── Conservative defaults for the AI Studio free tier ────────────────────────
# Empirical notes (2026-04-20): the free endpoint doesn't tolerate
# concurrent callers, so throttling is enforced upstream (orchestrator
# uses --ocr-concurrency=1 by default). Here we keep the request
# envelope generous: exponential backoff on retry + long timeout.
DEFAULT_SPLIT_PAGES = 80
DEFAULT_TIMEOUT     = 600
# Exponential-ish backoff; len(RETRY_BACKOFF) sets the default retry count.
RETRY_BACKOFF       = [5, 10, 20, 40, 60]
DEFAULT_RETRIES     = len(RETRY_BACKOFF)


def _log(msg: str) -> None:
    """Unbuffered print so progress is visible under `tee` / background jobs."""
    print(msg, flush=True)


# ── API call ──────────────────────────────────────────────────────────────────

def send_pdf(
    pdf_bytes: bytes,
    chunk_label: str = "",
    retries: int = DEFAULT_RETRIES,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[dict]:
    """Send one PDF chunk. Returns layoutParsingResults list.

    Retries with exponential backoff on any non-200 / network error.
    Logs HTTP status, response body (first 500 chars) and elapsed time
    so failures are debuggable.
    """
    size_mb = len(pdf_bytes) / 1024 / 1024
    file_data = base64.b64encode(pdf_bytes).decode("ascii")
    headers = {
        "Authorization": f"token {TOKEN}",
        "Content-Type":  "application/json",
    }
    payload = {
        "file":                      file_data,
        "fileType":                  0,
        "useDocOrientationClassify": False,
        "useDocUnwarping":           False,
        "useChartRecognition":       False,
    }
    label = f"{chunk_label} " if chunk_label else ""
    last_err: str = ""

    for attempt in range(1, retries + 1):
        t0 = time.time()
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=timeout)
            elapsed = time.time() - t0
            if resp.status_code == 200:
                return resp.json()["result"]["layoutParsingResults"]
            body = (resp.text or "")[:500]
            last_err = (
                f"HTTP {resp.status_code} (size={size_mb:.2f} MB, "
                f"elapsed={elapsed:.1f}s) body={body!r}"
            )
            _log(f"  [warn] {label}attempt {attempt}/{retries} failed: {last_err}")
        except requests.exceptions.Timeout as e:
            elapsed = time.time() - t0
            last_err = f"timeout after {elapsed:.1f}s (size={size_mb:.2f} MB): {e}"
            _log(f"  [warn] {label}attempt {attempt}/{retries} timeout: {last_err}")
        except Exception as e:   # noqa: BLE001
            elapsed = time.time() - t0
            last_err = f"request error after {elapsed:.1f}s: {e}"
            _log(f"  [warn] {label}attempt {attempt}/{retries} error: {last_err}")

        # Retry?
        if attempt < retries:
            delay = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
            _log(f"  [retry] {label}backing off {delay}s before attempt {attempt + 1}/{retries}")
            time.sleep(delay)

    raise RuntimeError(
        f"{label}API failed after {retries} attempts (chunk {size_mb:.2f} MB). "
        f"Last error: {last_err}"
    )


# ── PDF splitting ─────────────────────────────────────────────────────────────

def split_pdf(pdf_path: Path, pages_per_chunk: int) -> list[bytes]:
    """Split PDF into chunks of N pages, return list of PDF bytes."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise SystemExit("ERROR: pypdfium2 not installed. Run: pip install pypdfium2")

    doc = pdfium.PdfDocument(str(pdf_path))
    total = len(doc)
    chunks: list[bytes] = []
    for start in range(0, total, pages_per_chunk):
        end = min(start + pages_per_chunk, total)
        new_doc = pdfium.PdfDocument.new()
        new_doc.import_pages(doc, list(range(start, end)))
        import io as _io
        _buf = _io.BytesIO()
        new_doc.save(_buf)
        buf = _buf.getvalue()
        chunks.append(buf)
        _log(f"  [split] chunk pages {start + 1}-{end} ({len(buf) / 1024 / 1024:.2f} MB)")
    doc.close()
    return chunks


# ── Image saving (unchanged schema) ──────────────────────────────────────────

def save_images(res: dict, images_dir: Path, output_images_dir: Path,
                chunk_idx: int, page_idx: int) -> int:
    """Save images from a single page result. Returns count of images saved."""
    saved = 0

    md_images = res.get("markdown", {}).get("images", {})
    if md_images:
        images_dir.mkdir(parents=True, exist_ok=True)
        for img_name, img_b64 in md_images.items():
            try:
                img_bytes = base64.b64decode(img_b64)
                stem = Path(img_name).stem
                suffix = Path(img_name).suffix or ".png"
                fname = f"c{chunk_idx:02d}_p{page_idx:03d}_{stem}{suffix}"
                (images_dir / fname).write_bytes(img_bytes)
                saved += 1
            except Exception as e:   # noqa: BLE001
                _log(f"    [warn] Failed to save markdown image {img_name}: {e}")

    out_images = res.get("outputImages", {})
    if out_images:
        output_images_dir.mkdir(parents=True, exist_ok=True)
        for img_name, img_b64 in out_images.items():
            try:
                img_bytes = base64.b64decode(img_b64)
                stem = Path(img_name).stem
                suffix = Path(img_name).suffix or ".png"
                fname = f"c{chunk_idx:02d}_p{page_idx:03d}_{stem}{suffix}"
                (output_images_dir / fname).write_bytes(img_bytes)
                saved += 1
            except Exception as e:   # noqa: BLE001
                _log(f"    [warn] Failed to save output image {img_name}: {e}")

    return saved


# ── Checkpoint ───────────────────────────────────────────────────────────────

def _load_progress(progress_path: Path) -> dict:
    if not progress_path.exists():
        return {"completed_chunks": [], "page_counter": 0}
    try:
        data = json.loads(progress_path.read_text())
        if not isinstance(data, dict):
            return {"completed_chunks": [], "page_counter": 0}
        data.setdefault("completed_chunks", [])
        data.setdefault("page_counter", 0)
        return data
    except Exception:
        return {"completed_chunks": [], "page_counter": 0}


def _save_progress(progress_path: Path, progress: dict) -> None:
    tmp = progress_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(progress, indent=2))
    tmp.replace(progress_path)


def _rebuild_merged_md(output_dir: Path) -> tuple[int, int]:
    """Concatenate doc_*.md into merged.md. Returns (pages, total_chars)."""
    parts: list[str] = []
    docs = sorted(output_dir.glob("doc_*.md"))
    for mdp in docs:
        try:
            page_num = int(mdp.stem.split("_", 1)[1])
        except Exception:
            continue
        try:
            text = mdp.read_text(encoding="utf-8")
        except Exception:
            text = ""
        if text:
            parts.append(f"\n<!-- page {page_num} -->\n{text}")
    content = "\n".join(parts)
    (output_dir / "merged.md").write_text(content, encoding="utf-8")
    return len(docs), len(content)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="PaddleOCR-VL 1.5 layout-parsing via AI Studio API")
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--split-pages", type=int, default=DEFAULT_SPLIT_PAGES,
                        help=f"Pages per chunk (default {DEFAULT_SPLIT_PAGES}; "
                             f"AI Studio API cap is ~100)")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES,
                        help=f"Max retries per chunk (default {DEFAULT_RETRIES}; "
                             f"backoff schedule: {RETRY_BACKOFF})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"HTTP timeout seconds per request (default {DEFAULT_TIMEOUT})")
    args = parser.parse_args()

    pdf_path   = Path(args.pdf)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    merged_md         = output_dir / "merged.md"
    images_dir        = output_dir / "images"
    output_images_dir = output_dir / "outputImages"
    progress_path     = output_dir / "_ocr_progress.json"

    if not pdf_path.exists():
        raise SystemExit(f"ERROR: PDF not found: {pdf_path}")

    # Idempotence: if merged.md already exists, treat as fully done.
    if merged_md.exists():
        _log(f"[ocr] merged.md already exists — skipping (delete to re-run)")
        return

    pdf_size_mb = pdf_path.stat().st_size / 1024 / 1024
    _log(f"[ocr] PDF: {pdf_path.name} ({pdf_size_mb:.1f} MB)")
    _log(f"[ocr] Config: split-pages={args.split_pages} "
         f"retries={args.retries} timeout={args.timeout}s")

    # Always split — API return size cap is ~100 pages per request.
    _log(f"[ocr] Splitting into {args.split_pages}-page chunks")
    chunks = split_pdf(pdf_path, args.split_pages)
    n_chunks = len(chunks)

    # Resume from prior checkpoint if any.
    progress = _load_progress(progress_path)
    completed_set: set[int] = set(progress.get("completed_chunks", []))
    page_counter = int(progress.get("page_counter", 0))
    if completed_set:
        _log(f"[resume] loaded progress: {len(completed_set)}/{n_chunks} chunks done, "
             f"page_counter={page_counter}")

    total_images = 0

    for i, chunk_bytes in enumerate(chunks):
        if i in completed_set:
            _log(f"[skip] chunk {i + 1}/{n_chunks} already done (resume)")
            continue

        chunk_mb = len(chunk_bytes) / 1024 / 1024
        chunk_label = f"chunk {i + 1}/{n_chunks}"
        _log(f"[ocr] Sending {chunk_label} ({chunk_mb:.2f} MB)...")
        t0 = time.time()
        try:
            results = send_pdf(
                chunk_bytes,
                chunk_label=chunk_label,
                retries=args.retries,
                timeout=args.timeout,
            )
        except RuntimeError as e:
            _log(f"[fail] {chunk_label}: {e}")
            _log(f"[info] progress saved at {progress_path}; re-run to resume unfinished chunks.")
            raise SystemExit(1)
        elapsed = time.time() - t0
        pages_in_chunk = len(results)
        start_page = page_counter + 1

        for j, res in enumerate(results):
            page_counter += 1
            md_text = res.get("markdown", {}).get("text", "")
            page_md_path = output_dir / f"doc_{page_counter:04d}.md"
            page_md_path.write_text(md_text or "", encoding="utf-8")

            n_saved = save_images(res, images_dir, output_images_dir, i + 1, j + 1)
            if n_saved > 0:
                total_images += n_saved

        end_page = page_counter
        completed_set.add(i)
        progress["completed_chunks"] = sorted(completed_set)
        progress["page_counter"] = page_counter
        _save_progress(progress_path, progress)

        _log(f"[done] {chunk_label} pages {start_page}-{end_page} "
             f"({pages_in_chunk} pages) in {elapsed:.1f}s "
             f"→ {len(completed_set)}/{n_chunks} chunks")

    # Rebuild merged.md from the persistent per-page files so that
    # a resumed run still produces the same aggregate output.
    n_docs, merged_chars = _rebuild_merged_md(output_dir)
    _log("")
    _log(f"[done] merged.md written: {merged_chars:,} chars, {n_docs} pages → {merged_md}")
    _log(f"[done] Per-page docs: {n_docs} doc_*.md files in {output_dir}")
    _log(f"[done] Images saved: {total_images} total (this run)")
    if images_dir.exists():
        _log(f"  images/: {len(list(images_dir.iterdir()))} files")
    if output_images_dir.exists():
        _log(f"  outputImages/: {len(list(output_images_dir.iterdir()))} files")


if __name__ == "__main__":
    main()
