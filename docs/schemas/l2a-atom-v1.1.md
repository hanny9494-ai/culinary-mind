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
| `process_state`     | enum string               | no       | Added in v1.1. The processing state of the ingredient — see table below. |
| `prep_class`        | enum string               | no       | Added in v1.1. High-level prep classification — see table below.        |
| `derived_from`      | string                    | no       | Added in v1.1. Parent canonical_id when this atom is a derivative of another (e.g. `chicken_stock` derived_from `chicken_carcass`). |

Per-page Skill C extraction records may also include the underscore-prefixed
metadata fields `_page`, `_skill: "c"`, `_book`, mirroring Skill A/B/D
conventions.


## `evidence_type` (added in v1.1)

Optional enum describing the provenance quality of this record.

| Value            | Meaning                                                                                |
|------------------|----------------------------------------------------------------------------------------|
| `empirical`      | From an experimental study / peer-reviewed dataset. Primary evidence.                  |
| `theoretical`    | Derived from established physical/chemical laws (Arrhenius, Fick, Henderson-Hasselbalch).|
| `expert_opinion` | From an authoritative textbook / monograph / chef manual — synthesised expert summary. |
| `derived`        | Derived by a solver / model / another record. Not a primary source.                    |

Backward compatibility: missing field → treat as `None` (unknown).
Consumers should not reject v1.0 records lacking this field.

## `process_state` / `prep_class` / `derived_from` (added in v1.1)

These three fields disambiguate ingredient atoms that share a canonical
name but differ in pre-processing:

### `process_state`

| Value         | Meaning                                                              |
|---------------|----------------------------------------------------------------------|
| `raw`         | Untreated / uncooked / unprocessed.                                  |
| `cooked`      | Heat-treated (boiled, baked, roasted, fried).                        |
| `dried`       | Water removed via drying / dehydration.                              |
| `frozen`      | Held below freezing point.                                           |
| `fermented`   | Microbial transformation applied (kimchi, miso, soy sauce, …).       |
| `cured`       | Salt/nitrate-treated (charcuterie, salted fish, …).                  |
| `processed`   | Industrially refined / extracted (oils, sugars, isolates, …).        |
| `mixed`       | Multi-state (blend, paste, dough — when a single state doesn't fit). |

### `prep_class`

| Value          | Meaning                                                              |
|----------------|----------------------------------------------------------------------|
| `whole`        | Intact piece (whole chicken, whole onion, whole cabbage).            |
| `cut`          | Diced / sliced / chopped / julienned.                                |
| `ground`       | Minced / ground / pureed.                                            |
| `extract`      | Liquid or concentrate from a parent (stock, juice, dashi, infusion). |
| `powder`       | Dry, finely milled (spice powder, milk powder, isolate).             |
| `paste`        | Semi-solid mixture (curry paste, miso, gochujang).                   |

### `derived_from`

When an atom is a transformation of a "parent" canonical, set
`derived_from` to the parent's `canonical_id`. Examples:

```
chicken_stock     derived_from: chicken_carcass
caramelized_onion derived_from: onion
clarified_butter  derived_from: butter
```

This lets downstream queries traverse parent→child chains
(e.g. "all dairy-derived atoms").

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
  "external_ids": {"usda_fdc": "167909", "foodb": "FOOD00201"},
  "process_state": "raw",
  "prep_class": "whole",
  "derived_from": null
}
```

Derived-atom example:

```json
{
  "_v": "1.1",
  "canonical_id": "chicken_stock",
  "display_name": {"zh": "鸡高汤", "en": "Chicken Stock"},
  "process_state": "cooked",
  "prep_class": "extract",
  "derived_from": "chicken_carcass",
  "evidence_type": "expert_opinion"
}
```