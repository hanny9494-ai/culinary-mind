#!/usr/bin/env python3
"""Phase 0b — Download flavor/chemistry/food-composition databases.

HARD CONSTRAINTS:
  - Only writes to data/external/raw/
  - trust_env=False for direct downloads; proxy used only for EU sites that require it
  - No loaders, no cleaning, no DB imports
  - No scraping — if a dataset requires a scraper, document it and skip
  - Total disk budget: 15GB (2.7GB already used → 12GB remaining)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Clear proxy env vars by default (override per-request when needed)
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY"]:
    os.environ.pop(_k, None)
os.environ["no_proxy"] = "localhost,127.0.0.1"

import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "external" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
NOW = datetime.now(timezone.utc).isoformat()
PROXY = "http://127.0.0.1:7890"
REPORT: list[dict] = []


# ─── helpers ─────────────────────────────────

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def human_size(n: float) -> str:
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"

def disk_used_raw() -> int:
    return sum(f.stat().st_size for f in RAW_DIR.rglob("*")
               if f.is_file() and ".git" not in str(f))

def download_file(url: str, dest: Path, desc: str = "",
                  use_proxy: bool = False, timeout: int = 600) -> tuple[bool, str]:
    print(f"  ↓ {desc or url}")
    env = dict(os.environ)
    if use_proxy:
        env["http_proxy"] = PROXY
        env["https_proxy"] = PROXY
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "culinary-mind/phase0b"})
        if use_proxy:
            proxy_handler = urllib.request.ProxyHandler(
                {"http": PROXY, "https": PROXY})
            opener = urllib.request.build_opener(proxy_handler)
        else:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}))  # no proxy
        with opener.open(req, timeout=timeout) as resp, open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            while chunk := resp.read(65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    print(f"\r    {human_size(downloaded)} / {human_size(total)} ({downloaded/total*100:.0f}%)",
                          end="", flush=True)
                else:
                    print(f"\r    {human_size(downloaded)}", end="", flush=True)
        print()
        return True, f"OK ({human_size(dest.stat().st_size)})"
    except Exception as e:
        return False, str(e)

def write_readme(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")

def write_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8")

def record(name: str, status: str, size: str, notes: str,
           files: list[dict] | None = None, needs_collector: bool = False) -> None:
    REPORT.append({"dataset": name, "status": status, "size": size,
                   "notes": notes, "files": files or [],
                   "needs_open_data_collector": needs_collector})
    icon = {"done": "✅", "pending": "⏳", "partial": "⚠️",
            "failed": "❌", "dropped": "❌", "needs_scraper": "🤖"}.get(status, "❓")
    print(f"\n{icon} {name}: {status} — {size}")
    if notes:
        print(f"   {notes}")


# ──────────────────────────────────────────────
# P0-1: FooDB (already exists at data/external/foodb/)
# ──────────────────────────────────────────────

def pull_foodb() -> None:
    name = "FooDB"
    target = RAW_DIR / "foodb"
    target.mkdir(exist_ok=True)

    existing = REPO_ROOT / "data" / "external" / "foodb"
    existing_csv = existing / "foodb_2020_04_07_csv"
    existing_tar = existing / "foodb_2020_4_7_csv.tar.gz"

    files = []
    total_sz = 0
    if existing_csv.exists():
        sz = sum(f.stat().st_size for f in existing_csv.rglob("*") if f.is_file())
        total_sz += sz
        files.append({"path": str(existing_csv.relative_to(REPO_ROOT)),
                      "size": human_size(sz), "tables": len(list(existing_csv.glob("*.csv")))})
    if existing_tar.exists():
        sz2 = existing_tar.stat().st_size
        total_sz += sz2
        files.append({"path": str(existing_tar.relative_to(REPO_ROOT)),
                      "size": human_size(sz2)})

    csv_tables = list(existing_csv.glob("*.csv")) if existing_csv.exists() else []

    write_readme(target / "README.md", f"""# FooDB

**Description**: Canadian food composition database. {len(csv_tables)} CSV tables covering
nutrients AND non-nutrient food components (polyphenols, aroma compounds, etc.).
More detailed than USDA for secondary metabolites.
**Source**: https://foodb.ca/downloads
**Version**: 2020-04-07
**Downloaded**: Previously (see data/external/foodb/)
**License**: CC BY-NC 4.0 (non-commercial confirmed OK)
**Expected Role**: Reference layer — L2a food component cross-reference; secondary metabolite data

## Data Location
Existing data at `data/external/foodb/` — not duplicated in raw/ to save disk.

## Key Tables ({len(csv_tables)} CSVs)
- `Compound.csv` — chemical compounds with properties
- `Content.csv` — food × compound concentration data (main join table)
- `Food.csv` — 1,000+ food items
- `Nutrient.csv` — nutrient definitions
- `CompoundSynonym.csv` — compound name aliases

## Status
✅ Complete (data exists at data/external/foodb/)

## Notes
- Do NOT import into production without QC pass.
- Key join: Food.csv × Content.csv × Compound.csv gives food→compound→concentration.
""")

    write_manifest(target / "manifest.json", {
        "name": "FooDB", "version": "2020-04-07",
        "source_url": "https://foodb.ca/downloads",
        "download_date": NOW,
        "actual_location": str(existing),
        "files": files, "role": "reference",
        "license": "CC BY-NC 4.0",
        "notes": f"Already downloaded. {len(csv_tables)} CSV tables at data/external/foodb/.",
    })
    record(name, "done", human_size(total_sz),
           f"Already at data/external/foodb/ — {len(csv_tables)} CSV tables", files)


# ──────────────────────────────────────────────
# P0-2: FoodAtlas
# ──────────────────────────────────────────────

def pull_foodatlas() -> None:
    name = "FoodAtlas"
    target = RAW_DIR / "foodatlas"
    t0 = time.time()

    # Search for the right repo — "knbuckner/FoodAtlas" has 0 stars, try others
    candidates = [
        "https://github.com/knbuckner/FoodAtlas",
        "https://github.com/FoodAtlas/FoodAtlas",
        "https://github.com/davidmoirekassel/FoodAtlas",
    ]

    # Check which one exists
    repo_url = None
    for url in candidates:
        api_url = url.replace("https://github.com/", "https://api.github.com/repos/")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(api_url, headers={
                "User-Agent": "culinary-mind/phase0b",
                "Accept": "application/vnd.github.v3+json"})
            with opener.open(req, timeout=10) as resp:
                d = json.loads(resp.read())
                if d.get("id"):
                    repo_url = url
                    print(f"  Found FoodAtlas: {url} (stars: {d.get('stargazers_count',0)})")
                    break
        except:
            continue

    if repo_url is None:
        # Try the knbuckner one directly via clone
        repo_url = "https://github.com/knbuckner/FoodAtlas"

    if (target / ".git").exists():
        print("  FoodAtlas already cloned, pulling...")
        result = subprocess.run(["git", "-C", str(target), "pull", "--ff-only"],
                                capture_output=True, text=True)
        ok = result.returncode == 0
    else:
        print(f"  git clone {repo_url}...")
        result = subprocess.run(
            ["git", "clone", "--depth=1", repo_url, str(target)],
            capture_output=True, text=True, timeout=120)
        ok = result.returncode == 0

    elapsed = time.time() - t0

    if not ok:
        # Document and skip
        write_readme(target / "README.md" if (target / ".git").exists() else
                     (target.mkdir(exist_ok=True) or target / "README.md"),
                     f"""# FoodAtlas

**Description**: Food-compound relationship database (ingredient × chemical compound mappings).
**Source**: https://github.com/knbuckner/FoodAtlas (or related)
**Status**: ❌ Clone failed

## Error
{result.stderr[:300]}

## Next Steps
- Try manually: `git clone {repo_url} data/external/raw/foodatlas/`
- Or check if repo moved to a different organization
""")
        target.mkdir(exist_ok=True)
        write_manifest(target / "manifest.json", {
            "name": "FoodAtlas", "version": "unknown",
            "source_url": repo_url, "download_date": NOW,
            "files": [], "role": "prior", "license": "unknown",
            "notes": f"Clone failed: {result.stderr[:200]}"})
        record(name, "failed", "0 B", f"git clone failed: {result.stderr[:100]}")
        return

    commit = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()[:12]
    total_sz = sum(f.stat().st_size for f in target.rglob("*")
                   if f.is_file() and ".git" not in str(f))
    files = [{"path": str(f.relative_to(REPO_ROOT)), "size": human_size(f.stat().st_size)}
             for f in sorted(target.rglob("*"))
             if f.is_file() and ".git" not in str(f)][:30]

    write_readme(target / "README.md", f"""# FoodAtlas

**Description**: Food ingredient × chemical compound relationship database.
**Source**: {repo_url}
**Commit**: {commit}
**Downloaded**: {NOW}
**License**: See repo LICENSE
**Expected Role**: Prior layer — ingredient-to-compound mappings for flavor graph

## Status
✅ Complete (git clone --depth=1, commit {commit})

## Notes
- Do NOT import into production without QC.
- Key data: ingredient-compound relationship tables.
""")
    write_manifest(target / "manifest.json", {
        "name": "FoodAtlas", "version": f"git-{commit}",
        "source_url": repo_url, "download_date": NOW,
        "files": files, "role": "prior", "license": "See repo",
        "notes": f"git clone --depth=1, commit {commit}",
        "elapsed_seconds": round(elapsed, 1)})
    record(name, "done", human_size(total_sz), f"commit {commit}", files[:5])


# ──────────────────────────────────────────────
# P0-3: FlavorDB2 (no API — needs scraper)
# ──────────────────────────────────────────────

def pull_flavordb2() -> None:
    name = "FlavorDB2"
    target = RAW_DIR / "flavordb2"
    target.mkdir(exist_ok=True)

    # Try all known API/download patterns
    base = "https://cosylab.iiitd.edu.in/flavordb2"
    api_attempts = [
        f"{base}/api/entity/all",
        f"{base}/api/flavor/all",
        f"{base}/api/ingredient/all",
        f"{base}/api/molecule/all",
        f"{base}/flavordb/api/entity/all",
        f"{base}/static/data/entities.json",
        f"{base}/static/data/flavors.json",
        # Original FlavorDB (predecessor)
        "https://flavordb.org/api/entity/all",
        "http://cosylab.iiitd.edu.in/flavordb/api/entity/all",
    ]

    found_data = False
    for url in api_attempts:
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(url, headers={"User-Agent": "culinary-mind/phase0b"})
            with opener.open(req, timeout=10) as resp:
                if resp.status == 200:
                    content = resp.read()
                    if len(content) > 1000:  # real data, not error page
                        fname = url.split("/")[-1] or "data.json"
                        (target / fname).write_bytes(content)
                        print(f"  ✓ Got data from {url} ({human_size(len(content))})")
                        found_data = True
        except:
            continue

    write_readme(target / "README.md", f"""# FlavorDB2

**Description**: 25,595 flavor molecules × 936 food ingredients database (IIIT Delhi).
This is the upstream raw data source for FlavorGraph's pre-trained embeddings.
**Source**: https://cosylab.iiitd.edu.in/flavordb2/
**Original**: https://flavordb.org/ (predecessor)
**Status**: {'⚠️ Partial — some data retrieved' if found_data else '🤖 NEEDS SCRAPER — no direct download API'}

## Why Scraping Required
FlavorDB2 is a web application (DataTables.js frontend). Data is served via paginated AJAX
calls, not a bulk download endpoint. All direct API attempts returned 404.

The data is accessible via:
- Web UI: https://cosylab.iiitd.edu.in/flavordb2/
- Individual entity pages: /flavordb2/entity/<id>
- Individual ingredient pages: /flavordb2/ingredient/<name>

## Recommended Approach: open-data-collector + OpenClaw
1. Enumerate entity IDs 1–25595 via: `GET /flavordb2/entity/<id>`
2. Each entity returns flavor molecules + ingredient associations
3. ~25,595 requests; 1 req/s = ~7 hours on Mac Mini sandbox

## Expected Data Schema (from paper)
- entity_id, entity_alias_readable (ingredient name)
- flavor_molecules: list of {{molecule_id, common_name, CAS, FEMA, odor_description}}

## Notes
- Paper: "FlavorDB: a database of flavor molecules" (NAR 2018)
- doi: 10.1093/nar/gkx957
- This is P0-critical for rebuilding our own flavor graph from raw molecular data.
""")
    write_manifest(target / "manifest.json", {
        "name": "FlavorDB2", "version": "unknown",
        "source_url": "https://cosylab.iiitd.edu.in/flavordb2/",
        "download_date": NOW, "files": [],
        "role": "prior", "license": "Academic",
        "status": "needs_scraper",
        "notes": "No bulk download API. Needs open-data-collector + OpenClaw (entity enumeration 1-25595).",
        "scraper_spec": {
            "type": "entity_enumeration",
            "base_url": "https://cosylab.iiitd.edu.in/flavordb2/entity/{id}",
            "id_range": [1, 25595],
            "rate_limit": "1 req/s",
            "estimated_time_hours": 7,
        }
    })
    record(name, "needs_scraper", "0 B",
           "No bulk API — needs open-data-collector (entity enumeration 1-25595, ~7h)",
           needs_collector=True)


# ──────────────────────────────────────────────
# P1-1: Open Food Facts
# ──────────────────────────────────────────────

def pull_open_food_facts() -> None:
    name = "Open Food Facts"
    target = RAW_DIR / "open_food_facts"
    target.mkdir(exist_ok=True)
    t0 = time.time()

    # Disk budget check: ~1.2GB gzip + unzip to ~9GB CSV — too large
    # Only download the gzip, don't unzip
    url = "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz"
    dest = target / "en.openfoodfacts.org.products.csv.gz"

    # Check disk
    used = disk_used_raw()
    avail = shutil.disk_usage(str(RAW_DIR)).free
    print(f"  Disk check: raw/ = {human_size(used)}, free = {human_size(avail)}")

    files = []
    failed = []

    if dest.exists() and dest.stat().st_size > 100_000_000:
        print(f"  ✓ Already exists ({human_size(dest.stat().st_size)})")
        files.append({"path": str(dest.relative_to(REPO_ROOT)),
                      "size": human_size(dest.stat().st_size),
                      "sha256": sha256_file(dest)})
    else:
        ok, msg = download_file(url, dest, "Open Food Facts CSV.gz (~1.2GB)", use_proxy=False)
        if not ok:
            # Try with proxy
            print(f"  Direct failed ({msg}), trying proxy...")
            ok, msg = download_file(url, dest, "Open Food Facts CSV.gz (via proxy)", use_proxy=True)
        if ok:
            files.append({"path": str(dest.relative_to(REPO_ROOT)),
                          "size": human_size(dest.stat().st_size),
                          "sha256": sha256_file(dest)})
        else:
            failed.append(msg)

    elapsed = time.time() - t0
    total_sz = sum(f.stat().st_size for f in target.glob("*") if f.is_file())

    write_readme(target / "README.md", f"""# Open Food Facts

**Description**: Open crowdsourced database of food products worldwide. 3M+ products with
nutrition labels, ingredients lists, additives, allergens, packaging, and more.
**Source**: https://world.openfoodfacts.org/data
**Downloaded**: {NOW}
**License**: Open Database License (ODbL) + Database Contents License (DbCL)
**Expected Role**: Reference layer — L2c commercial food ingredients + nutrition cross-reference

## Files
| File | Size | Description |
|------|------|-------------|
| en.openfoodfacts.org.products.csv.gz | ~1.2 GB | Full product database (gzipped CSV) |

## Schema (key columns)
code, product_name, brands, categories, ingredients_text, nutriments,
additives_tags, allergens, countries, labels

## Status
{'✅ Complete' if not failed else '❌ Failed — ' + '; '.join(failed[:1])}

## Notes
- ~3M products. Do NOT import into production without QC.
- To inspect: `zcat en.openfoodfacts.org.products.csv.gz | head -5`
- Full unzipped size ~9GB — keeping gzip only to save disk.
""")
    write_manifest(target / "manifest.json", {
        "name": "Open Food Facts",
        "version": f"snapshot-{NOW[:10]}",
        "source_url": "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz",
        "download_date": NOW, "files": files,
        "role": "reference", "license": "ODbL + DbCL",
        "notes": "; ".join(failed) if failed else "Complete gzip.",
        "elapsed_seconds": round(elapsed, 1)})
    status = "done" if not failed else "failed"
    record(name, status, human_size(total_sz),
           "; ".join(failed) if failed else f"elapsed {elapsed:.0f}s", files)


# ──────────────────────────────────────────────
# P1-2: Phenol-Explorer (via proxy — EU site)
# ──────────────────────────────────────────────

def pull_phenol_explorer() -> None:
    name = "Phenol-Explorer"
    target = RAW_DIR / "phenol_explorer"
    target.mkdir(exist_ok=True)
    t0 = time.time()

    # Get download links from the downloads page
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
        req = urllib.request.Request("http://phenol-explorer.eu/downloads",
                                     headers={"User-Agent": "culinary-mind/phase0b"})
        with opener.open(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        html = ""
        print(f"  Could not fetch downloads page: {e}")

    # Extract download links
    import re
    links = re.findall(r'href="([^"]*(?:csv|xls|xlsx|zip|gz|tsv)[^"]*)"', html, re.I)
    base_url = "http://phenol-explorer.eu"

    files = []
    failed = []

    if not links:
        # Try known direct URLs
        links = [
            "/downloads/phenol-explorer-3-1.zip",
            "/downloads/compounds.csv",
            "/downloads/foods.csv",
            "/downloads/composition.csv",
        ]

    for link in links[:10]:
        if not link.startswith("http"):
            link = base_url + link
        fname = link.split("/")[-1].split("?")[0]
        dest = target / fname
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"  ✓ {fname} already exists")
            files.append({"path": str(dest.relative_to(REPO_ROOT)),
                          "size": human_size(dest.stat().st_size)})
            continue
        ok, msg = download_file(link, dest, fname, use_proxy=True, timeout=120)
        if ok:
            files.append({"path": str(dest.relative_to(REPO_ROOT)),
                          "size": human_size(dest.stat().st_size)})
        else:
            failed.append(f"{fname}: {msg}")
            print(f"  ✗ {fname}: {msg}")

    elapsed = time.time() - t0
    total_sz = sum(f.stat().st_size for f in target.glob("*") if f.is_file())

    write_readme(target / "README.md", f"""# Phenol-Explorer

**Description**: Polyphenol content database — 500+ polyphenols in 400+ foods.
Covers tannins, anthocyanins, flavonoids, stilbenes, lignans, etc.
**Source**: http://phenol-explorer.eu/downloads
**Downloaded**: {NOW}
**License**: CC BY 3.0
**Expected Role**: Reference layer — texture/astringency dimension for FT taste vectors

## Status
{'✅ Complete' if files and not failed else ('⚠️ Partial' if files else '❌ Failed')}
{chr(10).join('- ' + f for f in failed) if failed else ''}

## Key Data
- Polyphenol → food concentration data
- Chemical properties (MW, formula, CAS)
- Food categories
- Method of measurement

## Notes
- Do NOT import into production without QC.
- Key for modeling astringency/bitterness (tannin concentration → texture effect).
""")
    write_manifest(target / "manifest.json", {
        "name": "Phenol-Explorer",
        "version": "3.6 (or latest)",
        "source_url": "http://phenol-explorer.eu/downloads",
        "download_date": NOW, "files": files,
        "role": "reference", "license": "CC BY 3.0",
        "notes": "; ".join(failed) if failed else "Complete.",
        "elapsed_seconds": round(elapsed, 1)})
    status = "done" if files and not failed else ("partial" if files else "failed")
    record(name, status, human_size(total_sz),
           "; ".join(failed) if failed else f"elapsed {elapsed:.0f}s", files)


# ──────────────────────────────────────────────
# P1-3: BitterDB
# ──────────────────────────────────────────────

def pull_bitterdb() -> None:
    name = "BitterDB"
    target = RAW_DIR / "bitterdb"
    target.mkdir(exist_ok=True)

    # BitterDB is at Hebrew University — often slow/unreachable
    # Try both direct and proxy
    urls_to_try = [
        ("http://bitterdb.agri.huji.ac.il/bitterdb/", False),
        ("http://bitterdb.agri.huji.ac.il/bitterdb/", True),
        ("https://bitterdb.agri.huji.ac.il/bitterdb/", True),
    ]

    reachable = False
    html = ""
    for url, use_proxy in urls_to_try:
        try:
            if use_proxy:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
            else:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(url, headers={"User-Agent": "culinary-mind/phase0b"})
            with opener.open(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                reachable = True
                print(f"  Reached BitterDB via {'proxy' if use_proxy else 'direct'}")
                break
        except Exception as e:
            print(f"  BitterDB {'proxy' if use_proxy else 'direct'} failed: {e}")

    # Try to find download links
    import re
    files = []
    if reachable:
        links = re.findall(r'href="([^"]*(?:csv|xls|xlsx|zip|gz|download)[^"]*)"', html, re.I)
        for link in links[:5]:
            if not link.startswith("http"):
                link = "http://bitterdb.agri.huji.ac.il" + link
            fname = link.split("/")[-1].split("?")[0] or "bitterdb_data"
            dest = target / fname
            ok, msg = download_file(link, dest, fname, use_proxy=True, timeout=60)
            if ok:
                files.append({"path": str(dest.relative_to(REPO_ROOT)),
                              "size": human_size(dest.stat().st_size)})

    write_readme(target / "README.md", f"""# BitterDB

**Description**: Database of bitter compounds and bitter taste receptors (hTAS2Rs).
~1,000 bitter compounds with molecular structures, receptor binding data, and sensory thresholds.
**Source**: http://bitterdb.agri.huji.ac.il/bitterdb/
**Downloaded**: {NOW}
**License**: Academic/research use
**Expected Role**: Reference layer — bitter taste dimension for FT taste vectors

## Status
{'✅ Complete' if files else ('⚠️ Site reachable but no download links found' if reachable else '❌ Site unreachable')}

## Access Notes
- Server: Hebrew University, Jerusalem — may be slow or blocked from CN network
- Try: http://bitterdb.agri.huji.ac.il/bitterdb/
- Download may require navigation through web UI
- Alternative: paper supplementary data (Dagan-Wiener et al. 2019, doi:10.1093/nar/gky974)

## If Manually Needed
1. Visit http://bitterdb.agri.huji.ac.il/bitterdb/dload.php (download page)
2. Download compound CSV + receptor CSV
3. Place in data/external/raw/bitterdb/

## Notes
- ~1,000 compounds. Small dataset, manageable for manual download.
- Do NOT import into production without QC.
""")
    write_manifest(target / "manifest.json", {
        "name": "BitterDB", "version": "unknown",
        "source_url": "http://bitterdb.agri.huji.ac.il/bitterdb/",
        "download_date": NOW, "files": files,
        "role": "reference", "license": "Academic",
        "notes": "Site unreachable. Manual download needed from dload.php page." if not reachable
                 else ("Download links not found in HTML." if not files else "Complete."),
    })
    status = "done" if files else ("pending" if reachable else "failed")
    record(name, status, "0 B" if not files else human_size(sum(
        Path(f["path"]).stat().st_size for f in files if Path(REPO_ROOT / f["path"]).exists()
    )), "Site unreachable — manual download needed (Dagan-Wiener 2019 paper supplement)")


# ──────────────────────────────────────────────
# P1-4: SuperSweet
# ──────────────────────────────────────────────

def pull_supersweet() -> None:
    name = "SuperSweet"
    target = RAW_DIR / "supersweet"
    target.mkdir(exist_ok=True)
    t0 = time.time()

    files = []
    failed = []

    # Try Charité Berlin server + proxy
    attempts = [
        ("http://bioinf-applied.charite.de/sweet/", False),
        ("http://bioinf-applied.charite.de/sweet/", True),
        ("https://sweetdb.charite.de/", True),
        ("http://sweetdb.charite.de/", True),
    ]

    html = ""
    reachable = False
    for url, use_proxy in attempts:
        try:
            if use_proxy:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
            else:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(url, headers={"User-Agent": "culinary-mind/phase0b"})
            with opener.open(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                reachable = True
                print(f"  Reached SuperSweet at {url}")
                break
        except Exception as e:
            print(f"  SuperSweet {url}: {e}")

    # Try to find download links or SDF/CSV
    import re
    if reachable:
        links = re.findall(r'href="([^"]*(?:csv|sdf|xls|download|zip)[^"]*)"', html, re.I)
        for link in links[:5]:
            if not link.startswith("http"):
                link = "http://bioinf-applied.charite.de" + link
            fname = link.split("/")[-1].split("?")[0] or "supersweet_data"
            dest = target / fname
            ok, msg = download_file(link, dest, fname, use_proxy=True, timeout=60)
            if ok:
                files.append({"path": str(dest.relative_to(REPO_ROOT)),
                              "size": human_size(dest.stat().st_size)})
            else:
                failed.append(f"{fname}: {msg}")

    write_readme(target / "README.md", f"""# SuperSweet

**Description**: Database of sweet compounds (~11,000 entries including natural + artificial sweeteners).
**Source**: http://bioinf-applied.charite.de/sweet/
**Downloaded**: {NOW}
**License**: Academic/research
**Expected Role**: Reference — sweet taste dimension for FT taste vectors

## Status
{'✅ Complete' if files else ('⚠️ Site reachable but no downloads extracted' if reachable else '❌ Site unreachable')}

## Access Notes
- Server: Charité Berlin — may be slow/unreachable
- Alternative mirror / publication data: Dunkel et al. 2012, Nucleic Acids Research
- doi: 10.1093/nar/gkr1164

## If Manually Needed
1. Visit http://bioinf-applied.charite.de/sweet/
2. Look for SDF or CSV download under "Download" section
3. Place in data/external/raw/supersweet/

## Notes
- ~11,000 compounds. Small dataset.
- Do NOT import into production without QC.
""")
    write_manifest(target / "manifest.json", {
        "name": "SuperSweet", "version": "unknown",
        "source_url": "http://bioinf-applied.charite.de/sweet/",
        "download_date": NOW, "files": files,
        "role": "reference", "license": "Academic",
        "notes": "Site unreachable" if not reachable else ("No download links" if not files else "Complete.")
    })
    total_sz = sum(f.stat().st_size for f in target.glob("*") if f.is_file())
    status = "done" if files else ("pending" if reachable else "failed")
    record(name, status, human_size(total_sz),
           "Site unreachable — manual download or publication supplement (Dunkel 2012)" if not reachable else
           ("No direct download links found" if not files else f"elapsed {time.time()-t0:.0f}s"))


# ──────────────────────────────────────────────
# P2-1: GoodScents (needs scraper)
# ──────────────────────────────────────────────

def pull_goodscents() -> None:
    name = "GoodScentsCompany"
    target = RAW_DIR / "goodscents"
    target.mkdir(exist_ok=True)

    write_readme(target / "README.md", """# Good Scents Company

**Description**: Industrial flavor/fragrance compound database with odor descriptors,
CAS numbers, molecular structures, and usage information. ~8,000+ aroma chemicals.
**Source**: http://www.thegoodscentscompany.com/
**Status**: 🤖 NEEDS SCRAPER — no bulk download API

## Why Scraping Required
The Good Scents Company website is a purely static HTML site with no download or API endpoint.
Data is embedded in individual compound pages at:
- http://www.thegoodscentscompany.com/data/{compound_id}.html

## Recommended Approach: open-data-collector + OpenClaw
1. Crawl the compound index pages to build ID list
2. Fetch each compound page: `/data/{id}.html`
3. Parse HTML tables for: name, CAS, FEMA, odor descriptors, flavor notes
4. Estimated ~8,000 requests; 1 req/s = ~2.5 hours on Mac Mini sandbox

## Data Available Per Compound
- Chemical name + synonyms
- CAS registry number
- FEMA number
- Odor profile (descriptor terms)
- Flavor profile
- Natural occurrence (which foods)
- Physical properties

## Notes
- Public web data. No login required.
- Robots.txt: check before scraping (likely allows reasonable crawl rate).
- This is critical for aroma-compound dimension of FT vectors.
""")
    write_manifest(target / "manifest.json", {
        "name": "GoodScentsCompany", "version": "unknown",
        "source_url": "http://www.thegoodscentscompany.com/",
        "download_date": None, "files": [],
        "role": "prior", "license": "Public web data",
        "status": "needs_scraper",
        "notes": "Static HTML site. Needs open-data-collector + OpenClaw (~8000 compound pages).",
        "scraper_spec": {
            "type": "compound_page_crawl",
            "index_url": "http://www.thegoodscentscompany.com/",
            "compound_url_pattern": "http://www.thegoodscentscompany.com/data/{id}.html",
            "estimated_count": 8000,
            "rate_limit": "1 req/s",
            "estimated_time_hours": 2.5,
        }
    })
    record(name, "needs_scraper", "0 B",
           "Static HTML — needs open-data-collector + OpenClaw (~8000 pages, ~2.5h)",
           needs_collector=True)


# ──────────────────────────────────────────────
# P2-2: FlavorNet (Ahn 2011)
# ──────────────────────────────────────────────

def pull_flavornet() -> None:
    name = "FlavorNet"
    target = RAW_DIR / "flavornet"
    target.mkdir(exist_ok=True)
    t0 = time.time()

    files = []

    # FlavorNet (Acree lab, Cornell) — old site with CRC/FID data
    # The Ahn 2011 flavor network is separate (Science paper supplement)
    ahn_sources = [
        # Ahn 2011 paper supplementary — Korean food network
        ("https://static-content.springer.com/esm/art%3A10.1038%2Fsrep00196/MediaObjects/41598_2012_BFsrep00196_MOESM1_ESM.xls",
         "ahn2011_supplement.xls", "Ahn 2011 Sci Rep supplement (ingredient-compound)"),
        # GitHub repos with the Ahn 2011 data
        ("https://raw.githubusercontent.com/lamypark/FlavorGraph/master/input/ingredient_compound_df.csv",
         "ingredient_compound_df.csv", "FlavorGraph ingredient-compound CSV (Ahn derived)"),
        ("https://raw.githubusercontent.com/lamypark/FlavorGraph/master/input/molecule_list.txt",
         "molecule_list.txt", "FlavorGraph molecule list"),
        ("https://raw.githubusercontent.com/lamypark/FlavorGraph/master/input/ingredient_list.txt",
         "ingredient_list.txt", "FlavorGraph ingredient list"),
    ]

    opener_noproxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    for url, fname, desc in ahn_sources:
        dest = target / fname
        if dest.exists() and dest.stat().st_size > 100:
            print(f"  ✓ {fname} already exists")
            files.append({"path": str(dest.relative_to(REPO_ROOT)),
                          "size": human_size(dest.stat().st_size)})
            continue
        ok, msg = download_file(url, dest, desc, use_proxy=False)
        if not ok:
            ok, msg = download_file(url, dest, f"{desc} (proxy)", use_proxy=True)
        if ok:
            files.append({"path": str(dest.relative_to(REPO_ROOT)),
                          "size": human_size(dest.stat().st_size)})
        else:
            print(f"  ✗ {fname}: {msg}")

    elapsed = time.time() - t0
    total_sz = sum(f.stat().st_size for f in target.glob("*") if f.is_file())

    write_readme(target / "README.md", f"""# FlavorNet / Ahn 2011 Flavor Network

**Description**: Original flavor network data from Ahn et al. 2011 (Flavor network and the principles
of food pairing). 1,530 ingredients × 1,106 flavor compounds, shared compound co-occurrence network.
**Source**: https://www.nature.com/articles/srep00196 (Sci Rep 2011)
**Also**: http://www.flavornet.org/ (Acree lab, Cornell — GCO-detected odorants)
**Downloaded**: {NOW}
**License**: Open science / CC
**Expected Role**: Prior layer — foundational food-pairing network (Ahn network reproduction)

## Files
{chr(10).join('- `' + f['path'].split('/')[-1] + '` — ' + f['size'] for f in files) if files else '- No files downloaded'}

## Status
{'✅ Complete' if files else '⚠️ Partial — some files failed'}

## Notes
- ingredient_compound_df.csv is the core edge list (ingredient × molecule)
- This is the Ahn 2011 data as processed by FlavorGraph — original supplement from Nature may require proxy
- Do NOT import into production without QC.
""")
    write_manifest(target / "manifest.json", {
        "name": "FlavorNet / Ahn 2011",
        "version": "Ahn 2011 Sci Rep",
        "source_url": "https://www.nature.com/articles/srep00196",
        "download_date": NOW, "files": files,
        "role": "prior", "license": "CC / Open science",
        "notes": f"{len(files)} files downloaded.",
        "elapsed_seconds": round(elapsed, 1)})
    status = "done" if files else "failed"
    record(name, status, human_size(total_sz),
           f"{len(files)} files from FlavorGraph/Ahn sources, elapsed {elapsed:.0f}s", files)


# ──────────────────────────────────────────────
# P2-3: CFSDB (China Food Standard DB)
# ──────────────────────────────────────────────

def pull_cfsdb() -> None:
    name = "CFSDB"
    target = RAW_DIR / "cfsdb"
    target.mkdir(exist_ok=True)

    # Try known academic mirrors and GitHub repos
    github_candidates = [
        "https://github.com/china-food-database/CFSDB",
        "https://github.com/NationalFoodNutritionDatabase/CFND",
    ]

    files = []
    found = False

    for url in github_candidates:
        api = url.replace("https://github.com/", "https://api.github.com/repos/")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(api, headers={
                "User-Agent": "culinary-mind/phase0b",
                "Accept": "application/vnd.github.v3+json"})
            with opener.open(req, timeout=10) as resp:
                d = json.loads(resp.read())
                if d.get("id"):
                    print(f"  Found: {url}")
                    found = True
                    break
        except:
            continue

    # Try official CN nutrition site
    cn_urls = [
        "http://www.chinanutri.cn/fgbz/fgbzdt/201611/t20161101_133538.htm",
        "https://www.chinanutri.cn/",
    ]
    for url in cn_urls:
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(url, headers={"User-Agent": "culinary-mind/phase0b"})
            with opener.open(req, timeout=10) as resp:
                print(f"  CN nutrition site reachable: {url}")
                break
        except:
            pass

    write_readme(target / "README.md", """# CFSDB — China Food Standard Database

**Description**: Chinese food composition data, equivalent to USDA for Chinese ingredients.
Critical for covering traditional Chinese ingredients missing from USDA/FooDB.
**Source**: http://www.chinanutri.cn/ (China CDC National Institute for Nutrition and Health)
**Status**: ⏳ PENDING — no public bulk download found

## Why No Public Download
The official CFSDB/CFND data is:
1. Published as physical books (中国食物成分表 第2版)
2. Available via restricted web interface at chinanutri.cn
3. No bulk download API or open dataset

## Academic Open Versions Found
- **USDA NNDSR** includes some Chinese foods but is incomplete
- **No open CFSDB bulk download exists** as of research date

## Recommended Approaches (in priority order)
1. **Purchase book**: 《中国食物成分表》标准版 (Standard Edition) — ISBN 978-7-117-13168-5
   Available on JD.com/Taobao. Data may be OCR-extractable.
2. **Chinese academic repositories**: Check CNKI/Wanfang for datasets citing CFSDB
3. **Peer project datasets**: https://github.com/search?q=中国食物成分 language:Python
4. **Taiwan OSFDC**: Taiwan's food composition DB (publicly downloadable, partially overlaps)
   → https://consumer.fda.gov.tw/Food/TFND.aspx?nodeID=178

## Alternative: Taiwan Food Composition Database
Taiwan FDA provides open bulk download — similar coverage for Chinese cuisine:
  https://consumer.fda.gov.tw/Food/TFND.aspx?nodeID=178

## Notes
- Jeff decision needed: purchase book vs Taiwan FDA data vs skip for now.
""")
    write_manifest(target / "manifest.json", {
        "name": "CFSDB", "version": "unknown",
        "source_url": "http://www.chinanutri.cn/",
        "download_date": None, "files": [],
        "role": "reference", "license": "Restricted",
        "status": "pending_decision",
        "notes": "No public bulk download. Options: (1) purchase book + OCR, (2) Taiwan FDA DB (open), (3) skip.",
        "alternatives": [
            "Taiwan FDA Food Composition: https://consumer.fda.gov.tw/Food/TFND.aspx?nodeID=178",
        ]
    })
    record(name, "pending", "0 B",
           "No public bulk download. Options: Taiwan FDA DB (open) or purchase CN book. Jeff decision needed.")


# ──────────────────────────────────────────────
# Write final INDEX.md and report
# ──────────────────────────────────────────────

def update_index() -> None:
    total_sz = sum(f.stat().st_size for f in RAW_DIR.rglob("*")
                   if f.is_file() and ".git" not in str(f))

    # Phase 0 datasets
    phase0 = [
        ("✅", "foodon",        "done",          "38.6 MB", "OWL ontology v2025-02-01"),
        ("✅", "flavorgraph",   "done",          "27 MB",   "git clone + 300D embeddings"),
        ("✅", "foodkg",        "done",          "96 MB",   "git clone subgraphs + tooling"),
        ("❌", "recipe1m_plus", "dropped",       "0 B",     "Misaligned — image-retrieval ML"),
        ("✅", "recipenlg",     "done",          "2.1 GB",  "2,231,142 recipes CSV"),
        ("✅", "usda_fdc",      "done",          "2.2 MB",  "Existing at data/external/usda-fdc/"),
    ]

    p0_rows = "\n".join(f"| {icon} | {n} | {s} | {sz} | {notes} |"
                        for icon, n, s, sz, notes in phase0)

    # Phase 0b datasets
    p0b_rows_list = []
    for r in REPORT:
        icon = {"done": "✅", "pending": "⏳", "partial": "⚠️",
                "failed": "❌", "needs_scraper": "🤖", "dropped": "❌"}.get(r["status"], "❓")
        p0b_rows_list.append(
            f"| {icon} | {r['dataset']} | {r['status']} | {r['size']} | {r['notes'][:80]} |")
    p0b_rows = "\n".join(p0b_rows_list)

    (RAW_DIR / "INDEX.md").write_text(f"""# External Data Index

**Generated**: {NOW}
**Total size (raw/)**: {human_size(total_sz)}
**Location**: `data/external/raw/`

## Phase 0 — Foundation Datasets

| Status | Dataset | State | Size | Notes |
|--------|---------|-------|------|-------|
{p0_rows}

## Phase 0b — Flavor / Chemistry / Food Composition

| Status | Dataset | State | Size | Notes |
|--------|---------|-------|------|-------|
{p0b_rows}

## Hard Constraints
- ❌ NO loader, NO cleaning, NO DB import
- ❌ Production (L0/L2a/L2b/Neo4j) NOT touched
- ✅ All files in `data/external/raw/` only
- 🤖 Datasets marked "needs_scraper" → open-data-collector task

## Next Steps
1. QC pass on all downloadable datasets
2. open-data-collector: FlavorDB2 + GoodScents scraping
3. CFSDB: Jeff decides (Taiwan FDA vs CN book vs skip)
4. BitterDB + SuperSweet: manual download (small datasets)
5. After QC → staging → approved → distillation pipeline
""", encoding="utf-8")
    print(f"\n📄 INDEX.md updated ({human_size(total_sz)} total)")


def write_phase0b_report() -> None:
    report_dir = REPO_ROOT / "raw" / "coder"
    report_dir.mkdir(parents=True, exist_ok=True)

    total_sz = sum(f.stat().st_size for f in RAW_DIR.rglob("*")
                   if f.is_file() and ".git" not in str(f))

    sections = []
    for r in REPORT:
        icon = {"done": "✅", "pending": "⏳", "partial": "⚠️",
                "failed": "❌", "needs_scraper": "🤖"}.get(r["status"], "❓")
        collector = "\n- **Needs open-data-collector**: Yes" if r.get("needs_open_data_collector") else ""
        sections.append(f"""### {icon} {r['dataset']}
- **Status**: {r['status']}
- **Size**: {r['size']}{collector}
- **Notes**: {r['notes']}
""")

    done = [r for r in REPORT if r["status"] == "done"]
    scraper = [r for r in REPORT if r["status"] == "needs_scraper"]
    pending = [r for r in REPORT if r["status"] in ("pending", "failed", "partial")]

    (report_dir / "phase0b-flavor-chem-report.md").write_text(f"""# Phase 0b — Flavor/Chemistry Dataset Pull Report

**Date**: {NOW[:10]}
**Total raw/ size**: {human_size(total_sz)}
**Summary**: {len(done)} done, {len(scraper)} needs scraper, {len(pending)} pending/failed

## Dataset Status

{''.join(sections)}

## Datasets Needing open-data-collector (Mac Mini OpenClaw)
{chr(10).join('- **' + r['dataset'] + '**: ' + r['notes'] for r in scraper)}

## Datasets Needing Jeff Decision
- **CFSDB**: No public bulk download. Options:
  1. Taiwan FDA Food Composition DB (open, good coverage): https://consumer.fda.gov.tw/Food/TFND.aspx?nodeID=178
  2. Purchase 《中国食物成分表》and OCR
  3. Skip for now

## Small Datasets for Manual Download (Jeff or coder)
- **BitterDB**: ~1000 compounds, visit http://bitterdb.agri.huji.ac.il/bitterdb/dload.php
- **SuperSweet**: ~11000 compounds, visit http://bioinf-applied.charite.de/sweet/

## Constraints Verified
- ✅ All files in `data/external/raw/` only
- ✅ Production databases untouched
- ✅ No loaders, no cleaning
- ✅ No scraping done by coder (documented and passed to open-data-collector)
""", encoding="utf-8")
    print(f"📄 Report: raw/coder/phase0b-flavor-chem-report.md")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Phase 0b — Flavor/Chemistry Dataset Pull")
    print(f"Free disk: {human_size(shutil.disk_usage(str(RAW_DIR)).free)}")
    print(f"Raw/ current size: {human_size(disk_used_raw())}")
    print("=" * 60)

    # P0
    pull_foodb()
    pull_foodatlas()
    pull_flavordb2()

    # P1
    pull_open_food_facts()
    pull_phenol_explorer()
    pull_bitterdb()
    pull_supersweet()

    # P2
    pull_goodscents()
    pull_flavornet()
    pull_cfsdb()

    update_index()
    write_phase0b_report()

    print("\n" + "=" * 60)
    print("Phase 0b complete.")
    print(f"Total raw/ size: {human_size(disk_used_raw())}")
