# FlavorTarget (FT) Schema — v1.1

Producer: `pipeline/skills/run_skill.py --skill d` (records where `_type == "flavor_target"`)
Sink: `output/{book_id}/skill_d/results.jsonl`

Version field: `_v` (default `"1.0"` when absent).

## Fields

| Field                | Type                  | Required | Description                                                                |
|----------------------|-----------------------|----------|----------------------------------------------------------------------------|
| `_v`                 | string                | no       | Schema version. v1.1 producers write `"1.1"`; missing → treat as `"1.0"`.                              |
| `evidence_type` | enum string       | no       | Added in v1.1. One of `textbook`, `empirical`, `review`, `computed`. Marks how strongly to trust this record at inference time. |
| `ft_id`              | string                | yes      | Slug identifier, typically `aesthetic_word_en + substrate` normalised.     |
| `aesthetic_word`     | string                | yes      | Sensory descriptor in source language (e.g. `镬气`, `crispy`).             |
| `aesthetic_word_en`  | string                | yes      | English rendering of the aesthetic word.                                   |
| `matrix_type`        | string                | yes      | Matrix classification (`liquid`, `solid_crystalline`, `foam`, …).          |
| `substrate`          | string                | yes      | Concrete ingredient or dish the word attaches to.                          |
| `target_states`      | object                | yes      | `{parameter: {target, range}}`. Parameters are quantitative sensory variables. |
| `l0_domains`         | array of string       | yes      | Each element MUST be one of the 17 L0 domains OR `"other"`.                |
| `source`             | object                | yes      | `{book, page}`.                                                            |
| `_type`              | enum string           | yes      | Always `"flavor_target"` for FT rows.                                      |
| `_page`              | integer               | yes      | Injected by runner.                                                        |
| `_skill`             | enum string           | yes      | Always `"d"`.                                                              |
| `_book`              | string                | yes      | Book id.                                                                   |

## Constraints

- `l0_domains` is empty-list-allowed but strongly encouraged to be
  non-empty; every listed domain string is validated against the 17
  canonical names with `other` as the only escape hatch.
- `target_states[*].target` may be `null` (the value is descriptive
  only); `range` is an array like `[low, high]`.
- The prompt in `pipeline/skills/run_skill.py` enforces the full field
  set at extraction time.


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

## Example

```json
{
  "_v": "1.1",
  "ft_id": "wok_hei_stirfry_beef",
  "aesthetic_word": "镬气",
  "aesthetic_word_en": "wok hei",
  "matrix_type": "protein_sear",
  "substrate": "牛肉",
  "target_states": {
    "surface_temperature_c": {"target": 230, "range": [200, 260]},
    "maillard_browning":     {"target": "high", "range": []}
  },
  "l0_domains": ["maillard_caramelization", "thermal_dynamics"],
  "source": {"book": "zhujixiaoguan_3", "page": 41},
  "_type": "flavor_target",
  "_page": 41, "_skill": "d", "_book": "zhujixiaoguan_3"
}
```