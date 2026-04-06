#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://www.cdad-is.org.cn"
COOKIE_BOOTSTRAP_PATH = "/admin/Zylist/index1?type=cngenetics1&subtype=2"
LIST_PATH = "/admin/Zylist/index"
DETAIL_PATH = "/admin/Genetic.Cngenetics1/view31"
DEFAULT_SUBTYPES = [1, 2, 3, 4, 5, 6, 7, 11, 13]
PAGE_SIZE = 20


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_session() -> requests.Session:
    session = requests.Session()
    session.verify = False
    session.trust_env = False
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}{COOKIE_BOOTSTRAP_PATH}",
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    return session


def bootstrap_cookie(session: requests.Session) -> None:
    response = session.get(f"{BASE_URL}{COOKIE_BOOTSTRAP_PATH}", timeout=60)
    response.raise_for_status()


def post_form_json(
    session: requests.Session,
    path: str,
    query: dict[str, Any],
    form: dict[str, Any],
) -> Any:
    response = session.post(f"{BASE_URL}{path}", params=query, data=form, timeout=120)
    response.raise_for_status()
    return response.json()


def extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("data", "rows", "list"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                for nested_key in ("rows", "list", "data"):
                    nested_value = value.get(nested_key)
                    if isinstance(nested_value, list):
                        return nested_value
    if isinstance(payload, list):
        return payload
    return []


def extract_total(payload: Any, fallback_count: int) -> int:
    if isinstance(payload, dict):
        for key in ("total", "count"):
            value = payload.get(key)
            if isinstance(value, int):
                return value
        for nested_key in ("data",):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                for key in ("total", "count"):
                    value = nested.get(key)
                    if isinstance(value, int):
                        return value
    return fallback_count


def fetch_breed_pages(session: requests.Session, subtype: int, delay_s: float, max_pages: int | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    page_no = 1
    all_rows: list[dict[str, Any]] = []
    page_payloads: list[dict[str, Any]] = []
    while True:
        if max_pages is not None and page_no > max_pages:
            break
        offset = (page_no - 1) * PAGE_SIZE
        query = {"type": "cngenetics1", "subtype": str(subtype)}
        form = {"offset": offset, "limit": PAGE_SIZE}
        data = post_form_json(session, LIST_PATH, query, form)
        rows = extract_rows(data)
        total = extract_total(data, len(rows))
        page_payloads.append(
            {"request": {"query": query, "form": form}, "response": data, "row_count": len(rows), "total": total}
        )
        if not rows:
            break
        all_rows.extend(rows)
        print(f"[list] subtype={subtype} page={page_no} rows={len(rows)} total={total}", flush=True)
        if len(rows) < PAGE_SIZE or len(all_rows) >= total:
            break
        page_no += 1
        time.sleep(delay_s)
    return all_rows, page_payloads


def parse_detail_html(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str] = {}
    ordered_fields: list[dict[str, str]] = []
    for tr in soup.select("table tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.select("th,td")]
        if len(cells) >= 2:
            key = cells[0]
            value = " ".join(cells[1:]).strip()
            if key:
                fields[key] = value
                ordered_fields.append({"label": key, "value": value})

    body_text = "\n".join(
        line.strip()
        for line in soup.get_text("\n", strip=True).splitlines()
        if line.strip()
    )
    return {"fields": fields, "ordered_fields": ordered_fields, "text": body_text}


def fetch_breed_detail(
    session: requests.Session,
    breed_id: int | str,
    subtype: int,
) -> tuple[str, dict[str, Any]]:
    response = session.get(
        f"{BASE_URL}{DETAIL_PATH}",
        params={"id": breed_id, "subtype": subtype},
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        timeout=120,
    )
    response.raise_for_status()
    html = response.text
    parsed = parse_detail_html(html)
    return html, parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape CDAD Chinese livestock/poultry genetic resource breed data")
    parser.add_argument("--output-dir", default="~/culinary-engine/data/external/cdad_breeds")
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--subtypes", default="1,2,3,4,5,6,7,11,13")
    parser.add_argument("--max-list-pages", type=int, default=None, help="Limit list pages per subtype for testing")
    parser.add_argument("--max-breeds", type=int, default=None, help="Limit total breeds for testing")
    parser.add_argument("--skip-articles", action="store_true")
    args = parser.parse_args()

    output_dir = ensure_dir(Path(args.output_dir).expanduser())
    raw_dir = ensure_dir(output_dir / "raw")
    breeds_dir = ensure_dir(output_dir / "breeds")
    details_html_dir = ensure_dir(output_dir / "details_html")
    details_json_dir = ensure_dir(output_dir / "details_json")
    subtypes = [int(item.strip()) for item in args.subtypes.split(",") if item.strip()]

    session = build_session()
    bootstrap_cookie(session)
    write_json(output_dir / "session_cookies.json", session.cookies.get_dict())

    all_breeds: list[dict[str, Any]] = []
    subtype_summaries: list[dict[str, Any]] = []
    for subtype in subtypes:
        breeds, page_payloads = fetch_breed_pages(session, subtype, args.delay, args.max_list_pages)
        write_json(raw_dir / f"list_subtype_{subtype}.json", page_payloads)
        subtype_summaries.append({"subtype": subtype, "breed_count": len(breeds)})
        for breed in breeds:
            breed["subtype"] = subtype
        all_breeds.extend(breeds)
        time.sleep(args.delay)

    if args.max_breeds is not None:
        all_breeds = all_breeds[: args.max_breeds]

    write_json(output_dir / "subtype_summary.json", subtype_summaries)
    write_json(output_dir / "all_breeds.json", all_breeds)
    with (output_dir / "all_breeds.jsonl").open("w", encoding="utf-8") as fh:
        for breed in all_breeds:
            fh.write(json.dumps(breed, ensure_ascii=False) + "\n")

    detail_summary: list[dict[str, Any]] = []
    if not args.skip_articles:
        for index, breed in enumerate(all_breeds, start=1):
            breed_id = breed.get("id")
            subtype = breed.get("subtype")
            if breed_id is None or subtype is None:
                print(f"[warn] breed missing id field at index={index}: {breed}", flush=True)
                continue
            html, detail = fetch_breed_detail(session, breed_id, int(subtype))
            (details_html_dir / f"{breed_id}.html").write_text(html, encoding="utf-8")
            write_json(details_json_dir / f"{breed_id}.json", detail)
            breed_record = dict(breed)
            breed_record["detail_fields"] = detail["fields"]
            breed_record["detail_field_count"] = len(detail["fields"])
            write_json(breeds_dir / f"{breed_id}.json", breed_record)
            detail_summary.append(
                {
                    "id": breed_id,
                    "subtype": subtype,
                    "name": breed.get("pzmc"),
                    "detail_field_count": len(detail["fields"]),
                }
            )
            print(
                f"[breed] {index}/{len(all_breeds)} id={breed_id} subtype={subtype} fields={len(detail['fields'])}",
                flush=True,
            )
            time.sleep(args.delay)

    write_json(output_dir / "detail_summary.json", detail_summary)
    print(f"Done. breeds={len(all_breeds)} details={len(detail_summary)} output={output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
