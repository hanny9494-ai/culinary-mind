# Schema Version Changelog

## 2026-04-26 — evidence_type vocabulary refresh

The `evidence_type` enum (added 2026-04-24) is renamed to align with
the empirical-vs-theoretical-vs-secondary distinction used by the
inference layer:

  Old → New
  textbook → expert_opinion
  empirical → empirical (unchanged)
  review   → (folded into expert_opinion / derived per case)
  computed → derived
  (new)    → theoretical

The schema version stays at v1.1 because this is a *value-set* change
(no field added/removed). Pipelines emit the new enum starting now;
older records still validate (we never enforced a closed enum).

## 2026-04-24 — v1.1 Minor (evidence_type)

All L0, Skill A/B, FT (Skill D), L6 (Skill D), L2a atom schemas bump to
**v1.1** with one new OPTIONAL field:

- `evidence_type` — enum string, one of:
  - `textbook`  — from an authoritative textbook / monograph
  - `empirical` — from an experimental study / dataset
  - `review`    — from a review paper summarising other sources
  - `computed`  — derived from a solver / model / another record

Backward compatible: records without `evidence_type` are valid v1.0
data; consumers default to `None` (unknown).

Producers updated: `pipeline/l0/extract.py`,
`pipeline/skills/run_skill.py` (A/B/C/D prompts).

L2a canonical_map stays at v2.0 (provenance not tracked at the
canonical level). L2b normalized recipe stays at `schema_version: "v1"`.

---


Each data layer carries a lightweight `_v` string field that records the
schema version of the producing pipeline. Existing records without `_v`
are treated as v1.0 (the pipelines default to that on read).

**Convention**: `major.minor` semantic-version-ish.
- **Minor** (1.0 → 1.1): additive — new optional fields, pipelines stay
  backward-compatible.
- **Major** (1.x → 2.0): breaking — field removed/renamed. Requires a
  migration script in `scripts/migrations/migrate_{layer}_{old}_{new}.py`
  and all records updated.

**Exception — L2b normalized recipe** keeps its pre-existing
`schema_version: "v1"` field (has a formal JSON Schema in this directory).
No field-name change.

---

## 2026-04-23 — Initial version baselines

All layers below are simultaneously declared at their first official
schema version. Records produced prior to this date are considered
implicitly at the same version unless otherwise noted.

| Layer                 | Version field        | Baseline version | Spec file                    |
|-----------------------|----------------------|------------------|------------------------------|
| L0 causal chains      | `_v`                 | `1.1`            | [l0-v1.1.md](l0-v1.1.md)             |
| Skill A parameters    | `_v`                 | `1.1`            | [skill-a-v1.1.md](skill-a-v1.1.md)   |
| Skill B recipes       | `_v`                 | `1.1`            | [skill-b-v1.1.md](skill-b-v1.1.md)   |
| Skill D FT            | `_v`                 | `1.1`            | [ft-v1.1.md](ft-v1.1.md)             |
| Skill D L6 glossary   | `_v`                 | `1.1`            | [l6-v1.1.md](l6-v1.1.md)             |
| L2a atom              | `_v`                 | `1.1`            | [l2a-atom-v1.1.md](l2a-atom-v1.1.md) |
| L2a canonical_map     | `_v`                 | `2.0`            | [l2a-canonical-v2.0.md](l2a-canonical-v2.0.md) |
| L2b normalized recipe | `schema_version`     | `v1`             | [recipe-normalized-v1.json](recipe-normalized-v1.json) |
| L1 equipment          | `_v`                 | (no data yet)    | n/a                          |
| L2c commercial        | `_v`                 | (no data yet)    | n/a                          |

Skill C ingredient-atoms output feeds into the L2a atom schema
(`l2a-atom-v1.1.md`); its per-page extraction records therefore carry
`_v: "1.1"` alongside Skill A/B/D when emitted by `run_skill.py`.

Why `_v` (not `schema_version`) across the new layers:
- short, matches the existing `_page` / `_skill` / `_book` underscore
  metadata convention used by run_skill.py;
- saves ~15 bytes × 52 000 records ≈ 780 KB vs `schema_version`;
- L2b already ships `schema_version`, so we explicitly leave it alone.

---

## Upgrade policy

```
Minor (1.0 → 1.1):
  - Producer adds optional fields with `_v: "1.1"`.
  - Consumers default missing fields to v1.0 values via
    `record.get("_v", "1.0")`.
  - No backfill required.

Major (1.x → 2.0):
  - Write scripts/migrations/migrate_{layer}_{old}_{new}.py.
  - Migration rewrites every record with the new `_v` and any
    field renames / deletions.
  - Consumers drop v1.x compatibility branches after migration.
```

Record every version bump here with a dated section (newest first).
