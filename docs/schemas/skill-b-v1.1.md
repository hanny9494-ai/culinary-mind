# Skill B Recipe Schema — v1.1

Producer: `pipeline/skills/run_skill.py --skill b`
Sink: `output/{book_id}/skill_b/results.jsonl`

Version field: `_v` (default `"1.0"` when absent).

## Fields

| Field                 | Type                  | Required | Description                                                                 |
|-----------------------|-----------------------|----------|-----------------------------------------------------------------------------|
| `_v`                  | string                | no       | Schema version. v1.1 producers write `"1.1"`; missing → treat as `"1.0"`.                               |
| `evidence_type` | enum string       | no       | Added in v1.1. One of `textbook`, `empirical`, `review`, `computed`. Marks how strongly to trust this record at inference time. |
| `recipe_id`           | string                | yes      | `"auto"` at extraction time; canonicalised downstream.                      |
| `name`                | string                | yes      | English recipe name.                                                        |
| `name_zh`             | string                | no       | Chinese name (required when source is Chinese).                             |
| `recipe_type`         | enum string           | yes      | `main` / `side` / `sauce` / `dessert` / `bread` / `soup` / `snack`.         |
| `ingredients`         | array of object       | yes      | `[{name, amount, prep}]`.                                                   |
| `steps`               | array of object       | yes      | `[{step, text, time_min, temp_c}]`.                                         |
| `equipment`           | array of string       | no       | Equipment list, e.g. `["sauté pan", "oven"]`.                               |
| `course`              | string                | no       | `main` / `side` / `sauce` / `dessert` — logical course independent of type. |
| `flavor_tags`         | array of string       | no       | Free-form flavor descriptors.                                               |
| `dietary_tags`        | array of string       | no       | `vegetarian` / `vegan` / `gluten-free` / …                                  |
| `key_science_points`  | array of object       | no       | `[{l0_domain, decision_point, confidence}]`.                                |
| `source`              | object                | yes      | `{book, page}`.                                                             |
| `_page`               | integer               | yes      | Injected by runner.                                                         |
| `_skill`              | enum string           | yes      | Always `"b"`.                                                               |
| `_book`               | string                | yes      | Book id.                                                                    |

## Constraints

- `ingredients[*].name` uses the English key name. Chinese sources
  populate `item` instead — the L2a ingest accepts both (see the
  `scripts/ingredient_frequency.py` scanner).
- `steps[*].time_min` and `steps[*].temp_c` are nullable but typed
  (integer or null).
- `key_science_points[*].l0_domain` MUST be one of the 17 L0 domains or
  `"other"` (to match the Skill D constraint already enforced).


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
  "recipe_id": "auto",
  "name": "Tomato Confit",
  "name_zh": "油封番茄",
  "recipe_type": "side",
  "ingredients": [
    {"name": "tomato", "amount": "500 g", "prep": "halved"},
    {"name": "olive oil", "amount": "250 ml", "prep": ""}
  ],
  "steps": [
    {"step": 1, "text": "Heat oven to 95°C.", "time_min": null, "temp_c": 95},
    {"step": 2, "text": "Bake 3 h.", "time_min": 180, "temp_c": 95}
  ],
  "equipment": ["oven"],
  "course": "side",
  "flavor_tags": ["sweet", "umami"],
  "dietary_tags": ["vegan"],
  "key_science_points": [
    {"l0_domain": "maillard_caramelization", "decision_point": "low heat preserves pectin", "confidence": "high"}
  ],
  "source": {"book": "modernist_cuisine_v2", "page": 181},
  "_page": 181, "_skill": "b", "_book": "modernist_cuisine_v2"
}
```