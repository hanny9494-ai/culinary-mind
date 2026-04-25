"""
pipeline/etl/common.py
Public-facing helpers for all external-data ETL pipelines.

Seven classes:
    CanonicalMatcher   — ingredient name → canonical_id
    CompoundRegistry   — cascade compound matching (pubchem/cas/smiles/name)
    UnitNormalizer     — normalise composition / temperature / pressure units
    ExternalIdRegistry — track canonical_id ↔ external IDs (usda/foodb/…)
    BatchWriter        — append JSONL into output/etl_staging/{layer}/{source}.jsonl
    SuperNodeFilter    — mark high-degree nodes as Universal
    ConflictResolver   — pick the winning value from multiple sources

Design refs:
    raw/architect/022-data-ingestion-master-plan-20260420.md §四
    raw/architect/023-gemini-019-synthesis-ingestion-plan-final-20260420.md

Conventions:
    • All classes are in-memory; persistence is the caller's problem via
      `dump()` / `BatchWriter`. Nothing here mutates files in place
      except BatchWriter.
    • Nothing here knows about Neo4j. Staging JSONL is consumed later by
      pipeline/graph/bulk_import.py.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions (for CompoundRegistry safety — GPT-5.4 review fixes 1 & 2)
# ─────────────────────────────────────────────────────────────────────────────

class CompoundConflictError(ValueError):
    """Base class for compound-registry conflicts."""


class CrossKeyConflictError(CompoundConflictError):
    """Raised when a single input compound resolves to multiple existing
    compound_ids via different identifier keys — e.g. pubchem_id points
    to cmpd_A but cas_number points to cmpd_B. Silent merge would
    corrupt the registry, so we stop the caller instead.
    """


class WeakNameMergeError(CompoundConflictError):
    """Raised in strict mode when the ONLY matching key is
    normalized_name (a weak signal). Strong keys (pubchem/cas/smiles)
    are preferred; falling back to normalized_name alone can conflate
    different compounds that share a common name.
    """

log = logging.getLogger("pipeline.etl.common")

REPO_ROOT = Path(__file__).resolve().parents[2]


# ─────────────────────────────────────────────────────────────────────────────
# 1. CanonicalMatcher
# ─────────────────────────────────────────────────────────────────────────────

# Modifiers we strip from ingredient names when an exact match misses.
# Order-sensitive inside each group so longer phrases match first.
_NAME_MODIFIERS = (
    "freshly chopped", "freshly ground", "finely chopped", "finely sliced",
    "roughly chopped", "thinly sliced", "coarsely ground",
    "peeled and chopped", "peeled", "chopped", "sliced", "minced",
    "grated", "shredded", "crushed", "ground",
    "fresh", "dried", "raw", "cooked", "frozen", "canned", "powdered",
    "whole", "organic",
)


class CanonicalMatcher:
    """Map raw ingredient names → canonical_id.

    Loads the L2a canonical registry and exposes three lookup strategies:
      1. direct `raw_to_canonical` lookup (O(1))
      2. normalised-form lookup (lowercase / strip / collapse ws)
      3. modifier-stripped lookup (drop "fresh"/"dried"/"chopped"/...)

    `register_new()` lets an ETL pipeline add brand-new canonicals on
    the fly without mutating the on-disk map. Call `dump()` if you want
    the augmented registry persisted.
    """

    def __init__(self, canonical_map_path: str | Path | None = None):
        if canonical_map_path is None:
            canonical_map_path = REPO_ROOT / "output" / "l2a" / "canonical_map_v2_final.json"
        self.path = Path(canonical_map_path)
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"canonical_map not found: {self.path}")
        data = json.loads(self.path.read_text(encoding="utf-8"))

        # Schema-version sanity check — L2a canonical_map is pinned at v2.0
        # (see docs/schemas/l2a-canonical-v2.0.md). Warn loudly if the file
        # is missing `_v` or carries a version we don't recognise so the
        # caller knows the parser/schema may be mismatched.
        v = data.get("_v")
        if v is None:
            log.warning(
                f"CanonicalMatcher: {self.path} is missing `_v` — "
                f"treating as v2.0 baseline (see docs/schemas/CHANGELOG.md)."
            )
        elif v != "2.0":
            log.warning(
                f"CanonicalMatcher: {self.path} carries `_v={v!r}`, "
                f"expected '2.0'. Parser assumes v2.0 structure; verify "
                f"schema compatibility."
            )

        # Required keys per L2a schema
        self.metadata: dict = data.get("metadata", {})
        canonicals: list[dict] = data.get("canonicals", []) or []
        self.raw_to_canonical: dict[str, str] = dict(data.get("raw_to_canonical", {}) or {})

        # id → canonical entry
        self.by_id: dict[str, dict] = {c["canonical_id"]: c for c in canonicals}

        # Secondary indexes
        self._name_en_index: dict[str, str] = {}
        self._name_zh_index: dict[str, str] = {}
        for c in canonicals:
            cid = c["canonical_id"]
            en = (c.get("canonical_name_en") or "").strip().lower()
            zh = (c.get("canonical_name_zh") or "").strip()
            if en:
                self._name_en_index.setdefault(en, cid)
            if zh:
                self._name_zh_index.setdefault(zh, cid)
        # Normalised raw index (for second-pass matches)
        self._normalised_raw_index: dict[str, str] = {}
        for raw, cid in self.raw_to_canonical.items():
            nk = self._normalise(raw)
            if nk:
                self._normalised_raw_index.setdefault(nk, cid)

    # ── normalisation ────────────────────────────────────────────────────
    @staticmethod
    def _normalise(name: str) -> str:
        """Lowercase, NFKC, collapse whitespace, trim punctuation."""
        if not name:
            return ""
        s = unicodedata.normalize("NFKC", str(name)).strip().lower()
        s = re.sub(r"\s+", " ", s)
        s = s.strip(" .,;:!?\"'()[]{}")
        return s

    @classmethod
    def _strip_modifiers(cls, norm: str) -> str:
        s = f" {norm} "
        for m in _NAME_MODIFIERS:
            s = s.replace(f" {m} ", " ")
        return re.sub(r"\s+", " ", s).strip()

    # ── public API ───────────────────────────────────────────────────────
    def match(self, name: str, lang: str = "en") -> str | None:
        """Return canonical_id or None if no match."""
        if not name:
            return None
        raw = str(name)

        # 1. Exact raw → canonical
        cid = self.raw_to_canonical.get(raw)
        if cid:
            return cid

        # 2. Normalised raw index
        norm = self._normalise(raw)
        if norm:
            cid = self._normalised_raw_index.get(norm)
            if cid:
                return cid

        # 3. canonical_name match
        if lang == "zh":
            cid = self._name_zh_index.get(norm) or self._name_zh_index.get(raw.strip())
        else:
            cid = self._name_en_index.get(norm)
        if cid:
            return cid

        # 4. Modifier-stripped fallback
        stripped = self._strip_modifiers(norm)
        if stripped and stripped != norm:
            cid = (self._normalised_raw_index.get(stripped)
                   or self._name_en_index.get(stripped)
                   or self._name_zh_index.get(stripped))
            if cid:
                return cid
        return None

    def register_new(self, name_en: str, name_zh: str = "",
                     category: str = "other",
                     confidence: str = "medium") -> str:
        """Add a new canonical. Returns the new canonical_id.

        Does NOT write to disk — call `dump()` to persist.
        """
        if not name_en:
            raise ValueError("name_en is required for register_new")
        cid = self._slugify(name_en)
        with self._lock:
            if cid in self.by_id:
                # de-dupe: extend raw_variants but return existing id
                existing = self.by_id[cid]
                if name_zh and not existing.get("canonical_name_zh"):
                    existing["canonical_name_zh"] = name_zh
                return cid
            entry = {
                "canonical_id":      cid,
                "canonical_name_en": name_en,
                "canonical_name_zh": name_zh or "",
                "category":          category,
                "confidence":        confidence,
                "raw_variants":      [name_en] + ([name_zh] if name_zh else []),
                "external_ids":      {},
            }
            self.by_id[cid] = entry
            # Index the new canonical so subsequent .match() finds it.
            en = name_en.strip().lower()
            if en:
                self._name_en_index.setdefault(en, cid)
            if name_zh:
                self._name_zh_index.setdefault(name_zh.strip(), cid)
            self.raw_to_canonical[name_en] = cid
            self._normalised_raw_index[self._normalise(name_en)] = cid
        log.debug(f"CanonicalMatcher: registered new canonical {cid} ← {name_en!r}")
        return cid

    @staticmethod
    def _slugify(name: str) -> str:
        """ASCII-safe slug for canonical_id."""
        s = unicodedata.normalize("NFKD", name)
        s = s.encode("ascii", "ignore").decode("ascii").lower()
        s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
        return s or f"ingredient_{int(time.time()*1000) % 1_000_000}"

    def dump(self, out_path: str | Path | None = None) -> Path:
        """Persist current state back to disk (JSON)."""
        out = Path(out_path) if out_path else self.path
        payload = {
            "metadata":         dict(self.metadata, dumped_at=_ts()),
            "canonicals":       list(self.by_id.values()),
            "raw_to_canonical": self.raw_to_canonical,
        }
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(out)
        return out


# ─────────────────────────────────────────────────────────────────────────────
# 2. CompoundRegistry
# ─────────────────────────────────────────────────────────────────────────────

class CompoundRegistry:
    """Cascade-match chemistry compound identifiers.

    MATCH_CHAIN order: pubchem_id → cas_number → canonical_smiles →
    normalized_name (lowercase + strip). Strong keys (the first three)
    are treated as primary merge evidence; normalized_name is a weak
    signal by itself.

    Safety guarantees (GPT-5.4 review fixes):
      • Cross-key conflicts raise CrossKeyConflictError — if the input
        record's pubchem/cas/smiles resolve to two or more different
        existing compound_ids, we refuse the merge rather than silently
        corrupt the registry.
      • Weak name-only matches only count in non-strict mode. In strict
        mode we raise WeakNameMergeError instead of merging two records
        that share a common normalized_name without any strong-key
        overlap.
    """

    STRONG_KEYS: tuple[str, ...] = ("pubchem_id", "cas_number", "canonical_smiles")
    WEAK_KEYS:   tuple[str, ...] = ("normalized_name",)
    MATCH_CHAIN: tuple[str, ...] = STRONG_KEYS + WEAK_KEYS

    def __init__(self):
        self._index: dict[str, dict[str, str]] = {k: {} for k in self.MATCH_CHAIN}
        self._records: dict[str, dict] = {}   # compound_id → full record
        self._lock = threading.Lock()
        self._seq = 0

    # ── normalisation helpers ────────────────────────────────────────────
    @staticmethod
    def _norm_name(name: str) -> str:
        return (name or "").strip().lower()

    def _derive_name_key(self, data: dict) -> str | None:
        """Prefer explicit normalized_name, otherwise normalise 'name'."""
        nn = (data.get("normalized_name") or "").strip().lower()
        if nn:
            return nn
        n = (data.get("name") or "").strip().lower()
        return n or None

    def _key_value(self, data: dict, key: str) -> str | None:
        if key == "normalized_name":
            return self._derive_name_key(data)
        v = data.get(key)
        return v if v else None

    # ── internal: gather all matches across keys ─────────────────────────
    def _gather_hits(self, compound_data: dict) -> dict[str, str]:
        """Return {key: compound_id} for every key in compound_data that
        already resolves to a known compound. Callers inspect this to
        detect cross-key conflicts and weak-only matches.
        """
        hits: dict[str, str] = {}
        for key in self.MATCH_CHAIN:
            val = self._key_value(compound_data, key)
            if val is None:
                continue
            cid = self._index[key].get(val)
            if cid is not None:
                hits[key] = cid
        return hits

    # ── public API ───────────────────────────────────────────────────────
    def match(self, compound_data: dict, strict: bool = False) -> str | None:
        """Return compound_id or None if no match.

        strict=False (default):
            normalized_name fallback is allowed (current behaviour).
        strict=True:
            only STRONG_KEYS can produce a hit. Useful when the caller
            cannot tolerate name collisions between different molecules.

        Always enforced:
            If a single compound_data resolves to TWO DIFFERENT ids via
            different keys (e.g. pubchem → A, cas → B), raises
            CrossKeyConflictError instead of returning the "first hit".
        """
        if not isinstance(compound_data, dict):
            return None
        hits = self._gather_hits(compound_data)
        if not hits:
            return None

        distinct_ids = set(hits.values())
        if len(distinct_ids) > 1:
            raise CrossKeyConflictError(
                f"compound_data resolves to multiple existing compound_ids "
                f"via different keys: {hits!r}"
            )

        cid = distinct_ids.pop()
        matched_keys = {k for k, v in hits.items() if v == cid}
        strong_match = bool(matched_keys & set(self.STRONG_KEYS))
        if not strong_match:
            # Only name matched.
            if strict:
                raise WeakNameMergeError(
                    f"refusing weak name-only match in strict mode "
                    f"(name={self._derive_name_key(compound_data)!r} → {cid})"
                )
            log.debug(
                f"CompoundRegistry: weak name-only match "
                f"(name={self._derive_name_key(compound_data)!r} → {cid})"
            )
        return cid

    def register(self, compound_data: dict, strict: bool = False) -> str:
        """Insert or merge a compound; returns compound_id.

        Behaviour:
          • If no prior hit → create a new record.
          • If exactly one prior hit across all keys → merge missing
            identifier keys into the existing record.
          • Cross-key conflict (different ids via different keys) →
            CrossKeyConflictError. NEVER silently merged.
          • Weak name-only match:
              strict=False → merge, log debug.
              strict=True  → WeakNameMergeError, caller decides.
        """
        hits = self._gather_hits(compound_data)
        distinct_ids = set(hits.values())

        with self._lock:
            if len(distinct_ids) > 1:
                raise CrossKeyConflictError(
                    f"register: cross-key conflict {hits!r}"
                )

            if distinct_ids:
                cid = distinct_ids.pop()
                matched_keys = set(hits.keys())
                if strict and not (matched_keys & set(self.STRONG_KEYS)):
                    raise WeakNameMergeError(
                        f"register: refusing weak name-only merge "
                        f"(name={self._derive_name_key(compound_data)!r} → {cid})"
                    )
                # Merge missing keys into existing record.
                rec = self._records[cid]
                for key in self.MATCH_CHAIN:
                    if key == "normalized_name":
                        val = self._derive_name_key(compound_data)
                        if val and "normalized_name" not in rec:
                            rec["normalized_name"] = val
                            self._index[key].setdefault(val, cid)
                        continue
                    val = compound_data.get(key)
                    if val and not rec.get(key):
                        rec[key] = val
                        self._index[key].setdefault(val, cid)
                return cid

            # Fresh record
            self._seq += 1
            cid = f"cmpd_{self._seq:07d}"
            rec = dict(compound_data)
            if "normalized_name" not in rec:
                n = self._derive_name_key(compound_data)
                if n:
                    rec["normalized_name"] = n
            self._records[cid] = rec
            for key in self.MATCH_CHAIN:
                val = rec.get(key) if key != "normalized_name" else rec.get("normalized_name")
                if val:
                    self._index[key].setdefault(val, cid)
            return cid

    def get(self, compound_id: str) -> dict | None:
        return self._records.get(compound_id)

    def __len__(self) -> int:
        return len(self._records)


# ─────────────────────────────────────────────────────────────────────────────
# 3. UnitNormalizer
# ─────────────────────────────────────────────────────────────────────────────

class UnitNormalizer:
    """Normalise values to canonical SI-ish units.

    Composition → mg/100g
    Temperature → °C
    Pressure    → kPa

    Usage:
        un = UnitNormalizer()
        v, u = un.normalize(25, "mg/kg")            # (2.5, 'mg/100g')
        v, u = un.normalize_temperature(350, "F")   # (176.67, 'C')
        v, u = un.normalize_pressure(1, "bar")      # (100.0, 'kPa')
    """

    # composition — target mg/100g
    CONVERSIONS: dict[str, float | None] = {
        "mg/100g": 1.0,
        "mg/100 g": 1.0,
        "ug/g":    0.1,      # 1 µg/g == 0.1 mg/100g
        "ug/100g": 0.001,
        "g/100g":  1000.0,
        "mg/kg":   0.1,
        "ppm":     0.1,
        "%":       10000.0,  # 1% == 10 g/100g == 10 000 mg/100g
        "mg/g":    100.0,
        "g/kg":    100.0,
        "ug/kg":   0.0001,
        "mmol/100g": None,   # molecular weight required — caller handles
    }

    # temperature conversions to °C
    _TEMP_UNITS = ("c", "celsius", "°c", "f", "fahrenheit", "°f", "k", "kelvin")

    # pressure conversions to kPa
    _PRESSURE_CONV = {
        "kpa":  1.0,
        "pa":   0.001,
        "mpa":  1000.0,
        "bar":  100.0,
        "mbar": 0.1,
        "atm":  101.325,
        "psi":  6.89476,
        "mmhg": 0.133322,
        "torr": 0.133322,
    }

    # ── public API ───────────────────────────────────────────────────────
    def normalize(self, value: float, unit: str) -> tuple[float | None, str]:
        """Composition → mg/100g. Returns (value_or_None, 'mg/100g' or 'unconvertible')."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None, "unconvertible"
        factor = self.CONVERSIONS.get(self._uc(unit))
        if factor is None:
            return None, "unconvertible"
        return v * factor, "mg/100g"

    def normalize_temperature(self, value: float, unit: str) -> tuple[float | None, str]:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None, "unconvertible"
        u = self._uc(unit)
        if u in ("c", "celsius", "°c"):
            return v, "C"
        if u in ("f", "fahrenheit", "°f"):
            return (v - 32.0) * 5.0 / 9.0, "C"
        if u in ("k", "kelvin"):
            return v - 273.15, "C"
        return None, "unconvertible"

    def normalize_pressure(self, value: float, unit: str) -> tuple[float | None, str]:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None, "unconvertible"
        factor = self._PRESSURE_CONV.get(self._uc(unit))
        if factor is None:
            return None, "unconvertible"
        return v * factor, "kPa"

    @staticmethod
    def _uc(unit: str) -> str:
        return (unit or "").lower().strip().replace(" ", "")

    # ── SI enforcement (P1-03) ───────────────────────────────────────────
    # Beyond the three domain-specific normalisers above, a single
    # dispatcher that understands many common culinary/engineering units
    # and converts them to SI-ish canonical forms:
    #
    #   temperature (°F/°C/K)      → "C"
    #   pressure (psi/bar/atm/…)   → "kPa"
    #   composition (%, mg/kg, …)  → "mg/100g"
    #   energy (BTU/cal/kcal/J)    → "J"
    #   volume (cup/tbsp/tsp/mL/…) → "mL"
    #   length (inch/ft/mm/…)      → "m"
    #   mass (oz/lb/g/…)           → "g"
    #   time (min/h/day)           → "s"
    #
    # `enforce_si()` is used by Skill A and L0 ingest scripts to keep a
    # single canonical unit per quantity at graph-import time.

    _ENERGY_CONV = {     # → J
        "j":       1.0,
        "kj":      1000.0,
        "cal":     4.184,
        "kcal":    4184.0,
        "btu":     1055.056,
        "wh":      3600.0,
        "kwh":     3_600_000.0,
    }
    _VOLUME_CONV = {     # → mL
        "ml":        1.0,
        "l":         1000.0,
        "liter":     1000.0,
        "litre":     1000.0,
        "cup":       236.588,
        "tbsp":      14.7868,
        "tablespoon":14.7868,
        "tsp":       4.92892,
        "teaspoon":  4.92892,
        "floz":      29.5735,
        "fl_oz":     29.5735,
        "gal":       3785.41,
        "gallon":    3785.41,
        "pt":        473.176,
        "pint":      473.176,
        "qt":        946.353,
        "quart":     946.353,
    }
    _LENGTH_CONV = {     # → m
        "m":   1.0,
        "cm":  0.01,
        "mm":  0.001,
        "um":  1e-6,
        "nm":  1e-9,
        "inch":  0.0254,
        "in":    0.0254,
        "ft":    0.3048,
        "foot":  0.3048,
        "yd":    0.9144,
        "yard":  0.9144,
    }
    _MASS_CONV = {       # → g
        "g":   1.0,
        "kg":  1000.0,
        "mg":  0.001,
        "ug":  1e-6,
        "oz":  28.3495,
        "ounce": 28.3495,
        "lb":  453.592,
        "pound": 453.592,
    }
    _TIME_CONV = {       # → s
        "s":    1.0,
        "sec":  1.0,
        "ms":   0.001,
        "min":  60.0,
        "h":    3600.0,
        "hr":   3600.0,
        "hour": 3600.0,
        "day":  86400.0,
    }

    # Inference — tells enforce_si() which family a unit belongs to when
    # the caller doesn't specify `quantity_type`.
    _FAMILY_INDEX: dict[str, str] = {}

    @classmethod
    def _build_family_index(cls) -> None:
        if cls._FAMILY_INDEX:
            return
        for fam, table in (
            ("temperature", ("c", "celsius", "°c", "f", "fahrenheit", "°f", "k", "kelvin")),
            ("pressure",    tuple(cls._PRESSURE_CONV.keys())),
            ("composition", tuple(cls.CONVERSIONS.keys())),
            ("energy",      tuple(cls._ENERGY_CONV.keys())),
            ("volume",      tuple(cls._VOLUME_CONV.keys())),
            ("length",      tuple(cls._LENGTH_CONV.keys())),
            ("mass",        tuple(cls._MASS_CONV.keys())),
            ("time",        tuple(cls._TIME_CONV.keys())),
        ):
            for u in table:
                key = u.lower().replace(" ", "")
                # First-seen wins; composition + mass share "mg" / "g" tokens so
                # we prefer the family we registered earlier. We register
                # temperature/pressure/composition first to resolve these
                # ambiguities the way existing callers expect.
                cls._FAMILY_INDEX.setdefault(key, fam)

    def _infer_family(self, unit: str) -> str | None:
        self._build_family_index()
        return self._FAMILY_INDEX.get(self._uc(unit))

    def enforce_si(
        self,
        value: float,
        unit: str,
        quantity_type: str | None = None,
        strict: bool = False,
    ) -> tuple[float | None, str]:
        """Convert (value, unit) to the canonical SI-ish unit.

        quantity_type:
            "temperature" / "pressure" / "composition" / "energy" /
            "volume" / "length" / "mass" / "time". If None, inferred
            from the unit string.

        strict:
            False (default) — returns (None, "unconvertible") for
              unknown units, mirroring the softer normalise_* helpers.
            True — raises ValueError instead, so Skill-A / L0 ingest
              can surface the bad record.
        """
        fam = quantity_type or self._infer_family(unit)
        if fam is None:
            if strict:
                raise ValueError(f"enforce_si: unknown unit {unit!r}")
            return None, "unconvertible"

        try:
            v = float(value)
        except (TypeError, ValueError):
            if strict:
                raise ValueError(f"enforce_si: non-numeric value {value!r}")
            return None, "unconvertible"

        u = self._uc(unit)
        if fam == "temperature":
            nv, nu = self.normalize_temperature(v, unit)
        elif fam == "pressure":
            nv, nu = self.normalize_pressure(v, unit)
        elif fam == "composition":
            nv, nu = self.normalize(v, unit)
        elif fam == "energy":
            f = self._ENERGY_CONV.get(u)
            nv, nu = (v * f, "J") if f is not None else (None, "unconvertible")
        elif fam == "volume":
            f = self._VOLUME_CONV.get(u)
            nv, nu = (v * f, "mL") if f is not None else (None, "unconvertible")
        elif fam == "length":
            f = self._LENGTH_CONV.get(u)
            nv, nu = (v * f, "m") if f is not None else (None, "unconvertible")
        elif fam == "mass":
            f = self._MASS_CONV.get(u)
            nv, nu = (v * f, "g") if f is not None else (None, "unconvertible")
        elif fam == "time":
            f = self._TIME_CONV.get(u)
            nv, nu = (v * f, "s") if f is not None else (None, "unconvertible")
        else:
            nv, nu = None, "unconvertible"

        if nv is None and strict:
            raise ValueError(
                f"enforce_si: cannot convert {value!r} {unit!r} "
                f"in family {fam!r}"
            )
        return nv, nu


# ─────────────────────────────────────────────────────────────────────────────
# 4. ExternalIdRegistry
# ─────────────────────────────────────────────────────────────────────────────

class ExternalIdRegistry:
    """Track mapping canonical_id → {source: external_id | list[external_id]}.

    Valid `source` values (not enforced but recommended):
      usda_fdc, foodb, flavordb2, flavorgraph, foodon, pubchem, openfoodfacts
    """

    VALID_SOURCES = frozenset({
        "usda_fdc", "foodb", "flavordb2", "flavorgraph",
        "foodon", "pubchem", "openfoodfacts",
    })

    def __init__(self):
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def link(self, canonical_id: str, source: str, external_id: str) -> None:
        if not canonical_id or not source or not external_id:
            raise ValueError("canonical_id / source / external_id are all required")
        if source not in self.VALID_SOURCES:
            log.warning(f"ExternalIdRegistry: non-standard source {source!r}")
        with self._lock:
            bucket = self._store.setdefault(canonical_id, {})
            cur = bucket.get(source)
            if cur is None:
                bucket[source] = external_id
            elif isinstance(cur, list):
                if external_id not in cur:
                    cur.append(external_id)
            else:
                if cur != external_id:
                    bucket[source] = [cur, external_id]

    def get_linked(self, canonical_id: str) -> dict[str, Any]:
        return dict(self._store.get(canonical_id, {}))

    def dump(self, out_path: str | Path) -> Path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"_ts": _ts(), "external_ids": self._store},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(out)
        return out

    def __len__(self) -> int:
        return len(self._store)


# ─────────────────────────────────────────────────────────────────────────────
# 5. BatchWriter
# ─────────────────────────────────────────────────────────────────────────────

class BatchWriter:
    """Append-JSONL writer with periodic flush and optional record validation.

    Writes to `{output_dir}/etl_staging/{layer}/{source}.jsonl`.

    >>> bw = BatchWriter(layer="l2a", source="foodb_foods",
    ...                  required_fields=("foodb_id", "name"))
    >>> bw.write([{"foodb_id": "FOOD00021", "name": "Tomato"}])
    >>> path = bw.finalize()
    """

    def __init__(
        self,
        layer: str,
        source: str,
        output_dir: str | Path | None = None,
        required_fields: Iterable[str] = (),
        flush_every: int = 500,
    ):
        base = Path(output_dir) if output_dir else (REPO_ROOT / "output")
        self.path = base / "etl_staging" / layer / f"{source}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.required_fields = tuple(required_fields)
        self.flush_every = max(1, int(flush_every))
        self._buf: list[str] = []
        self._written = 0
        self._rejected = 0
        self._fh = None
        self._finalized = False
        self._lock = threading.Lock()

    def _open(self) -> None:
        if self._fh is None:
            self._fh = open(self.path, "a", encoding="utf-8")

    def _validate(self, rec: dict) -> tuple[bool, str]:
        if not isinstance(rec, dict):
            return False, f"not a dict: {type(rec).__name__}"
        for f in self.required_fields:
            if f not in rec or rec.get(f) in (None, ""):
                return False, f"missing required field: {f}"
        return True, ""

    def write(self, records: Iterable[dict]) -> int:
        """Append a batch. Returns count successfully buffered."""
        written = 0
        with self._lock:
            self._open()
            for rec in records:
                ok, why = self._validate(rec)
                if not ok:
                    self._rejected += 1
                    log.warning(f"BatchWriter: dropping record ({why})")
                    continue
                self._buf.append(json.dumps(rec, ensure_ascii=False))
                written += 1
                if len(self._buf) >= self.flush_every:
                    self._flush_locked()
        self._written += written
        return written

    def _flush_locked(self) -> None:
        if not self._buf:
            return
        assert self._fh is not None
        self._fh.write("\n".join(self._buf) + "\n")
        self._fh.flush()
        self._buf.clear()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def finalize(self) -> Path:
        """Flush buffered records and close the file."""
        with self._lock:
            self._flush_locked()
            if self._fh is not None:
                self._fh.close()
                self._fh = None
            self._finalized = True
        log.info(f"BatchWriter[{self.path.name}]: wrote {self._written} records, "
                 f"rejected {self._rejected}")
        return self.path

    # Context-manager support (GPT-5.4 review fix 3) — guarantees flush.
    def __enter__(self) -> "BatchWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.finalize()

    def __del__(self) -> None:
        """Defensive finalizer. Warns and flushes if finalize() wasn't
        called (e.g. caller forgot or crashed). Best-effort only —
        raising from __del__ is unsafe, so we warn via warnings module
        and log.
        """
        # __init__ may not have set these if construction failed partway.
        try:
            finalized = bool(getattr(self, "_finalized", True))
            buf       = getattr(self, "_buf", None)
            fh        = getattr(self, "_fh", None)
        except Exception:
            return
        if finalized:
            return
        if buf or fh is not None:
            msg = (f"BatchWriter[{getattr(self, 'path', '?')}] garbage-collected "
                   f"without finalize(); {len(buf) if buf else 0} buffered records "
                   f"salvaged via __del__. Use `with BatchWriter(...) as bw:` or "
                   f"call .finalize() explicitly.")
            try:
                warnings.warn(msg, ResourceWarning, stacklevel=2)
                log.warning(msg)
            except Exception:
                pass
            try:
                self.finalize()
            except Exception:
                pass

    @property
    def stats(self) -> dict:
        return {"written": self._written, "rejected": self._rejected, "path": str(self.path)}


# ─────────────────────────────────────────────────────────────────────────────
# 6. SuperNodeFilter
# ─────────────────────────────────────────────────────────────────────────────

class SuperNodeFilter:
    """Count node degrees and flag super-nodes (degree > threshold).

    Typical usage:
        snf = SuperNodeFilter(threshold=500)
        for edge in edges:
            snf.add_edge(edge.source); snf.add_edge(edge.target)
        universals = snf.universals()   # -> set of node_ids
        # Downstream: tag these nodes with :Universal label in Neo4j
    """

    def __init__(self, threshold: int = 500):
        self.threshold = int(threshold)
        self._degree: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def add_edge(self, node_id: str, weight: int = 1) -> None:
        if not node_id:
            return
        with self._lock:
            self._degree[node_id] += weight

    def add_edges(self, pairs: Iterable[tuple[str, str]]) -> None:
        with self._lock:
            for u, v in pairs:
                if u:
                    self._degree[u] += 1
                if v:
                    self._degree[v] += 1

    def degree(self, node_id: str) -> int:
        return self._degree.get(node_id, 0)

    def is_super(self, node_id: str) -> bool:
        return self.degree(node_id) > self.threshold

    def universals(self) -> set[str]:
        return {n for n, d in self._degree.items() if d > self.threshold}

    def top(self, n: int = 20) -> list[tuple[str, int]]:
        return sorted(self._degree.items(), key=lambda kv: -kv[1])[:n]

    def dump(self, out_path: str | Path) -> Path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_ts":        _ts(),
            "threshold":  self.threshold,
            "universals": sorted(self.universals()),
            "top_20":     self.top(20),
            "total_nodes": len(self._degree),
        }
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(out)
        return out


# ─────────────────────────────────────────────────────────────────────────────
# 7. ConflictResolver
# ─────────────────────────────────────────────────────────────────────────────

class ConflictResolver:
    """Pick the winning value when multiple sources disagree.

    Default priorities (D023 §7):
        usda      1.00
        foodb     0.90
        textbook  0.85
        video     0.70
        web       0.60

    `resolve()` accepts a list of candidate dicts, each expected to
    contain `source` and whatever payload fields the caller needs. The
    returned dict is the highest-priority one (ties broken by
    candidate-local `confidence` if present, else input order).
    """

    DEFAULT_PRIORITY: dict[str, float] = {
        "usda":     1.00,
        "usda_fdc": 1.00,
        "foodb":    0.90,
        "textbook": 0.85,
        "video":    0.70,
        "web":      0.60,
        "default":  0.50,
    }

    def __init__(self, priority: dict[str, float] | None = None):
        self.priority: dict[str, float] = dict(self.DEFAULT_PRIORITY)
        if priority:
            self.priority.update(priority)

    def source_confidence(self, source: str | None) -> float:
        if not source:
            return self.priority.get("default", 0.5)
        return self.priority.get(source, self.priority.get("default", 0.5))

    def resolve(self, candidates: list[dict]) -> dict | None:
        """Return the winning candidate dict, or None when empty."""
        if not candidates:
            return None
        best: tuple[float, float, int, dict] | None = None
        for idx, c in enumerate(candidates):
            src_conf = self.source_confidence(c.get("source"))
            local_conf = c.get("confidence", 0.0)
            try:
                local_conf_f = float(local_conf)
            except (TypeError, ValueError):
                local_conf_f = 0.0
            # We prefer HIGHER source_conf, then HIGHER local_conf, then earlier idx
            key = (src_conf, local_conf_f, -idx)
            if best is None or key > best[:3]:
                best = (key[0], key[1], key[2], c)
        return best[3] if best else None

    def rank(self, candidates: list[dict]) -> list[dict]:
        """Return candidates sorted by priority descending."""
        def _key(c: dict) -> tuple[float, float]:
            try:
                lc = float(c.get("confidence", 0.0))
            except (TypeError, ValueError):
                lc = 0.0
            return (-self.source_confidence(c.get("source")), -lc)
        return sorted(candidates, key=_key)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
