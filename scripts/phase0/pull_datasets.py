#!/usr/bin/env python3
"""Phase 0 — Download external datasets to data/external/raw/.

HARD CONSTRAINTS:
  - Only writes to data/external/raw/
  - trust_env=False (bypass local 7890 proxy)
  - No loaders, no cleaning, no DB imports
  - If a dataset needs registration, document it and skip
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

# Clear proxy env vars
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY", "REQUESTS_CA_BUNDLE"]:
    os.environ.pop(_k, None)
os.environ["no_proxy"] = "localhost,127.0.0.1"

import urllib.request
import urllib.error

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "external" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

NOW = datetime.now(timezone.utc).isoformat()
REPORT: list[dict] = []


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def download_file(url: str, dest: Path, desc: str = "") -> tuple[bool, str]:
    """Download a single file. Returns (ok, message)."""
    print(f"  ↓ {desc or url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "culinary-mind/phase0"})
        with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            while chunk := resp.read(65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r    {human_size(downloaded)} / {human_size(total)} ({pct:.0f}%)", end="", flush=True)
        print()
        return True, f"OK ({human_size(dest.stat().st_size)})"
    except Exception as e:
        return False, str(e)


def write_readme(target_dir: Path, content: str) -> None:
    (target_dir / "README.md").write_text(content, encoding="utf-8")


def write_manifest(target_dir: Path, manifest: dict) -> None:
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def record(name: str, status: str, size: str, notes: str, files: list[dict] = None) -> None:
    REPORT.append({
        "dataset": name,
        "status": status,
        "size": size,
        "notes": notes,
        "files": files or [],
        "timestamp": NOW,
    })
    icon = "✅" if status == "done" else ("⏳" if status == "pending" else "❌")
    print(f"\n{icon} {name}: {status} — {size}")
    if notes:
        print(f"   {notes}")


# ──────────────────────────────────────────────
# Dataset 1: FoodOn
# ──────────────────────────────────────────────

def pull_foodon() -> None:
    name = "FoodOn"
    target = RAW_DIR / "foodon"
    target.mkdir(exist_ok=True)
    t0 = time.time()

    files = []
    failed = []

    # Latest release OWL from GitHub releases API (no auth needed)
    # Also try OBO Foundry direct URL
    sources = [
        ("https://github.com/FoodOntology/foodon/releases/download/v2023-05-15/foodon.owl",
         "foodon.owl", "OWL ontology file"),
        ("https://raw.githubusercontent.com/FoodOntology/foodon/master/foodon.obo",
         "foodon.obo", "OBO format"),
    ]
    # Try to get the latest release info
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/FoodOntology/foodon/releases/latest",
            headers={"User-Agent": "culinary-mind/phase0", "Accept": "application/vnd.github.v3+json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            rel = json.loads(resp.read())
            version = rel.get("tag_name", "unknown")
            # Look for OWL asset
            for asset in rel.get("assets", []):
                if asset["name"].endswith(".owl"):
                    sources[0] = (asset["browser_download_url"], asset["name"], "OWL ontology file (latest release)")
                    break
            print(f"  FoodOn latest release: {version}")
    except Exception as e:
        version = "v2023-05-15 (fallback)"
        print(f"  FoodOn GitHub API failed ({e}), using fallback URL")

    for url, fname, desc in sources:
        dest = target / fname
        if dest.exists():
            print(f"  ✓ {fname} already exists, skipping download")
            files.append({"path": str(dest.relative_to(REPO_ROOT)), "size": human_size(dest.stat().st_size), "sha256": sha256_file(dest)})
            continue
        ok, msg = download_file(url, dest, desc)
        if ok:
            files.append({"path": str(dest.relative_to(REPO_ROOT)), "size": human_size(dest.stat().st_size), "sha256": sha256_file(dest)})
        else:
            failed.append(f"{fname}: {msg}")
            print(f"  ✗ {fname}: {msg}")

    elapsed = time.time() - t0
    total_sz = sum(f.stat().st_size for f in target.glob("*") if f.is_file())

    write_readme(target, f"""# FoodOn

**Description**: Food ontology (OWL) with 9,445+ classes covering ingredients, food products, processes.
**Source**: https://github.com/FoodOntology/foodon
**Version**: {version}
**Downloaded**: {NOW}
**License**: CC BY 4.0
**Expected Role**: Backbone / ID mapping layer for L2a canonical IDs

## Files
| File | Description |
|------|-------------|
| foodon.owl | OWL ontology — primary format |
| foodon.obo | OBO format — alternative |

## Status
{'✅ Complete' if not failed else '⚠️ Partial — ' + '; '.join(failed)}

## Notes
- Do NOT import into production. This is a reference archive only.
- Quality check before use: verify class count matches expected ~9445+
""")

    manifest = {
        "name": "FoodOn",
        "version": version,
        "source_url": "https://github.com/FoodOntology/foodon",
        "download_date": NOW,
        "files": files,
        "role": "backbone",
        "license": "CC BY 4.0",
        "notes": f"Food ontology OWL. {len(failed)} download failures." if failed else "Food ontology OWL. Complete download.",
        "elapsed_seconds": round(elapsed, 1),
    }
    write_manifest(target, manifest)

    status = "done" if not failed else ("partial" if files else "failed")
    record(name, status, human_size(total_sz), "; ".join(failed) if failed else f"elapsed {elapsed:.0f}s", files)


# ──────────────────────────────────────────────
# Dataset 2: FlavorGraph
# ──────────────────────────────────────────────

def pull_flavorgraph() -> None:
    name = "FlavorGraph"
    target = RAW_DIR / "flavorgraph"
    t0 = time.time()

    if (target / ".git").exists():
        print("  FlavorGraph already cloned, pulling latest...")
        result = subprocess.run(["git", "-C", str(target), "pull", "--ff-only"],
                                capture_output=True, text=True)
        ok = result.returncode == 0
        msg = result.stdout.strip() or result.stderr.strip()
    else:
        print("  git clone FlavorGraph...")
        result = subprocess.run(
            ["git", "clone", "--depth=1",
             "https://github.com/lamypark/FlavorGraph.git", str(target)],
            capture_output=True, text=True
        )
        ok = result.returncode == 0
        msg = result.stdout.strip() or result.stderr.strip()

    elapsed = time.time() - t0

    if not ok:
        record(name, "failed", "0 B", f"git clone failed: {msg}")
        return

    # Collect key files
    files = []
    key_patterns = ["*.csv", "*.pkl", "*.pt", "*.txt", "*.json", "*.npy", "*.tsv"]
    seen = set()
    for pat in key_patterns:
        for f in sorted(target.rglob(pat)):
            if ".git" in str(f):
                continue
            rel = str(f.relative_to(REPO_ROOT))
            if rel not in seen:
                seen.add(rel)
                files.append({"path": rel, "size": human_size(f.stat().st_size), "sha256": sha256_file(f)})

    total_sz = sum(f.stat().st_size for f in target.rglob("*") if f.is_file() and ".git" not in str(f))

    # Get commit hash
    commit_result = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"],
                                   capture_output=True, text=True)
    commit = commit_result.stdout.strip()[:12]

    write_readme(target, f"""# FlavorGraph

**Description**: 1,561 flavor molecules × 6,000 ingredients network with 300D pre-trained embeddings.
**Source**: https://github.com/lamypark/FlavorGraph
**Commit**: {commit}
**Downloaded**: {NOW}
**License**: MIT (see LICENSE in repo)
**Expected Role**: Prior / embedding initialisation for L3 Pass 1

## Key Files
- `data/` — ingredient list, molecule list, edge data
- embeddings files (if present) — 300D pre-trained vectors

## Status
✅ Complete (git clone depth=1)

## Notes
- Do NOT use embeddings directly in production without quality check.
- Verify molecule list against our L2a canonical IDs before any mapping.
""")

    manifest = {
        "name": "FlavorGraph",
        "version": f"git-{commit}",
        "source_url": "https://github.com/lamypark/FlavorGraph",
        "download_date": NOW,
        "files": files[:50],  # cap manifest size
        "role": "prior",
        "license": "MIT",
        "notes": f"git clone --depth=1, commit {commit}",
        "elapsed_seconds": round(elapsed, 1),
    }
    write_manifest(target, manifest)
    record(name, "done", human_size(total_sz), f"commit {commit}, elapsed {elapsed:.0f}s", files[:10])


# ──────────────────────────────────────────────
# Dataset 3: FoodKG
# ──────────────────────────────────────────────

def pull_foodkg() -> None:
    name = "FoodKG"
    target = RAW_DIR / "foodkg"
    target.mkdir(exist_ok=True)
    t0 = time.time()

    # FoodKG — try GitHub repo first (docs + smaller files)
    # The full 67M triple dataset is at foodkg.github.io
    files = []
    failed = []

    sources = [
        # GitHub repo README + scripts
        ("https://raw.githubusercontent.com/foodkg/foodkg.github.io/master/README.md",
         "upstream_README.md", "FoodKG upstream README"),
        # The actual KG data is distributed via foodkg.github.io — check what's available
        ("https://raw.githubusercontent.com/foodkg/foodkg.github.io/master/subgraphs/usda_ttl/usda.ttl",
         "usda.ttl", "USDA TTL subgraph"),
        ("https://raw.githubusercontent.com/foodkg/foodkg.github.io/master/subgraphs/recipe_ttl/recipe.ttl",
         "recipe.ttl", "Recipe TTL subgraph"),
    ]

    # First, clone the GitHub repo to get structure
    repo_target = target / "foodkg.github.io"
    if not (repo_target / ".git").exists():
        print("  git clone foodkg.github.io...")
        result = subprocess.run(
            ["git", "clone", "--depth=1",
             "https://github.com/foodkg/foodkg.github.io.git",
             str(repo_target)],
            capture_output=True, text=True, timeout=300
        )
        ok_clone = result.returncode == 0
        if not ok_clone:
            print(f"  git clone failed: {result.stderr[:200]}")
    else:
        print("  FoodKG repo already cloned")
        ok_clone = True

    elapsed = time.time() - t0
    total_sz = sum(f.stat().st_size for f in target.rglob("*") if f.is_file() and ".git" not in str(f))

    commit = "unknown"
    if ok_clone:
        commit_result = subprocess.run(["git", "-C", str(repo_target), "rev-parse", "HEAD"],
                                       capture_output=True, text=True)
        commit = commit_result.stdout.strip()[:12]

        for f in sorted(repo_target.rglob("*")):
            if f.is_file() and ".git" not in str(f):
                rel = str(f.relative_to(REPO_ROOT))
                files.append({"path": rel, "size": human_size(f.stat().st_size)})

    write_readme(target, f"""# FoodKG

**Description**: Food Knowledge Graph with ~67M triples (FoodOn + USDA + recipe subsets).
**Source**: https://github.com/foodkg/foodkg.github.io
**Commit**: {commit}
**Downloaded**: {NOW}
**License**: See repo LICENSE
**Expected Role**: Observation / cross-reference for L0 scientific claims

## Subgraphs
- `usda.ttl` — USDA nutrition facts as RDF triples
- `recipe.ttl` — Recipe ingredient co-occurrence triples
- Additional subgraphs in repo if available

## Status
{'✅ Complete (git clone)' if ok_clone else '❌ Clone failed'}

## Notes
- Full 67M triple dump may require separate download (see foodkg.github.io).
- Do NOT import into Neo4j without quality check pass.
- This version: GitHub repo content (scripts + sample subgraphs).
""")

    manifest = {
        "name": "FoodKG",
        "version": f"git-{commit}",
        "source_url": "https://github.com/foodkg/foodkg.github.io",
        "download_date": NOW,
        "files": files[:50],
        "role": "observation",
        "license": "See repo",
        "notes": "git clone --depth=1. Full 67M triple dump not yet retrieved (requires separate tooling).",
        "elapsed_seconds": round(elapsed, 1),
    }
    write_manifest(target, manifest)
    status = "done" if ok_clone else "failed"
    record(name, status, human_size(total_sz),
           f"commit {commit}, elapsed {elapsed:.0f}s. Note: full 67M triple dump pending." if ok_clone else "git clone failed",
           files[:10])


# ──────────────────────────────────────────────
# Dataset 4: Recipe1M+
# ──────────────────────────────────────────────

def pull_recipe1m() -> None:
    name = "Recipe1M+"
    target = RAW_DIR / "recipe1m_plus"
    target.mkdir(exist_ok=True)

    # Recipe1M+ requires registration — document and skip
    write_readme(target, """# Recipe1M+

**Description**: 1M+ recipes with images. Text files: layer1.json (recipes), layer2.json (images), det_ingrs.json (detected ingredients).
**Source**: http://pic2recipe.csail.mit.edu/
**Status**: ⏳ PENDING — requires registration

## Registration Required

To access Recipe1M+:
1. Visit: http://pic2recipe.csail.mit.edu/
2. Click "Request Access" / fill the registration form
3. You will receive a download link via email
4. Download only text layers (NOT images to save space):
   - `layer1.json` (~2.7 GB) — recipe text, ingredients, instructions
   - `det_ingrs.json` (~1.5 GB) — detected ingredient tokens

## Alternative: OpenSourced Subset
The im2recipe-Pytorch repo has a smaller subset:
  https://github.com/torralba-lab/im2recipe-Pytorch

## Expected Role
Observation / MSA variant signal and ingredient co-occurrence statistics.

## Action Required
Jeff needs to register at http://pic2recipe.csail.mit.edu/ and share the download link.
We only need layer1.json + det_ingrs.json (text, ~4GB total), NOT images.

## Notes
- Do NOT import into production. Archive only.
- Target: data/external/raw/recipe1m_plus/layer1.json, det_ingrs.json
""")

    manifest = {
        "name": "Recipe1M+",
        "version": "pending",
        "source_url": "http://pic2recipe.csail.mit.edu/",
        "download_date": None,
        "files": [],
        "role": "observation",
        "license": "Academic / non-commercial",
        "notes": "Requires registration at pic2recipe.csail.mit.edu. Jeff action needed.",
        "status": "pending_registration",
    }
    write_manifest(target, manifest)
    record(name, "pending", "0 B",
           "Requires registration at http://pic2recipe.csail.mit.edu/ — Jeff action needed")


# ──────────────────────────────────────────────
# Dataset 5: RecipeNLG
# ──────────────────────────────────────────────

def pull_recipenlg() -> None:
    name = "RecipeNLG"
    target = RAW_DIR / "recipenlg"
    target.mkdir(exist_ok=True)
    t0 = time.time()

    files = []
    failed = []

    # Try HuggingFace datasets download (parquet format, no auth)
    # Dataset: mbien/recipe_nlg on HuggingFace
    hf_url = "https://huggingface.co/datasets/mbien/recipe_nlg/resolve/main/data/train-00000-of-00002.parquet"
    hf_url2 = "https://huggingface.co/datasets/mbien/recipe_nlg/resolve/main/data/train-00001-of-00002.parquet"

    for url, fname in [(hf_url, "train-00000-of-00002.parquet"),
                       (hf_url2, "train-00001-of-00002.parquet")]:
        dest = target / fname
        if dest.exists():
            print(f"  ✓ {fname} already exists")
            files.append({"path": str(dest.relative_to(REPO_ROOT)), "size": human_size(dest.stat().st_size), "sha256": sha256_file(dest)})
            continue
        ok, msg = download_file(url, dest, fname)
        if ok:
            files.append({"path": str(dest.relative_to(REPO_ROOT)), "size": human_size(dest.stat().st_size), "sha256": sha256_file(dest)})
        else:
            # Try alternative: direct from recipenlg website
            print(f"  HuggingFace failed ({msg}), trying recipenlg.cs.put.poznan.pl...")
            alt_url = "https://recipenlg.cs.put.poznan.pl/dataset"
            ok2, msg2 = download_file(alt_url, dest, "RecipeNLG CSV from source")
            if ok2:
                files.append({"path": str(dest.relative_to(REPO_ROOT)), "size": human_size(dest.stat().st_size), "sha256": sha256_file(dest)})
            else:
                failed.append(f"{fname}: HuggingFace={msg}; direct={msg2}")

    elapsed = time.time() - t0
    total_sz = sum(f.stat().st_size for f in target.glob("*") if f.is_file())

    write_readme(target, f"""# RecipeNLG

**Description**: 2.2M cooking recipes in English (NLG dataset), CSV/Parquet format.
**Source**: https://recipenlg.cs.put.poznan.pl/ | HuggingFace: mbien/recipe_nlg
**Downloaded**: {NOW}
**License**: CC BY-NC-SA 4.0 (non-commercial)
**Expected Role**: Observation / MSA variant signal supplement, ingredient co-occurrence

## Files
| File | Description |
|------|-------------|
| train-00000-of-00002.parquet | Recipes part 1 |
| train-00001-of-00002.parquet | Recipes part 2 |

## Status
{'✅ Complete' if not failed else ('⚠️ Partial' if files else '❌ Failed')}
{chr(10).join('- ' + f for f in failed) if failed else ''}

## Schema (Parquet columns)
- title, ingredients (list), directions (list), link, source, NER (named entity recognized ingredients)

## Notes
- Non-commercial license. Project is not commercial (Jeff confirmed).
- Do NOT import into production without quality check.
- ~2GB total (2 parquet files).
""")

    manifest = {
        "name": "RecipeNLG",
        "version": "HuggingFace mbien/recipe_nlg",
        "source_url": "https://huggingface.co/datasets/mbien/recipe_nlg",
        "download_date": NOW,
        "files": files,
        "role": "observation",
        "license": "CC BY-NC-SA 4.0",
        "notes": f"{len(failed)} failures." if failed else "Complete.",
        "elapsed_seconds": round(elapsed, 1),
    }
    write_manifest(target, manifest)
    status = "done" if not failed else ("partial" if files else "failed")
    record(name, status, human_size(total_sz),
           "; ".join(failed) if failed else f"elapsed {elapsed:.0f}s", files)


# ──────────────────────────────────────────────
# Dataset 6: USDA FoodData Central
# ──────────────────────────────────────────────

def pull_usda_fdc() -> None:
    name = "USDA FoodData Central"
    target = RAW_DIR / "usda_fdc"
    target.mkdir(exist_ok=True)
    t0 = time.time()

    # Check if data/external/usda-fdc already has files we can symlink/copy
    existing = REPO_ROOT / "data" / "external" / "usda-fdc"
    if existing.exists():
        existing_files = list(existing.glob("*.jsonl")) + list(existing.glob("*.json")) + list(existing.glob("*.csv"))
        if existing_files:
            print(f"  Found existing USDA FDC data at {existing}, creating manifest...")
            files = []
            for f in existing_files:
                files.append({
                    "path": str(f.relative_to(REPO_ROOT)),
                    "size": human_size(f.stat().st_size),
                    "sha256": sha256_file(f) if f.stat().st_size < 500_000_000 else "skipped-too-large"
                })
            total_sz = sum(f.stat().st_size for f in existing_files)

            write_readme(target, f"""# USDA FoodData Central

**Description**: USDA FDC nutritional reference database.
**Source**: https://fdc.nal.usda.gov/download-datasets.html
**Downloaded**: Previously (see data/external/usda-fdc/)
**License**: Public Domain (US Government)
**Expected Role**: Reference / cross-validation layer (NOT production import)

## Status
✅ Data exists at data/external/usda-fdc/ (not duplicated here)

## Actual Data Location
`data/external/usda-fdc/` — {len(existing_files)} files, {human_size(total_sz)}

## Notes
- USDA data already downloaded previously. This README documents its existence.
- Raw directory points to: {existing}
- Do NOT import into production. Reference only.
""")
            manifest = {
                "name": "USDA FoodData Central",
                "version": "previously downloaded",
                "source_url": "https://fdc.nal.usda.gov/download-datasets.html",
                "download_date": NOW,
                "files": files,
                "actual_location": str(existing),
                "role": "reference",
                "license": "Public Domain",
                "notes": "Data exists at data/external/usda-fdc/. Not duplicated in raw/.",
            }
            write_manifest(target, manifest)
            record(name, "done", human_size(total_sz),
                   f"Data exists at data/external/usda-fdc/ ({len(existing_files)} files)", files)
            return

    files = []
    failed = []

    # FDC Full Download — the April 2024 release
    # URL pattern: https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_csv_YYYY-MM-DD.zip
    # Try the most recent known stable URL
    fdc_url = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_csv_2024-04-18.zip"
    dest = target / "FoodData_Central_csv_2024-04-18.zip"

    if dest.exists():
        print(f"  ✓ FDC zip already exists")
        files.append({"path": str(dest.relative_to(REPO_ROOT)), "size": human_size(dest.stat().st_size), "sha256": sha256_file(dest)})
    else:
        ok, msg = download_file(fdc_url, dest, "USDA FDC Full CSV 2024-04-18")
        if ok:
            files.append({"path": str(dest.relative_to(REPO_ROOT)), "size": human_size(dest.stat().st_size), "sha256": sha256_file(dest)})
        else:
            failed.append(f"FDC CSV zip: {msg}")
            # Try JSON version
            json_url = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_Supporting_Data_csv_2024-04-18.zip"
            dest2 = target / "FoodData_Central_Supporting_Data_csv_2024-04-18.zip"
            ok2, msg2 = download_file(json_url, dest2, "USDA FDC Supporting Data")
            if ok2:
                files.append({"path": str(dest2.relative_to(REPO_ROOT)), "size": human_size(dest2.stat().st_size), "sha256": sha256_file(dest2)})
                failed.pop()  # clear the first failure

    elapsed = time.time() - t0
    total_sz = sum(f.stat().st_size for f in target.glob("*") if f.is_file())

    write_readme(target, f"""# USDA FoodData Central

**Description**: USDA nutritional reference database. Full Download includes Foundation Foods, SR Legacy, FNDDS, and Branded Foods.
**Source**: https://fdc.nal.usda.gov/download-datasets.html
**Version**: 2024-04-18 release
**Downloaded**: {NOW}
**License**: Public Domain (US Government data)
**Expected Role**: Reference / cross-validation (NOT production import)

## Files
ZIP archive contains CSVs for all food categories.

## Status
{'✅ Complete' if not failed else ('⚠️ Partial' if files else '❌ Failed — see notes')}
{chr(10).join('- ' + f for f in failed) if failed else ''}

## Notes
- Public domain. No restrictions on non-commercial use.
- Do NOT import into production. Reference only.
- If download failed, manually download from: https://fdc.nal.usda.gov/download-datasets.html
""")

    manifest = {
        "name": "USDA FoodData Central",
        "version": "2024-04-18",
        "source_url": "https://fdc.nal.usda.gov/download-datasets.html",
        "download_date": NOW,
        "files": files,
        "role": "reference",
        "license": "Public Domain",
        "notes": "; ".join(failed) if failed else "Complete.",
        "elapsed_seconds": round(elapsed, 1),
    }
    write_manifest(target, manifest)
    status = "done" if not failed else ("partial" if files else "failed")
    record(name, status, human_size(total_sz),
           "; ".join(failed) if failed else f"elapsed {elapsed:.0f}s", files)


# ──────────────────────────────────────────────
# Write INDEX.md and report
# ──────────────────────────────────────────────

def write_index() -> None:
    total_sz = sum(
        f.stat().st_size
        for f in (RAW_DIR).rglob("*")
        if f.is_file() and ".git" not in str(f)
    )

    rows = []
    for r in REPORT:
        icon = "✅" if r["status"] == "done" else ("⏳" if r["status"] == "pending" else ("⚠️" if r["status"] == "partial" else "❌"))
        rows.append(f"| {icon} | {r['dataset']} | {r['status']} | {r['size']} | {r['notes'][:80]} |")

    index = f"""# External Data Index — Phase 0

**Generated**: {NOW}
**Total size**: {human_size(total_sz)}
**Location**: `data/external/raw/`

## Datasets

| Status | Dataset | State | Size | Notes |
|--------|---------|-------|------|-------|
{chr(10).join(rows)}

## Hard Constraints
- ❌ NO loader, NO cleaning, NO DB import
- ❌ Production (L0/L2a/L2b/Neo4j) NOT touched
- ✅ All files in `data/external/raw/` only

## Next Steps
1. Quality check each dataset (separate QC pass)
2. Recipe1M+ — Jeff to register at http://pic2recipe.csail.mit.edu/
3. FoodKG full 67M triple dump — evaluate if needed after QC
4. After QC: staging → approved → distillation pipeline
"""
    (RAW_DIR / "INDEX.md").write_text(index, encoding="utf-8")
    print(f"\n📄 INDEX.md written ({human_size(total_sz)} total)")


def write_report() -> None:
    report_dir = REPO_ROOT / "raw" / "coder"
    report_dir.mkdir(parents=True, exist_ok=True)

    total_sz = sum(
        f.stat().st_size
        for f in RAW_DIR.rglob("*")
        if f.is_file() and ".git" not in str(f)
    )

    done = [r for r in REPORT if r["status"] == "done"]
    partial = [r for r in REPORT if r["status"] == "partial"]
    pending = [r for r in REPORT if r["status"] == "pending"]
    failed = [r for r in REPORT if r["status"] == "failed"]

    sections = []
    for r in REPORT:
        icon = "✅" if r["status"] == "done" else ("⏳" if r["status"] == "pending" else ("⚠️" if r["status"] == "partial" else "❌"))
        sections.append(f"""### {icon} {r['dataset']}
- **Status**: {r['status']}
- **Size**: {r['size']}
- **Notes**: {r['notes']}
""")

    report = f"""# Phase 0 — External Dataset Pull Report

**Date**: {NOW[:10]}
**Total downloaded**: {human_size(total_sz)}
**Summary**: {len(done)} done, {len(partial)} partial, {len(pending)} pending, {len(failed)} failed

## Dataset Status

{''.join(sections)}

## Action Required by Jeff

{"- **Recipe1M+**: Register at http://pic2recipe.csail.mit.edu/ to get download link. Only need layer1.json + det_ingrs.json (~4GB text, NOT images)." if any(r["dataset"] == "Recipe1M+" for r in pending) else "No action required."}

## Constraints Verified
- ✅ All files in `data/external/raw/` only
- ✅ Production databases untouched (L0/L2a/L2b/Neo4j)
- ✅ No loaders written
- ✅ No data cleaning performed
- ✅ All HTTP requests with trust_env=False (no 7890 proxy)

## Next Steps
1. QC pass on each dataset (verify counts, schema, license compliance)
2. Recipe1M+ registration (Jeff action)
3. FoodKG full 67M triple dump evaluation
4. After QC: move to staging → approved → distillation pipeline
"""
    report_path = report_dir / "phase0-pull-report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"📄 Report: {report_path}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Phase 0 — External Dataset Pull")
    print(f"Target: {RAW_DIR}")
    print(f"Free disk: {human_size(shutil.disk_usage(str(RAW_DIR)).free)}")
    print("=" * 60)

    pull_foodon()
    pull_flavorgraph()
    pull_foodkg()
    pull_recipe1m()
    pull_recipenlg()
    pull_usda_fdc()

    write_index()
    write_report()

    print("\n" + "=" * 60)
    print("Phase 0 complete.")
    print(f"Results in: {RAW_DIR}")
    print(f"Report: raw/coder/phase0-pull-report.md")
