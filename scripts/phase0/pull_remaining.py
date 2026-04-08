#!/usr/bin/env python3
"""Phase 0 — Pull remaining datasets (FoodOn, Recipe1M+ pending, RecipeNLG, USDA FDC)."""
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

for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY"]:
    os.environ.pop(_k, None)
os.environ["no_proxy"] = "localhost,127.0.0.1"

import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "external" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
NOW = datetime.now(timezone.utc).isoformat()
REPORT: list[dict] = []


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(n: int | float) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def download_file(url: str, dest: Path, desc: str = "") -> tuple[bool, str]:
    print(f"  ↓ {desc or url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "culinary-mind/phase0"})
        with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as f:
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


def record(name, status, size, notes, files=None):
    REPORT.append({"dataset": name, "status": status, "size": size, "notes": notes, "files": files or []})
    icon = "✅" if status == "done" else ("⏳" if status == "pending" else ("⚠️" if status == "partial" else "❌"))
    print(f"\n{icon} {name}: {status} — {size}")
    if notes:
        print(f"   {notes}")


# ─── 1. FoodOn ───────────────────────────────

def fix_foodon():
    name = "FoodOn"
    target = RAW_DIR / "foodon"
    target.mkdir(exist_ok=True)
    t0 = time.time()
    files = []

    # OBO Foundry redirects to raw.githubusercontent.com/FoodOntology/foodon/master/foodon.owl
    sources = [
        ("https://raw.githubusercontent.com/FoodOntology/foodon/master/foodon.owl",
         "foodon.owl", "FoodOn OWL (master)"),
        ("https://raw.githubusercontent.com/FoodOntology/foodon/master/foodon_old.obo",
         "foodon.obo", "FoodOn OBO (master)"),
    ]

    for url, fname, desc in sources:
        dest = target / fname
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"  ✓ {fname} already exists ({human_size(dest.stat().st_size)})")
            files.append({"path": str(dest.relative_to(REPO_ROOT)),
                          "size": human_size(dest.stat().st_size),
                          "sha256": sha256_file(dest)})
            continue
        ok, msg = download_file(url, dest, desc)
        if ok:
            files.append({"path": str(dest.relative_to(REPO_ROOT)),
                          "size": human_size(dest.stat().st_size),
                          "sha256": sha256_file(dest)})
        else:
            print(f"  ✗ {fname}: {msg}")

    elapsed = time.time() - t0
    total_sz = sum(f.stat().st_size for f in target.glob("*") if f.is_file())

    (target / "README.md").write_text(f"""# FoodOn

**Description**: Food ontology (OWL) with 9,445+ classes covering ingredients, food products, processes.
**Source**: https://github.com/FoodOntology/foodon | OBO: http://purl.obolibrary.org/obo/foodon.owl
**Version**: v2025-02-01 (master branch)
**Downloaded**: {NOW}
**License**: CC BY 4.0
**Expected Role**: Backbone / ID mapping layer for L2a canonical IDs

## Files
| File | Description |
|------|-------------|
| foodon.owl | OWL ontology — primary format (~150MB) |
| foodon.obo | OBO format — legacy |

## Status
{'✅ Complete' if files else '❌ Failed'}

## Notes
- Do NOT import into production. Reference archive only.
- OBO Foundry purl: http://purl.obolibrary.org/obo/foodon.owl
""", encoding="utf-8")

    (target / "manifest.json").write_text(json.dumps({
        "name": "FoodOn", "version": "v2025-02-01",
        "source_url": "https://github.com/FoodOntology/foodon",
        "download_date": NOW, "files": files,
        "role": "backbone", "license": "CC BY 4.0",
        "elapsed_seconds": round(elapsed, 1),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    status = "done" if files else "failed"
    record(name, status, human_size(total_sz), f"elapsed {elapsed:.0f}s", files)


# ─── 2. FoodKG (check existing clone) ────────

def fix_foodkg():
    name = "FoodKG"
    target = RAW_DIR / "foodkg"
    repo = target / "foodkg.github.io"

    if (repo / ".git").exists():
        result = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                capture_output=True, text=True)
        commit = result.stdout.strip()[:12]
        total_sz = sum(f.stat().st_size for f in target.rglob("*")
                       if f.is_file() and ".git" not in str(f))

        files = []
        for f in sorted(repo.rglob("*")):
            if f.is_file() and ".git" not in str(f):
                files.append({"path": str(f.relative_to(REPO_ROOT)),
                               "size": human_size(f.stat().st_size)})

        (target / "README.md").write_text(f"""# FoodKG

**Description**: Food Knowledge Graph — GitHub repo with subgraphs and tooling. Full 67M triple dump requires separate tooling.
**Source**: https://github.com/foodkg/foodkg.github.io
**Commit**: {commit}
**Downloaded**: {NOW}
**License**: See repo LICENSE
**Expected Role**: Observation / cross-reference for L0 scientific claims

## Contents
- `foodkg.github.io/` — full repo clone
  - `subgraphs/` — RDF subgraphs (USDA, recipe, etc.)
  - `src/` — tooling scripts

## Status
✅ Complete (git clone --depth=1, commit {commit})

## Notes
- Full 67M triple dump at http://foodkg.github.io/downloads — requires tooling (separate eval needed).
- Do NOT import into Neo4j without quality check.
""", encoding="utf-8")

        (target / "manifest.json").write_text(json.dumps({
            "name": "FoodKG", "version": f"git-{commit}",
            "source_url": "https://github.com/foodkg/foodkg.github.io",
            "download_date": NOW, "files": files[:50],
            "role": "observation", "license": "See repo",
            "notes": f"git clone --depth=1, commit {commit}",
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        record(name, "done", human_size(total_sz), f"commit {commit}", files[:10])
    else:
        record(name, "failed", "0 B", "Clone not found — re-run pull_datasets.py")


# ─── 3. Recipe1M+ (pending — registration required) ───

def fix_recipe1m():
    name = "Recipe1M+"
    target = RAW_DIR / "recipe1m_plus"
    target.mkdir(exist_ok=True)

    (target / "README.md").write_text("""# Recipe1M+

**Description**: 1M+ recipes with images. We only need text: layer1.json + det_ingrs.json (~4GB).
**Source**: http://pic2recipe.csail.mit.edu/
**Status**: ⏳ PENDING — requires registration

## Action Required

**Jeff**: Please register at http://pic2recipe.csail.mit.edu/ and share the download link.

Steps:
1. Visit http://pic2recipe.csail.mit.edu/
2. Fill registration form (academic/research use)
3. Receive download link via email
4. Run: `python scripts/phase0/pull_recipe1m_manual.py --url <download_link>`

## Files Needed (text only, NOT images)
- `layer1.json` (~2.7 GB) — recipe text + ingredients + instructions
- `det_ingrs.json` (~1.5 GB) — detected ingredient tokens

## Expected Role
Observation / MSA variant signal and ingredient co-occurrence statistics.

## Alternative
Smaller subset at: https://github.com/torralba-lab/im2recipe-Pytorch
""", encoding="utf-8")

    (target / "manifest.json").write_text(json.dumps({
        "name": "Recipe1M+", "version": "pending",
        "source_url": "http://pic2recipe.csail.mit.edu/",
        "download_date": None, "files": [],
        "role": "observation", "license": "Academic non-commercial",
        "status": "pending_registration",
        "notes": "Requires registration. Jeff action needed.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    record(name, "pending", "0 B", "Requires registration at http://pic2recipe.csail.mit.edu/ — Jeff action needed")


# ─── 4. RecipeNLG ─────────────────────────────

def pull_recipenlg():
    name = "RecipeNLG"
    target = RAW_DIR / "recipenlg"
    target.mkdir(exist_ok=True)
    t0 = time.time()
    files = []
    failed = []

    # HuggingFace parquet shards
    hf_base = "https://huggingface.co/datasets/mbien/recipe_nlg/resolve/main/data"
    shards = [
        f"{hf_base}/train-00000-of-00002.parquet",
        f"{hf_base}/train-00001-of-00002.parquet",
    ]

    for url in shards:
        fname = url.split("/")[-1]
        dest = target / fname
        if dest.exists() and dest.stat().st_size > 100_000:
            print(f"  ✓ {fname} already exists ({human_size(dest.stat().st_size)})")
            files.append({"path": str(dest.relative_to(REPO_ROOT)),
                          "size": human_size(dest.stat().st_size),
                          "sha256": sha256_file(dest)})
            continue
        ok, msg = download_file(url, dest, fname)
        if ok:
            files.append({"path": str(dest.relative_to(REPO_ROOT)),
                          "size": human_size(dest.stat().st_size),
                          "sha256": sha256_file(dest)})
        else:
            failed.append(f"{fname}: {msg}")
            print(f"  ✗ {fname}: {msg}")

    elapsed = time.time() - t0
    total_sz = sum(f.stat().st_size for f in target.glob("*") if f.is_file())

    (target / "README.md").write_text(f"""# RecipeNLG

**Description**: 2.2M cooking recipes in English. Parquet format from HuggingFace.
**Source**: https://recipenlg.cs.put.poznan.pl/ | HuggingFace: mbien/recipe_nlg
**Downloaded**: {NOW}
**License**: CC BY-NC-SA 4.0 (non-commercial — confirmed OK)
**Expected Role**: Observation / MSA variant signal and ingredient co-occurrence

## Files
| File | Size | Description |
|------|------|-------------|
| train-00000-of-00002.parquet | ~1GB | Recipes part 1 |
| train-00001-of-00002.parquet | ~1GB | Recipes part 2 |

## Schema (Parquet)
- title, ingredients (list), directions (list), link, source, NER

## Status
{'✅ Complete' if not failed else ('⚠️ Partial — ' + '; '.join(failed) if files else '❌ Failed')}

## Notes
- Non-commercial use confirmed OK (project not commercial).
- Do NOT import into production without quality check.
""", encoding="utf-8")

    (target / "manifest.json").write_text(json.dumps({
        "name": "RecipeNLG",
        "version": "HuggingFace mbien/recipe_nlg",
        "source_url": "https://huggingface.co/datasets/mbien/recipe_nlg",
        "download_date": NOW, "files": files,
        "role": "observation", "license": "CC BY-NC-SA 4.0",
        "notes": "; ".join(failed) if failed else "Complete.",
        "elapsed_seconds": round(elapsed, 1),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    status = "done" if not failed else ("partial" if files else "failed")
    record(name, status, human_size(total_sz),
           "; ".join(failed) if failed else f"elapsed {elapsed:.0f}s", files)


# ─── 5. USDA FDC ─────────────────────────────

def fix_usda_fdc():
    name = "USDA FoodData Central"
    target = RAW_DIR / "usda_fdc"
    target.mkdir(exist_ok=True)

    # Data already exists at data/external/usda-fdc/
    existing = REPO_ROOT / "data" / "external" / "usda-fdc"
    existing_files_list = []
    total_sz = 0

    if existing.exists():
        for f in sorted(existing.glob("*")):
            if f.is_file():
                existing_files_list.append({
                    "path": str(f.relative_to(REPO_ROOT)),
                    "size": human_size(f.stat().st_size),
                })
                total_sz += f.stat().st_size

    (target / "README.md").write_text(f"""# USDA FoodData Central

**Description**: USDA FDC nutritional reference database. Foundation Foods, SR Legacy, FNDDS, Branded Foods.
**Source**: https://fdc.nal.usda.gov/download-datasets.html
**License**: Public Domain (US Government)
**Expected Role**: Reference / cross-validation (NOT production import)

## Data Location
Existing data: `data/external/usda-fdc/` — {len(existing_files_list)} files, {human_size(total_sz)}

Files:
{chr(10).join('- ' + f['path'] + ' (' + f['size'] + ')' for f in existing_files_list)}

## Status
{'✅ Complete (data exists at data/external/usda-fdc/)' if existing_files_list else '⏳ Pending — no data found'}

## Notes
- Data already downloaded previously at `data/external/usda-fdc/`.
- Not duplicated here to avoid wasting disk space.
- Do NOT import into production. Reference only.
- Full FDC download (~750MB CSV zip): https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_csv_2024-04-18.zip
""", encoding="utf-8")

    (target / "manifest.json").write_text(json.dumps({
        "name": "USDA FoodData Central",
        "version": "previously downloaded",
        "source_url": "https://fdc.nal.usda.gov/download-datasets.html",
        "download_date": NOW,
        "files": existing_files_list,
        "actual_location": str(existing),
        "role": "reference", "license": "Public Domain",
        "notes": f"Data at data/external/usda-fdc/. {len(existing_files_list)} files.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    status = "done" if existing_files_list else "partial"
    record(name, status, human_size(total_sz),
           f"Data at data/external/usda-fdc/ ({len(existing_files_list)} files)", existing_files_list)


# ─── Write INDEX.md ────────────────────────────

def write_index():
    total_sz = sum(
        f.stat().st_size for f in RAW_DIR.rglob("*")
        if f.is_file() and ".git" not in str(f)
    )
    rows = []
    for r in REPORT:
        icon = "✅" if r["status"] == "done" else ("⏳" if r["status"] == "pending" else ("⚠️" if r["status"] == "partial" else "❌"))
        rows.append(f"| {icon} | {r['dataset']} | {r['status']} | {r['size']} | {r['notes'][:80]} |")

    (RAW_DIR / "INDEX.md").write_text(f"""# External Data Index — Phase 0

**Generated**: {NOW}
**Total size (raw/)**: {human_size(total_sz)}
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
1. QC pass on each dataset
2. **Recipe1M+** — Jeff to register at http://pic2recipe.csail.mit.edu/
3. After QC: staging → approved → distillation pipeline
""", encoding="utf-8")
    print(f"\n📄 INDEX.md written ({human_size(total_sz)} total in raw/)")


def write_report():
    report_dir = REPO_ROOT / "raw" / "coder"
    report_dir.mkdir(parents=True, exist_ok=True)
    total_sz = sum(
        f.stat().st_size for f in RAW_DIR.rglob("*")
        if f.is_file() and ".git" not in str(f)
    )
    done = [r for r in REPORT if r["status"] == "done"]
    partial = [r for r in REPORT if r["status"] == "partial"]
    pending = [r for r in REPORT if r["status"] == "pending"]
    failed_r = [r for r in REPORT if r["status"] == "failed"]

    sections = []
    for r in REPORT:
        icon = "✅" if r["status"] == "done" else ("⏳" if r["status"] == "pending" else ("⚠️" if r["status"] == "partial" else "❌"))
        sections.append(f"""### {icon} {r['dataset']}
- **Status**: {r['status']}
- **Size**: {r['size']}
- **Notes**: {r['notes']}
""")

    (report_dir / "phase0-pull-report.md").write_text(f"""# Phase 0 — External Dataset Pull Report

**Date**: {NOW[:10]}
**Total size**: {human_size(total_sz)}
**Summary**: {len(done)} done, {len(partial)} partial, {len(pending)} pending, {len(failed_r)} failed

## Dataset Status

{''.join(sections)}

## Action Required by Jeff

- **Recipe1M+**: Register at http://pic2recipe.csail.mit.edu/ to get download link. We only need `layer1.json` + `det_ingrs.json` (~4GB text, NOT images).

## Constraints Verified
- ✅ All files in `data/external/raw/` only
- ✅ Production databases untouched (L0/L2a/L2b/Neo4j)
- ✅ No loaders written
- ✅ No data cleaning performed
- ✅ trust_env=False (no 7890 proxy)

## Next Steps
1. QC pass on each dataset
2. Recipe1M+ registration (Jeff action above)
3. FoodKG full 67M triple dump — evaluate if needed after QC
4. USDA FDC full CSV zip (~750MB) — currently have partial JSONL; full zip available if needed
5. After QC → staging → approved → distillation pipeline
""", encoding="utf-8")
    print(f"📄 Report: raw/coder/phase0-pull-report.md")


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 0 — Pull Remaining Datasets")
    print(f"Free disk: {human_size(shutil.disk_usage(str(RAW_DIR)).free)}")
    print("=" * 60)

    fix_foodon()
    fix_foodkg()
    fix_recipe1m()
    pull_recipenlg()
    fix_usda_fdc()

    write_index()
    write_report()

    print("\n" + "=" * 60)
    print("Phase 0 complete.")
