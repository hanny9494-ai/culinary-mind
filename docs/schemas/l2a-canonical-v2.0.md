# L2a Canonical Map Schema — v2.0

Producer: `pipeline/l2a/canonicalize/*` scripts (R1 Flash → R2 Opus merge → R3 Flash remap)
Sink: `output/l2a/canonical_map_v2_final.json`

Version field: `_v` (this registry is declared `"2.0"` at baseline because
it has gone through three iteration rounds before this version scheme
was formalised; the on-disk file pre-dates adding the field in-record).

## Top-level structure

```json
{
  "_v": "2.0",
  "metadata": {
    "total_raw": 60499,
    "total_canonical": 26434,
    "mapped": 56066,
    "unmapped": 4433,
    "created": "2026-04-02",
    "rounds": "R1 Flash + R2 Opus merge + R3 Flash remap"
  },
  "canonicals": [ {...}, ... ],
  "raw_to_canonical": { "raw_name": "canonical_id", ... }
}
```

## Canonical entry fields

| Field                | Type             | Required | Description                                                         |
|----------------------|------------------|----------|---------------------------------------------------------------------|
| `canonical_id`       | string           | yes      | Slugified id. Stable across rounds.                                 |
| `canonical_name_en`  | string           | yes      | English canonical name.                                             |
| `canonical_name_zh`  | string           | no       | Chinese canonical name (may be empty for foreign-only items).       |
| `category`           | string           | no       | High-level bucket (`vegetable`, `protein`, `grain`, `spice`, …).    |
| `confidence`         | enum string      | no       | `high` / `medium` / `low` — R3 stability confidence.                |
| `raw_variants`       | array of string  | yes      | All raw surface forms that map here.                                |
| `external_ids`       | object           | yes      | Keyed by source (`usda_fdc`, `foodb`, `flavordb2`, `pubchem`, `foodon`). |

## Raw-to-canonical lookup

`raw_to_canonical` is a flat dict `{raw_name: canonical_id}` built for
O(1) lookup at ETL time. The `CanonicalMatcher` class in
`pipeline.etl.common` loads this file and exposes `.match(name)` and
`.register_new(...)`.

## Why v2.0 at baseline

The canonical map went through three rounds before `_v` was introduced:
- R1 (Flash) — initial clustering of 60 499 raw variants
- R2 (Opus) — merge duplicates, fix cluster boundaries
- R3 (Flash) — remap unmapped entries using R2 clusters

Starting at `2.0` signals that the baseline is already a mature product
(not an "initial draft"). Future minor bumps (`2.1`, `2.2`) will add
optional fields such as per-entry provenance; a `3.0` would rename
`canonical_id` or restructure `external_ids`.

## Example entry

```json
{
  "canonical_id": "pork_belly",
  "canonical_name_en": "pork belly",
  "canonical_name_zh": "五花肉",
  "category": "protein",
  "confidence": "high",
  "raw_variants": ["pork belly", "Pork, belly, raw", "五花肉", "带皮五花"],
  "external_ids": {"usda_fdc": "167909", "foodb": "FOOD00201"}
}
```
