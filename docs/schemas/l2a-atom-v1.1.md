# L2a Ingredient-Atom Schema — v1.1

Producers:
- `pipeline/skills/run_skill.py --skill c` (per-page extraction)
- `pipeline/l2a/atoms/*.py` merge / synthesis scripts

Sink: `output/l2a/atoms/*.json`

Version field: `_v` (default `"1.0"` when absent).

## Fields

| Field               | Type                      | Required | Description                                                          |
|---------------------|---------------------------|----------|----------------------------------------------------------------------|
| `_v`                | string                    | no       | Schema version. v1.1 producers write `"1.1"`; missing → treat as `"1.0"`.                        |
| `evidence_type` | enum string       | no       | Added in v1.1. One of `textbook`, `empirical`, `review`, `computed`. Marks how strongly to trust this record at inference time. |
| `canonical_id`      | string                    | yes      | Matches an entry in `output/l2a/canonical_map_v2_final.json`.        |
| `display_name`      | object                    | yes      | `{zh, en}` canonical display strings.                                |
| `scientific_name`   | string                    | no       | Latin binomial if applicable.                                        |
| `composition`       | object                    | no       | Typical macros: `water_pct`, `protein_pct`, `fat_pct`, `carb_pct`, `ash_pct`. |
| `flavor_profile`    | object                    | no       | `{primary_tastes: [], aroma_notes: []}`.                             |
| `texture`           | object                    | no       | `{raw, cooked}` textural descriptions.                               |
| `culinary_uses`     | object                    | no       | `{methods: []}` and free-form fields.                                |
| `sourcing`          | object                    | no       | Origin / season / market info.                                       |
| `l0_domains`        | array of string           | no       | Each element MUST be one of the 17 L0 domains OR `"other"`.          |
| `external_ids`      | object                    | no       | `{usda_fdc, foodb, flavordb2, pubchem, foodon}` — managed by `ExternalIdRegistry`. |

Per-page Skill C extraction records may also include the underscore-prefixed
metadata fields `_page`, `_skill: "c"`, `_book`, mirroring Skill A/B/D
conventions.


## `evidence_type` (added in v1.1)

Optional enum describing the provenance quality of this record.

| Value      | Meaning                                                                       |
|------------|-------------------------------------------------------------------------------|
| `textbook` | From an authoritative textbook / monograph. Default for distilled book data.  |
| `empirical`| From an experimental study / peer-reviewed dataset. Primary evidence.         |
| `review`   | From a review paper aggregating other sources. Secondary evidence.            |
| `computed` | Derived by a solver / model / another record. Not primary source.             |

Backward compatibility: missing field → treat as `None` (unknown).
Consumers should not reject v1.0 records lacking this field.

## Example

```json
{
  "_v": "1.1",
  "canonical_id": "pork_belly",
  "display_name": {"zh": "五花肉", "en": "Pork Belly"},
  "scientific_name": "Sus scrofa domesticus",
  "composition": {"water_pct": 42.0, "protein_pct": 9.0, "fat_pct": 48.0, "carb_pct": 0.0},
  "flavor_profile": {"primary_tastes": ["umami", "savoury"], "aroma_notes": ["roast", "porky"]},
  "texture": {"raw": "dense with alternating lean/fat bands", "cooked": "unctuous, layered"},
  "culinary_uses": {"methods": ["braise", "roast", "confit"]},
  "sourcing": {},
  "l0_domains": ["lipid_science", "protein_science"],
  "external_ids": {"usda_fdc": "167909", "foodb": "FOOD00201"}
}
```