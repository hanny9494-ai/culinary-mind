#!/usr/bin/env python3
"""
pipeline/skills/ocr_claw.py
OCR Claw — PDF → PaddleOCR VL 1.5 → per-page markdown + pages.json

Usage:
    python ocr_claw.py --book-id van_boekel_kinetic_modeling [--pages 10] [--mode api]
    python ocr_claw.py --book-id foo --pdf /path/to/book.pdf
    python ocr_claw.py --list-books

Output:
    output/{book_id}/pages.json  — list of {page, text, source}
    output/{book_id}/ocr.log
"""

import os, sys, json, base64, time, logging, argparse, re
from pathlib import Path

# ── Proxy bypass ──────────────────────────────────────────────────────────────
for k in ["http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY","all_proxy","ALL_PROXY"]:
    os.environ.pop(k, None)
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Config ────────────────────────────────────────────────────────────────────

def load_api_config() -> dict:
    cfg_path = REPO_ROOT / "config" / "api.yaml"
    with open(cfg_path) as f:
        return yaml.safe_load(f)

def resolve_env(val: str) -> str:
    """Replace ${VAR} placeholders with environment variable values."""
    if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
        env_var = val[2:-1]
        return os.environ.get(env_var, "")
    return val

# ── PaddleOCR API ─────────────────────────────────────────────────────────────

PADDLE_URL   = "https://t1m0ybsdk3d2hcyc.aistudio-app.com/layout-parsing"
PADDLE_TOKEN = "6c85d029b67e3ea07bd94338dc0f27ce8c54318f"

def _extract_page_text(page_result: dict) -> str:
    """
    Extract plain text from a single PaddleOCR page result.

    API response format (as of 2026-04-15):
      layoutParsingResults[i].prunedResult.parsing_res_list[j]
        .block_content  — HTML or plain text for each block
        .block_label    — 'text', 'table', 'title', etc.
    """
    text_parts: list[str] = []

    # Newest API format: result.layoutParsingResults[i].prunedResult
    pruned = page_result.get("prunedResult", page_result)
    parsing_res = pruned.get("parsing_res_list", [])
    for block in parsing_res:
        content = block.get("block_content", "") or block.get("text", "")
        if content and isinstance(content, str):
            # Strip HTML tags (tables come as <table>...</table>)
            clean = re.sub(r"<[^>]+>", " ", content)
            clean = re.sub(r"\s+", " ", clean).strip()
            if clean:
                text_parts.append(clean)

    if text_parts:
        return "\n".join(text_parts)

    # Legacy format: .markdown.text
    md = page_result.get("markdown", {})
    if isinstance(md, dict) and md.get("text"):
        return md["text"]

    # Fallback: .blocks[].text
    for b in page_result.get("blocks", []):
        t = b.get("text", "") or b.get("block_content", "")
        if t:
            text_parts.append(str(t))
    return "\n".join(text_parts)


def _call_api_with_retry(
    pdf_b64: str,
    retries: int,
    log: logging.Logger,
) -> list[dict]:
    """
    POST a base64-encoded PDF chunk to PaddleOCR API with retry.
    Returns layoutParsingResults list.
    """
    payload = {
        "file": pdf_b64,
        "fileType": 0,
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }
    headers = {
        "Authorization": f"token {PADDLE_TOKEN}",
        "Content-Type": "application/json",
    }

    for attempt in range(1, retries + 1):
        try:
            log.info(f"[OCR] Attempt {attempt}/{retries} → {PADDLE_URL}")
            with httpx.Client(trust_env=False, timeout=300, follow_redirects=False) as client:
                resp = client.post(PADDLE_URL, json=payload, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            # Unwrap nested "result" key if present
            top = data.get("result", data)
            results = top.get("layoutParsingResults", [])
            if not results:
                raise ValueError(
                    f"PaddleOCR API returned empty layoutParsingResults. "
                    f"errorCode={data.get('errorCode')} errorMsg={data.get('errorMsg')} "
                    f"top_keys={list(top.keys())}"
                )
            return results
        except Exception as e:
            log.warning(f"[OCR] Attempt {attempt} failed: {e}")
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)

    return []  # unreachable, but satisfies type checker


def ocr_pdf_api(
    pdf_path: Path,
    max_pages: int | None = None,
    retries: int = 3,
    logger: logging.Logger | None = None,
    chunk_size: int = 100,
) -> list[dict]:
    """
    Call PaddleOCR VL 1.5 API on a PDF file.
    Splits PDFs larger than chunk_size pages into multiple API calls.
    Returns list of {page: int, text: str, source: "paddleocr_api"}.
    """
    import fitz  # PyMuPDF

    log = logger or logging.getLogger(__name__)
    log.info(f"OCR API: loading {pdf_path} ({pdf_path.stat().st_size // 1024} KB)")

    doc = fitz.open(str(pdf_path))
    total = min(len(doc), max_pages or len(doc))
    log.info(f"[OCR] Total pages to process: {total} (chunk_size={chunk_size})")

    all_pages: list[dict] = []
    num_chunks = (total + chunk_size - 1) // chunk_size

    for chunk_idx, start in enumerate(range(0, total, chunk_size)):
        end = min(start + chunk_size, total)
        log.info(f"[OCR] Processing chunk {chunk_idx + 1}/{num_chunks}: pages {start + 1}–{end}")

        # Build a temporary in-memory PDF for this page range
        tmp_doc = fitz.open()
        tmp_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
        tmp_bytes = tmp_doc.tobytes()
        tmp_doc.close()

        pdf_b64 = base64.b64encode(tmp_bytes).decode()

        # Call API with per-chunk retry
        chunk_results = _call_api_with_retry(pdf_b64, retries=retries, log=log)

        # Extract pages and adjust page numbers relative to full document
        chunk_pages: list[dict] = []
        for i, page_result in enumerate(chunk_results):
            abs_page_num = start + i + 1  # 1-based absolute page number
            if abs_page_num > total:
                break
            text = _extract_page_text(page_result)
            chunk_pages.append({
                "page": abs_page_num,
                "text": text.strip(),
                "source": "paddleocr_api",
            })

        all_pages.extend(chunk_pages)
        log.info(
            f"[OCR] Chunk {chunk_idx + 1}/{num_chunks} done: "
            f"pages {start + 1}–{end}, got {len(chunk_pages)} pages "
            f"(total so far: {len(all_pages)}/{total})"
        )

        # Rate-limit pause between chunks (skip after last chunk)
        if end < total:
            time.sleep(1)

    doc.close()
    log.info(f"[OCR] Got {len(all_pages)} pages from API")
    return all_pages


def ocr_pdf_local(pdf_path: Path, max_pages: int | None = None, logger: logging.Logger | None = None) -> list[dict]:
    """
    Local PaddleOCR fallback using paddleocr Python package.
    Falls back gracefully if not installed.
    """
    log = logger or logging.getLogger(__name__)
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except ImportError:
        log.error("paddleocr package not installed. Install: pip install paddleocr")
        raise

    try:
        import fitz  # PyMuPDF
    except ImportError:
        log.error("PyMuPDF not installed. Install: pip install pymupdf")
        raise

    ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    doc = fitz.open(str(pdf_path))
    pages: list[dict] = []

    limit = min(len(doc), max_pages or len(doc))
    for i in range(limit):
        page = doc[i]
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")

        result = ocr.ocr(img_bytes, cls=True)
        lines: list[str] = []
        if result and result[0]:
            for line in result[0]:
                if line and len(line) >= 2:
                    text_conf = line[1]
                    lines.append(text_conf[0])

        pages.append({
            "page": i + 1,
            "text": "\n".join(lines),
            "source": "paddleocr_local",
        })
        log.info(f"  page {i+1}/{limit} done")

    return pages

# ── Book resolution ───────────────────────────────────────────────────────────

def find_pdf(book_id: str) -> Path | None:
    """Look for a PDF in standard output/{book_id}/ locations."""
    candidates = [
        REPO_ROOT / "output" / book_id / "source.pdf",
        REPO_ROOT / "output" / book_id / "source_converted.pdf",
        REPO_ROOT / "output" / book_id / f"{book_id}.pdf",
    ]
    for c in candidates:
        if c.exists():
            return c

    # Also check _archive subdirectory
    arch = REPO_ROOT / "output" / book_id / "_archive"
    if arch.is_dir():
        for p in arch.glob("*.pdf"):
            return p

    return None

# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OCR Claw — PDF → per-page markdown")
    p.add_argument("--book-id",  help="Book ID matching output/{book_id}/ directory")
    p.add_argument("--pdf",      help="Explicit path to PDF (overrides book-id lookup)")
    p.add_argument("--pages",    type=int, default=None, help="Max pages to process (default: all)")
    p.add_argument("--mode",     choices=["api", "local"], default="api", help="OCR mode (default: api)")
    p.add_argument("--out-dir",  help="Output directory (default: output/{book_id}/)")
    p.add_argument("--force",    action="store_true", help="Re-run even if pages.json exists")
    p.add_argument("--list-books", action="store_true", help="List available books and exit")
    p.add_argument("--chunk-size", type=int, default=100,
                   help="Max pages per API call for chunked processing (default: 100)")
    return p.parse_args()

def main() -> None:
    args = parse_args()

    if args.list_books:
        out_root = REPO_ROOT / "output"
        books = sorted(p.name for p in out_root.iterdir() if p.is_dir() and not p.name.startswith("_"))
        print(f"Available books ({len(books)}):")
        for b in books:
            pdf = find_pdf(b)
            pages_json = out_root / b / "pages.json"
            status = "✓ OCR done" if pages_json.exists() else ("PDF found" if pdf else "no PDF")
            print(f"  {b:<50} [{status}]")
        return

    # Resolve PDF path
    if args.pdf:
        pdf_path = Path(args.pdf).expanduser()
        book_id = args.book_id or pdf_path.stem
    elif args.book_id:
        book_id = args.book_id
        pdf_path = find_pdf(book_id)
        if not pdf_path:
            print(f"ERROR: No PDF found for book_id={book_id}. Try --pdf /path/to/file.pdf", file=sys.stderr)
            sys.exit(1)
    else:
        print("ERROR: Provide --book-id or --pdf", file=sys.stderr)
        sys.exit(1)

    # Output directory
    out_dir = Path(args.out_dir) if args.out_dir else (REPO_ROOT / "output" / book_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_json_path = out_dir / "pages.json"

    # Dedup check
    if pages_json_path.exists() and not args.force:
        existing = json.loads(pages_json_path.read_text())
        print(f"[ocr_claw] pages.json already exists ({len(existing)} pages). Use --force to re-run.")
        return

    # Logging
    log_path = out_dir / "ocr.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )
    log = logging.getLogger("ocr_claw")
    log.info(f"book_id={book_id}, pdf={pdf_path}, mode={args.mode}, max_pages={args.pages}, chunk_size={args.chunk_size}")

    # Run OCR
    t0 = time.time()
    if args.mode == "api":
        pages = ocr_pdf_api(pdf_path, max_pages=args.pages, logger=log, chunk_size=args.chunk_size)
    else:
        pages = ocr_pdf_local(pdf_path, max_pages=args.pages, logger=log)

    elapsed = time.time() - t0
    log.info(f"OCR done: {len(pages)} pages in {elapsed:.1f}s")

    # Write output
    pages_json_path.write_text(json.dumps(pages, ensure_ascii=False, indent=2))
    log.info(f"Wrote {pages_json_path}")

    # Summary
    total_chars = sum(len(p["text"]) for p in pages)
    empty_pages = sum(1 for p in pages if not p["text"].strip())
    print(f"\n── OCR Summary ──")
    print(f"  book_id:    {book_id}")
    print(f"  pages:      {len(pages)}")
    print(f"  total_chars:{total_chars:,}")
    print(f"  empty:      {empty_pages}")
    print(f"  time:       {elapsed:.1f}s")
    print(f"  output:     {pages_json_path}")

if __name__ == "__main__":
    main()
