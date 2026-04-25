# Skill A Parameter-Set Schema — v1.1

Producer: `pipeline/skills/run_skill.py --skill a`
Sink: `output/{book_id}/skill_a/results.jsonl`

Version field: `_v` (default `"1.0"` when absent).

## Fields

| Field             | Type              | Required | Description                                                                                  |
|-------------------|-------------------|----------|----------------------------------------------------------------------------------------------|
| `_v`              | string            | no       | Schema version. v1.1 producers write `"1.1"`; missing → treat as `"1.0"`.                                                |
| `evidence_type` | enum string       | no       | Added in v1.1. One of `textbook`, `empirical`, `review`, `computed`. Marks how strongly to trust this record at inference time. |
| `mother_formula`  | string            | yes      | Canonical Mother Formula name (see `config/mother_formulas.yaml`), e.g. `Fourier_1D`.       |
| `formula_id`      | string            | yes      | Mother Formula id, e.g. `MF-T01`. Must start with `MF-T`/`MF-K`/`MF-M`/`MF-R`/`MF-C`.       |
| `parameter_name`  | string            | yes      | Symbol or human-readable parameter name, e.g. `Ea`, `alpha`, `denaturation_temperature`.    |
| `value`           | number            | yes      | Numeric value in the recorded unit.                                                          |
| `unit`            | string            | yes      | Unit as given in the source, not yet normalised.                                             |
| `conditions`      | object            | no       | Experimental / substrate conditions. Free-form keys (`substrate`, `pH`, `temperature_range`).|
| `source`          | object            | yes      | `{book, chapter, page, table}` — where the value came from.                                  |
| `confidence`      | enum string       | yes      | `high` / `medium` / `low`.                                                                   |
| `causal_context`  | string            | yes      | 1–2 sentence explanation of the causal chain this parameter feeds into. MUST NOT be empty.   |
| `notes`           | string            | no       | Free-form notes.                                                                             |
| `_page`           | integer           | yes      | Source page number (injected by the runner).                                                 |
| `_skill`          | enum string       | yes      | Always `"a"`.                                                                                |
| `_book`           | string            | yes      | Book id.                                                                                     |

## Constraints

- `confidence` ∈ `{high, medium, low}` exactly — no numeric values in v1.0.
- `causal_context` is explicitly non-empty (enforced by the Skill A prompt).
- `formula_id` prefix must be one of `MF-T / MF-K / MF-M / MF-R / MF-C`.


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
  "mother_formula": "Arrhenius",
  "formula_id": "MF-T03",
  "parameter_name": "Ea",
  "value": 85000,
  "unit": "J/mol",
  "conditions": {"substrate": "milk casein", "pH": 6.7, "temperature_range": "60-90°C"},
  "source": {"book": "toledo_kinetics", "chapter": "5", "page": 142, "table": "5.3"},
  "confidence": "high",
  "causal_context": "Higher activation energy slows β-lactoglobulin denaturation; critical for pasteurisation schedules.",
  "notes": "Fit value across 3 studies",
  "_page": 142,
  "_skill": "a",
  "_book": "toledo_kinetics"
}
```