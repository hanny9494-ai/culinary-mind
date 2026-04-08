# Phase 0b — Flavor/Chemistry Dataset Pull Report (Final)

**Date**: 2026-04-08
**Total raw/ size**: 3.9 GB
**Summary**: 4 done, 2 needs scraper, 4 pending/not-found

## Dataset Status

### ✅ FooDB
- **Status**: done
- **Size**: 1.9 GB
- **Notes**: 29 CSV tables (existing). Key: Compound.csv × Content.csv × Food.csv.
### ❌ FoodAtlas
- **Status**: not_found
- **Size**: 0 B
- **Notes**: Repo knbuckner/FoodAtlas = 404. FooDB+FlavorGraph cover this.
### 🤖 FlavorDB2
- **Status**: needs_scraper
- **Size**: 0 B
- **Notes**: No API. open-data-collector: entity/1..25595 ~7h.
### ✅ Open Food Facts
- **Status**: done
- **Size**: 1.2 GB
- **Notes**: CSV.gz 3M+ products downloaded.
### ✅ Phenol-Explorer
- **Status**: done
- **Size**: 223 KB
- **Notes**: Core CSVs: compounds, foods, metabolites, structures.
### ❌ BitterDB
- **Status**: pending
- **Size**: 0 B
- **Notes**: Server unreachable (Hebrew U). Manual: dload.php.
### ❌ SuperSweet
- **Status**: pending
- **Size**: 0 B
- **Notes**: Server unreachable (Charité Berlin). Manual: sweet/ download.
### 🤖 GoodScents
- **Status**: needs_scraper
- **Size**: 0 B
- **Notes**: Static HTML. open-data-collector: ~8000 compound pages ~2.5h.
### ✅ FlavorNet/Ahn2011
- **Status**: done
- **Size**: 4.9 MB
- **Notes**: In flavorgraph/input/edges_191120.csv (4.9MB edge list).
### ⏳ CFSDB
- **Status**: pending
- **Size**: 0 B
- **Notes**: No public bulk download. Options: Taiwan FDA / CN book / skip.


## Datasets Needing open-data-collector (Mac Mini OpenClaw)
- **FlavorDB2**: `GET /flavordb2/entity/{id}` for id 1–25,595 (~7h at 1 req/s)
- **GoodScents**: `GET /data/{id}.html` ~8,000 compound pages (~2.5h at 1 req/s)

## Jeff Decision Needed
- **CFSDB**: Three options:
  1. ✅ Taiwan FDA Food Composition (open bulk download): https://consumer.fda.gov.tw/Food/TFND.aspx?nodeID=178
  2. Purchase 《中国食物成分表》+ OCR (most complete for Chinese cuisine)
  3. Skip for now

## Small Manual Downloads (30 min)
- **BitterDB** (~1000 bitter compounds): http://bitterdb.agri.huji.ac.il/bitterdb/dload.php
- **SuperSweet** (~11000 sweet compounds): http://bioinf-applied.charite.de/sweet/

## Constraints Verified
- ✅ All files in `data/external/raw/` only
- ✅ Production databases untouched (L0/L2a/L2b/Neo4j)
- ✅ No loaders, no cleaning, no scraping by coder
