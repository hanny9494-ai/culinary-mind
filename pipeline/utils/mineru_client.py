from __future__ import annotations

import json
import os
import time
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
import requests


class MineruError(RuntimeError):
    """Raised for MinerU-specific failures."""


@dataclass
class PdfPart:
    index: int
    path: Path
    page_start: int
    page_end: int

    @property
    def pages(self) -> int:
        return self.page_end - self.page_start + 1

    @property
    def part_id(self) -> str:
        return f"part{self.index}"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else default


def _save_json(path: Path, data: Any) -> None:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_pdf_page_count(pdf_path: Path) -> int:
    doc = fitz.open(str(pdf_path))
    try:
        return doc.page_count
    finally:
        doc.close()


def _write_pdf_slice(pdf_path: Path, out_path: Path, start_idx: int, end_idx: int) -> None:
    src = fitz.open(str(pdf_path))
    dst = fitz.open()
    _ensure_dir(out_path.parent)
    try:
        dst.insert_pdf(src, from_page=start_idx, to_page=end_idx)
        dst.save(str(out_path))
    finally:
        dst.close()
        src.close()


def _split_range_by_size(
    pdf_path: Path,
    base_name: str,
    parts_dir: Path,
    start_idx: int,
    end_idx: int,
    ranges_out: list[tuple[int, int]],
    *,
    max_mb_per_part: float,
) -> None:
    temp_path = parts_dir / f"{base_name}_{start_idx+1}_{end_idx+1}.pdf"
    _write_pdf_slice(pdf_path, temp_path, start_idx, end_idx)
    size_mb = temp_path.stat().st_size / (1024 * 1024)
    page_count = end_idx - start_idx + 1
    if size_mb <= max_mb_per_part or page_count <= 1:
        ranges_out.append((start_idx, end_idx))
        temp_path.unlink(missing_ok=True)
        return
    temp_path.unlink(missing_ok=True)
    mid = start_idx + ((end_idx - start_idx) // 2)
    _split_range_by_size(
        pdf_path,
        base_name,
        parts_dir,
        start_idx,
        mid,
        ranges_out,
        max_mb_per_part=max_mb_per_part,
    )
    _split_range_by_size(
        pdf_path,
        base_name,
        parts_dir,
        mid + 1,
        end_idx,
        ranges_out,
        max_mb_per_part=max_mb_per_part,
    )


def _build_pdf_parts(pdf_path: Path, parts_dir: Path, base_name: str, config: dict[str, Any]) -> list[PdfPart]:
    max_pages_per_part = int(config.get("max_pages_per_part") or 200)
    max_mb_per_part = float(config.get("max_mb_per_part") or 100)
    total_pages = _get_pdf_page_count(pdf_path)
    base_ranges: list[tuple[int, int]] = []
    for start in range(0, total_pages, max_pages_per_part):
        end = min(start + max_pages_per_part - 1, total_pages - 1)
        _split_range_by_size(
            pdf_path,
            base_name,
            parts_dir,
            start,
            end,
            base_ranges,
            max_mb_per_part=max_mb_per_part,
        )
    parts: list[PdfPart] = []
    for idx, (start_idx, end_idx) in enumerate(base_ranges, start=1):
        part_path = parts_dir / f"{base_name}_part{idx}.pdf"
        if not part_path.exists():
            _write_pdf_slice(pdf_path, part_path, start_idx, end_idx)
        parts.append(PdfPart(index=idx, path=part_path, page_start=start_idx + 1, page_end=end_idx + 1))
    return parts


def _quota_path(out_dir: Path) -> Path:
    return out_dir / "mineru_daily_quota.json"


def _check_daily_quota(out_dir: Path, pages_needed: int, config: dict[str, Any]) -> None:
    quota_path = _quota_path(out_dir)
    quota = _load_json(quota_path, {})
    today = time.strftime("%Y-%m-%d")
    used = int(quota.get(today, 0))
    limit = int(config.get("daily_page_limit") or 2000)
    if used + pages_needed > limit:
        raise MineruError(
            f"MinerU daily page quota exceeded: used={used}, next={pages_needed}, limit={limit}"
        )


def _record_daily_quota(out_dir: Path, pages: int) -> None:
    quota_path = _quota_path(out_dir)
    quota = _load_json(quota_path, {})
    today = time.strftime("%Y-%m-%d")
    quota[today] = int(quota.get(today, 0)) + int(pages)
    _save_json(quota_path, quota)


def _request_upload_url(base_url: str, token: str, filename: str) -> tuple[str, str]:
    response = requests.post(
        f"{base_url.rstrip('/')}/file-urls/batch",
        headers=_headers(token),
        json={
            "enable_formula": True,
            "enable_table": True,
            "language": "en",
            "files": [{"name": filename, "is_ocr": False, "data_id": filename}],
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise MineruError(f"MinerU upload-url request failed: {payload}")
    data = payload["data"]
    return str(data["file_urls"][0]), str(data["batch_id"])


def _upload_to_presigned_url(upload_url: str, pdf_path: Path) -> None:
    with pdf_path.open("rb") as fh:
        response = requests.put(upload_url, data=fh, timeout=900)
    response.raise_for_status()


def _poll_batch(base_url: str, token: str, batch_id: str, timeout_sec: int = 3600) -> str:
    started = time.time()
    url = f"{base_url.rstrip('/')}/extract-results/batch/{batch_id}"
    while time.time() - started < timeout_sec:
        response = requests.get(url, headers=_headers(token), timeout=60)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise MineruError(f"MinerU poll failed: {payload}")
        result = payload["data"]["extract_result"][0]
        state = str(result.get("state") or "")
        if state == "done":
            return str(result["full_zip_url"])
        if state == "failed":
            raise MineruError(f"MinerU extraction failed: {result.get('err_msg')}")
        time.sleep(5)
    raise MineruError(f"MinerU polling timed out for batch {batch_id}")


def _download_and_extract(zip_url: str, part_dir: Path, stem: str) -> Path:
    response = requests.get(zip_url, timeout=300)
    response.raise_for_status()
    _ensure_dir(part_dir)
    md_path: Path | None = None
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        for name in zf.namelist():
            pure_name = Path(name).name
            if not pure_name:
                continue
            if name.endswith(".md"):
                md_path = part_dir / f"{stem}.md"
                md_path.write_bytes(zf.read(name))
            elif "images/" in name or name.endswith((".png", ".jpg", ".jpeg")):
                image_path = part_dir / "images" / pure_name
                _ensure_dir(image_path.parent)
                image_path.write_bytes(zf.read(name))
            elif name.endswith(".json"):
                content_path = part_dir / f"{stem}_content_list.json"
                content_path.write_bytes(zf.read(name))
    if md_path is None:
        raise MineruError("MinerU result zip did not contain a markdown file")
    return md_path


def _combine_markdown_files(md_paths: list[Path], out_path: Path) -> None:
    blocks: list[str] = []
    for idx, md_path in enumerate(md_paths, start=1):
        text = md_path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        blocks.append(f"<!-- mineru part {idx}: {md_path.name} -->\n{text}")
    out_path.write_text(("\n\n".join(blocks).strip() + "\n") if blocks else "", encoding="utf-8")


def upload_and_extract(pdf_path: str | Path, out_dir: str | Path, config: dict[str, Any]) -> Path:
    pdf = Path(pdf_path)
    output_dir = _ensure_dir(Path(out_dir))
    token = str(config.get("api_key") or os.environ.get("MINERU_API_KEY") or "").strip()
    if not token:
        raise MineruError("Missing MinerU API key")
    base_url = str(config.get("base_url") or "https://mineru.net/api/v4")
    raw_mineru_path = output_dir / "raw_mineru.md"
    parts_dir = _ensure_dir(output_dir / "mineru_parts")
    progress_path = output_dir / "mineru_parts_progress.json"
    existing_progress = _load_json(progress_path, {"parts": []})
    existing_by_id = {
        str(item.get("part_id") or ""): item for item in existing_progress.get("parts", []) if item.get("part_id")
    }

    parts = _build_pdf_parts(pdf, parts_dir, pdf.stem.replace(" ", "_"), config)
    entries: list[dict[str, Any]] = []
    md_paths: list[Path] = []

    for part in parts:
        part_dir = _ensure_dir(parts_dir / part.part_id)
        md_path = part_dir / f"{part.part_id}.md"
        entry = {
            "part_id": part.part_id,
            "path": str(part.path),
            "page_start": part.page_start,
            "page_end": part.page_end,
            "pages": part.pages,
            "status": "pending",
            "md_path": str(md_path),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        prior = existing_by_id.get(part.part_id, {})
        if prior.get("status") == "done" and md_path.exists():
            entry["status"] = "done"
            entries.append(entry)
            md_paths.append(md_path)
            continue

        _check_daily_quota(output_dir, part.pages, config)
        upload_url, batch_id = _request_upload_url(base_url, token, part.path.name)
        _upload_to_presigned_url(upload_url, part.path)
        zip_url = _poll_batch(base_url, token, batch_id)
        result_md = _download_and_extract(zip_url, part_dir, part.part_id)
        _record_daily_quota(output_dir, part.pages)
        entry["status"] = "done"
        entry["md_path"] = str(result_md)
        entries.append(entry)
        md_paths.append(result_md)
        _save_json(progress_path, {"parts": entries})

    _save_json(progress_path, {"parts": entries})
    _combine_markdown_files(md_paths, raw_mineru_path)
    return raw_mineru_path
