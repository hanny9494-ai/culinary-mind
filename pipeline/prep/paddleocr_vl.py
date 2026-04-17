#!/usr/bin/env python3
"""paddleocr_vl.py — PaddleOCR-VL 1.5 OCR for Chinese books (PDF/EPUB).

Usage:
  python3 pipeline/prep/paddleocr_vl.py \\
      --pdf /path/to/book.pdf \\
      --output-dir output/shijing \\
      [--start-page 1] [--end-page 20]

Outputs:
  output/{book_id}/pages_vl.json  — per-page markdown (resume-safe)
  output/{book_id}/merged.md      — full merged text (<!-- page N --> separators)

Requires:
  pip install paddleocr pypdfium2 Pillow
  Model: ~/.paddlex/official_models/PaddleOCR-VL-1.5 (pre-downloaded)

Notes:
  - Resume: pages already in pages_vl.json are skipped on re-run.
  - EPUB: must be converted to PDF first (e.g. ebook-convert book.epub book.pdf).
  - Model connectivity check is disabled via env var.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Disable PaddleX model source connectivity check (required for offline use)
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

# ── Imports ────────────────────────────────────────────────────────────────────
try:
    import pypdfium2 as pdfium
except ImportError:
    print("ERROR: pypdfium2 not installed. Run: pip install pypdfium2", file=sys.stderr)
    raise SystemExit(1)

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow not installed. Run: pip install Pillow", file=sys.stderr)
    raise SystemExit(1)

# PaddleOCR-VL is imported lazily (slow to load) — only when actually running
_pipeline = None


def _get_pipeline() -> Any:
    global _pipeline
    if _pipeline is None:
        try:
            from paddleocr import PaddleOCRVL
        except ImportError:
            print("ERROR: paddleocr not installed. Run: pip install paddleocr", file=sys.stderr)
            raise SystemExit(1)
        print("[init] Loading PaddleOCR-VL 1.5 model…", flush=True)
        _pipeline = PaddleOCRVL(pipeline_version="v1.5")
        print("[init] Model loaded.", flush=True)
    return _pipeline


# ── Page JSON helpers ──────────────────────────────────────────────────────────

def load_pages_json(path: Path) -> dict[int, dict[str, Any]]:
    """Load existing pages_vl.json → {page_number: page_dict}."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pages = data.get("pages") if isinstance(data, dict) else data
        if not isinstance(pages, list):
            return {}
        return {int(p["page_number"]): p for p in pages if "page_number" in p}
    except Exception as e:
        print(f"[warn] Could not load {path}: {e}", flush=True)
        return {}


def save_pages_json(path: Path, pdf: Path, pages: dict[int, dict[str, Any]]) -> None:
    """Write pages_vl.json atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = [pages[k] for k in sorted(pages)]
    payload = {
        "source_pdf": str(pdf),
        "model": "PaddleOCR-VL-1.5",
        "page_count": len(ordered),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pages": ordered,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ── Merged markdown writer ─────────────────────────────────────────────────────

def write_merged_md(path: Path, pages: dict[int, dict[str, Any]]) -> None:
    """Write merged.md with <!-- page N --> separators (compatible with ocr.py)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    for page_num in sorted(pages):
        md = str(pages[page_num].get("markdown") or "").strip()
        parts.append(f"<!-- page {page_num} -->\n{md}".strip())
    merged = "\n\n".join(p for p in parts if p.strip()) + "\n"
    path.write_text(merged, encoding="utf-8")


# ── PDF page renderer ──────────────────────────────────────────────────────────

def render_page_to_png(pdf_path: Path, page_index: int, scale: float = 2.0) -> Path:
    """Render one PDF page to a temp PNG file. Returns the PNG path."""
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        page = doc[page_index]
        bitmap = page.render(scale=scale)
        img = bitmap.to_pil()
    finally:
        doc.close()

    tmp_path = Path(f"/tmp/_paddleocr_vl_page_{page_index}.png")
    img.save(str(tmp_path), format="PNG")
    return tmp_path


# ── OCR one page ──────────────────────────────────────────────────────────────

def ocr_page(png_path: Path, page_number: int) -> dict[str, Any]:
    """Run PaddleOCR-VL on a single PNG page. Returns page dict."""
    pipeline = _get_pipeline()
    t0 = time.time()

    results = pipeline.predict(str(png_path))

    markdown_text = ""
    if results:
        res = results[0]
        try:
            md_data = res._to_markdown()
            markdown_text = md_data.get("markdown_texts") or ""
        except Exception as e:
            print(f"[warn] page {page_number}: _to_markdown failed: {e}", flush=True)
            # Fallback: try to get raw text from result
            try:
                markdown_text = str(res)
            except Exception:
                markdown_text = ""

    elapsed = time.time() - t0
    return {
        "page_number": page_number,
        "markdown": markdown_text,
        "model": "PaddleOCR-VL-1.5",
        "elapsed_s": round(elapsed, 2),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PaddleOCR-VL 1.5 OCR for PDF books (Chinese/Traditional)"
    )
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--start-page", type=int, default=1, help="First page (1-indexed)")
    parser.add_argument("--end-page", type=int, default=None, help="Last page (1-indexed, inclusive)")
    parser.add_argument("--scale", type=float, default=2.0, help="PDF render scale (default 2.0)")
    parser.add_argument("--no-resume", action="store_true", help="Ignore existing progress, re-OCR all pages")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    pages_json_path = output_dir / "pages_vl.json"
    merged_md_path = output_dir / "merged.md"

    # Open PDF to get page count
    doc = pdfium.PdfDocument(str(pdf_path))
    total_pages = len(doc)
    doc.close()
    print(f"[info] PDF: {pdf_path.name}  total_pages={total_pages}", flush=True)

    start = max(1, args.start_page)
    end = min(total_pages, args.end_page) if args.end_page else total_pages
    print(f"[info] Processing pages {start}–{end}", flush=True)

    # Load existing progress
    existing: dict[int, dict[str, Any]] = {}
    if not args.no_resume:
        existing = load_pages_json(pages_json_path)
        if existing:
            print(f"[resume] {len(existing)} pages already done, skipping.", flush=True)

    # Determine pending pages
    pending = [p for p in range(start, end + 1) if p not in existing]
    print(f"[info] Pages to process: {len(pending)}", flush=True)

    if not pending:
        print("[done] Nothing to do (all pages already processed).", flush=True)
        write_merged_md(merged_md_path, existing)
        return 0

    # Process pages one at a time (VL model is sequential)
    for i, page_num in enumerate(pending, 1):
        page_index = page_num - 1  # 0-indexed for pypdfium2
        print(f"[ocr] page {page_num}/{end} ({i}/{len(pending)})…", end=" ", flush=True)

        try:
            png_path = render_page_to_png(pdf_path, page_index, scale=args.scale)
            page_data = ocr_page(png_path, page_num)
            # Clean up temp PNG
            try:
                png_path.unlink()
            except Exception:
                pass

            existing[page_num] = page_data
            md_preview = (page_data["markdown"] or "")[:60].replace("\n", " ")
            print(f"done ({page_data['elapsed_s']:.1f}s) | {md_preview!r}", flush=True)

        except KeyboardInterrupt:
            print("\n[interrupted] Saving progress…", flush=True)
            save_pages_json(pages_json_path, pdf_path, existing)
            write_merged_md(merged_md_path, existing)
            print(f"[saved] {len(existing)} pages → {pages_json_path}", flush=True)
            return 130

        except Exception as e:
            print(f"FAILED: {e}", flush=True)
            # Continue with next page — don't abort entire book for one bad page
            existing[page_num] = {
                "page_number": page_num,
                "markdown": f"<!-- ocr failed: {e} -->",
                "model": "PaddleOCR-VL-1.5",
                "error": str(e),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        # Checkpoint every 10 pages
        if i % 10 == 0 or i == len(pending):
            save_pages_json(pages_json_path, pdf_path, existing)
            write_merged_md(merged_md_path, existing)
            print(f"[checkpoint] {len(existing)}/{total_pages} pages saved", flush=True)

    # Final write
    save_pages_json(pages_json_path, pdf_path, existing)
    write_merged_md(merged_md_path, existing)
    done_count = sum(1 for p in existing.values() if "error" not in p)
    print(f"[done] {done_count} pages OK, {len(existing)-done_count} errors", flush=True)
    print(f"  pages_vl.json → {pages_json_path}", flush=True)
    print(f"  merged.md     → {merged_md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
