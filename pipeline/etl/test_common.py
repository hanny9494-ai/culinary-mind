"""Unit tests for pipeline.etl.common.

Run:
    /Users/jeff/miniforge3/bin/python3 -m pytest pipeline/etl/test_common.py -v
or:
    /Users/jeff/miniforge3/bin/python3 pipeline/etl/test_common.py
"""
from __future__ import annotations

import json
import math
import tempfile
import unittest
import warnings
from pathlib import Path

from pipeline.etl.common import (
    BatchWriter,
    CanonicalMatcher,
    CompoundRegistry,
    ConflictResolver,
    CrossKeyConflictError,
    ExternalIdRegistry,
    SuperNodeFilter,
    UnitNormalizer,
    WeakNameMergeError,
)


# Synthetic canonical_map fixture so tests don't depend on the real registry
_FAKE_CANONICALS = [
    {
        "canonical_id":      "tomato",
        "canonical_name_en": "tomato",
        "canonical_name_zh": "番茄",
        "category":          "vegetable",
        "confidence":        "high",
        "raw_variants":      ["tomato", "tomatoes", "fresh tomato"],
        "external_ids":      {},
    },
    {
        "canonical_id":      "garlic",
        "canonical_name_en": "garlic",
        "canonical_name_zh": "大蒜",
        "category":          "vegetable",
        "confidence":        "high",
        "raw_variants":      ["garlic", "garlic cloves"],
        "external_ids":      {},
    },
    {
        "canonical_id":      "black_pepper",
        "canonical_name_en": "black pepper",
        "canonical_name_zh": "黑胡椒",
        "category":          "spice",
        "confidence":        "high",
        "raw_variants":      ["black pepper", "ground black pepper"],
        "external_ids":      {},
    },
]
_FAKE_RAW_TO_CANONICAL = {
    "tomato":              "tomato",
    "tomatoes":            "tomato",
    "fresh tomato":        "tomato",
    "garlic":              "garlic",
    "garlic cloves":       "garlic",
    "black pepper":        "black_pepper",
    "ground black pepper": "black_pepper",
    "番茄":                "tomato",
}


def _write_fake_canonical_map(path: Path) -> None:
    payload = {
        "metadata":         {"fixture": True},
        "canonicals":       _FAKE_CANONICALS,
        "raw_to_canonical": _FAKE_RAW_TO_CANONICAL,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# CanonicalMatcher
# ─────────────────────────────────────────────────────────────────────────────

class TestCanonicalMatcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        self.tmp.close()
        _write_fake_canonical_map(Path(self.tmp.name))
        self.m = CanonicalMatcher(self.tmp.name)

    def test_exact_match(self):
        self.assertEqual(self.m.match("tomato"), "tomato")
        self.assertEqual(self.m.match("garlic cloves"), "garlic")

    def test_case_and_whitespace(self):
        self.assertEqual(self.m.match("  Tomato  "), "tomato")
        self.assertEqual(self.m.match("TOMATO"), "tomato")
        self.assertEqual(self.m.match("tomato."), "tomato")

    def test_zh_match(self):
        self.assertEqual(self.m.match("番茄", lang="zh"), "tomato")

    def test_modifier_strip_fallback(self):
        # 'chopped tomato' not in raw index but modifier strip → 'tomato' hits
        self.assertEqual(self.m.match("chopped tomato"), "tomato")
        self.assertEqual(self.m.match("freshly chopped garlic"), "garlic")

    def test_unknown_returns_none(self):
        self.assertIsNone(self.m.match("zebra meat"))
        self.assertIsNone(self.m.match(""))
        self.assertIsNone(self.m.match(None))

    def test_register_new(self):
        cid = self.m.register_new("durian", "榴莲", "fruit")
        self.assertEqual(cid, "durian")
        self.assertEqual(self.m.match("durian"), "durian")
        self.assertEqual(self.m.match("榴莲", lang="zh"), "durian")

    def test_register_existing_returns_same_id(self):
        cid1 = self.m.register_new("tomato sauce", "", "condiment")
        cid2 = self.m.register_new("tomato sauce", "", "condiment")
        self.assertEqual(cid1, cid2)


# ─────────────────────────────────────────────────────────────────────────────
# CompoundRegistry
# ─────────────────────────────────────────────────────────────────────────────

class TestCompoundRegistry(unittest.TestCase):
    def test_register_and_match_pubchem(self):
        r = CompoundRegistry()
        cid = r.register({"pubchem_id": "702", "name": "Ethanol"})
        self.assertTrue(cid.startswith("cmpd_"))
        # Later match by pubchem alone should hit
        self.assertEqual(r.match({"pubchem_id": "702"}), cid)

    def test_cascade_match(self):
        r = CompoundRegistry()
        cid = r.register({
            "pubchem_id":       "702",
            "cas_number":       "64-17-5",
            "canonical_smiles": "CCO",
            "name":             "Ethanol",
        })
        # Match by cas alone
        self.assertEqual(r.match({"cas_number": "64-17-5"}), cid)
        # Match by smiles alone
        self.assertEqual(r.match({"canonical_smiles": "CCO"}), cid)
        # Match by normalized_name alone
        self.assertEqual(r.match({"name": "Ethanol"}), cid)
        self.assertEqual(r.match({"name": "ETHANOL "}), cid)   # case/ws

    def test_register_merges_missing_keys(self):
        r = CompoundRegistry()
        cid = r.register({"pubchem_id": "702", "name": "Ethanol"})
        # Re-register with cas → should merge, not create new
        cid2 = r.register({"pubchem_id": "702", "cas_number": "64-17-5"})
        self.assertEqual(cid, cid2)
        self.assertEqual(r.match({"cas_number": "64-17-5"}), cid)

    def test_new_compound_no_keys_returns_none(self):
        r = CompoundRegistry()
        self.assertIsNone(r.match({"pubchem_id": "unknown"}))

    # ── GPT-5.4 review fix 1: weak name-only match safety ──────────────
    def test_weak_name_match_allowed_non_strict(self):
        """In non-strict mode, matching only by normalized_name still
        succeeds (current default behaviour preserved)."""
        r = CompoundRegistry()
        cid = r.register({"pubchem_id": "702", "name": "Ethanol"})
        # Only name match — no pubchem/cas/smiles overlap
        hit = r.match({"name": "Ethanol"})
        self.assertEqual(hit, cid)

    def test_weak_name_match_rejected_strict(self):
        """In strict mode, name-only hits raise WeakNameMergeError."""
        r = CompoundRegistry()
        r.register({"pubchem_id": "702", "name": "Ethanol"})
        with self.assertRaises(WeakNameMergeError):
            r.match({"name": "Ethanol"}, strict=True)

    def test_strong_key_match_allowed_strict(self):
        """Strict mode still works fine when strong keys match."""
        r = CompoundRegistry()
        cid = r.register({"pubchem_id": "702", "cas_number": "64-17-5",
                          "name": "Ethanol"})
        self.assertEqual(r.match({"pubchem_id": "702"}, strict=True), cid)
        self.assertEqual(r.match({"cas_number": "64-17-5"}, strict=True), cid)

    def test_register_strict_refuses_weak_merge(self):
        """register(strict=True) doesn't silently merge by name alone."""
        r = CompoundRegistry()
        r.register({"pubchem_id": "702", "name": "Ethanol"})
        with self.assertRaises(WeakNameMergeError):
            # Same-name different-source record — strict refuses to merge
            r.register({"name": "Ethanol", "source": "foodb"}, strict=True)

    # ── GPT-5.4 review fix 2: cross-key conflict detection ─────────────
    def test_cross_key_conflict_on_match(self):
        """pubchem → A, cas → B (different compound_ids) must raise."""
        r = CompoundRegistry()
        cid_a = r.register({"pubchem_id": "702", "name": "Ethanol"})
        cid_b = r.register({"cas_number": "64-17-5", "name": "Another"})
        self.assertNotEqual(cid_a, cid_b)
        # A probe that would "win" by pubchem but also hit B by cas:
        with self.assertRaises(CrossKeyConflictError):
            r.match({"pubchem_id": "702", "cas_number": "64-17-5"})

    def test_cross_key_conflict_on_register(self):
        """register() must also refuse cross-key conflicts."""
        r = CompoundRegistry()
        r.register({"pubchem_id": "702"})
        r.register({"cas_number": "64-17-5"})
        with self.assertRaises(CrossKeyConflictError):
            r.register({"pubchem_id": "702", "cas_number": "64-17-5"})

    def test_cross_key_no_conflict_when_same_id(self):
        """Same id via two keys is fine (expected merge path)."""
        r = CompoundRegistry()
        cid = r.register({"pubchem_id": "702", "cas_number": "64-17-5",
                          "name": "Ethanol"})
        # Every probe key points to the same cid → no conflict
        self.assertEqual(r.match({"pubchem_id": "702",
                                  "cas_number": "64-17-5"}), cid)

    # ── Double-review follow-up edge cases ──────────────────────────────
    def test_mixed_strong_plus_weak_name_strict_ok(self):
        """strict=True with (existing strong key + name) still succeeds —
        the strong key carries the match, name is merely consistent."""
        r = CompoundRegistry()
        cid = r.register({"pubchem_id": "702", "name": "Ethanol"})
        # probe has strong key + the same name — strong match dominates
        self.assertEqual(
            r.match({"pubchem_id": "702", "name": "Ethanol"}, strict=True),
            cid,
        )

    def test_three_way_cross_key_conflict(self):
        """pubchem → A, cas → B, smiles → C: three-way conflict still raises."""
        r = CompoundRegistry()
        r.register({"pubchem_id": "702"})
        r.register({"cas_number": "64-17-5"})
        r.register({"canonical_smiles": "CCO"})
        with self.assertRaises(CrossKeyConflictError):
            r.match({"pubchem_id": "702",
                     "cas_number": "64-17-5",
                     "canonical_smiles": "CCO"})

    def test_empty_and_none_values_do_not_index(self):
        """Empty strings / None must not hit the index or pollute it."""
        r = CompoundRegistry()
        r.register({"pubchem_id": "702", "name": "Ethanol"})
        # None-only probe should not match
        self.assertIsNone(r.match({"pubchem_id": None}))
        self.assertIsNone(r.match({"cas_number": ""}))
        # Registering a record with blanks should not orphan-index them
        cid = r.register({"pubchem_id": "999", "cas_number": "",
                          "canonical_smiles": None, "name": "Novel"})
        self.assertTrue(cid.startswith("cmpd_"))
        # The blank keys did NOT get inserted — empty-string probe stays None
        self.assertIsNone(r.match({"cas_number": ""}))
        self.assertIsNone(r.match({"canonical_smiles": ""}))


# ─────────────────────────────────────────────────────────────────────────────
# UnitNormalizer
# ─────────────────────────────────────────────────────────────────────────────

class TestUnitNormalizer(unittest.TestCase):
    def setUp(self):
        self.u = UnitNormalizer()

    def test_composition_mg_kg(self):
        v, u = self.u.normalize(25, "mg/kg")
        self.assertAlmostEqual(v, 2.5)
        self.assertEqual(u, "mg/100g")

    def test_composition_percent(self):
        v, u = self.u.normalize(5, "%")
        self.assertAlmostEqual(v, 50000.0)
        self.assertEqual(u, "mg/100g")

    def test_composition_g_100g(self):
        v, u = self.u.normalize(2, "g/100g")
        self.assertAlmostEqual(v, 2000.0)
        self.assertEqual(u, "mg/100g")

    def test_composition_unconvertible(self):
        v, u = self.u.normalize(1, "mmol/100g")   # needs MW, marked unconvertible
        self.assertIsNone(v)
        self.assertEqual(u, "unconvertible")
        v, u = self.u.normalize("abc", "mg/kg")
        self.assertIsNone(v)

    def test_temperature(self):
        v, u = self.u.normalize_temperature(32, "F")
        self.assertAlmostEqual(v, 0.0)
        self.assertEqual(u, "C")
        v, u = self.u.normalize_temperature(273.15, "K")
        self.assertAlmostEqual(v, 0.0)
        v, u = self.u.normalize_temperature(100, "C")
        self.assertAlmostEqual(v, 100.0)

    def test_pressure(self):
        v, u = self.u.normalize_pressure(1, "bar")
        self.assertAlmostEqual(v, 100.0)
        self.assertEqual(u, "kPa")
        v, u = self.u.normalize_pressure(1, "atm")
        self.assertTrue(math.isclose(v, 101.325, rel_tol=1e-3))
        v, u = self.u.normalize_pressure(1, "psi")
        self.assertTrue(math.isclose(v, 6.89476, rel_tol=1e-3))

    # ── P1-03 enforce_si ────────────────────────────────────────────────
    def test_enforce_si_temperature(self):
        v, u = self.u.enforce_si(350, "F")
        self.assertTrue(math.isclose(v, 176.666, rel_tol=1e-3))
        self.assertEqual(u, "C")

    def test_enforce_si_pressure(self):
        v, u = self.u.enforce_si(1, "psi")
        self.assertTrue(math.isclose(v, 6.89476, rel_tol=1e-3))
        self.assertEqual(u, "kPa")

    def test_enforce_si_energy(self):
        v, u = self.u.enforce_si(1, "BTU")
        self.assertTrue(math.isclose(v, 1055.056, rel_tol=1e-3))
        self.assertEqual(u, "J")
        v, u = self.u.enforce_si(1, "kcal")
        self.assertTrue(math.isclose(v, 4184.0))

    def test_enforce_si_volume(self):
        v, u = self.u.enforce_si(1, "cup")
        self.assertTrue(math.isclose(v, 236.588, rel_tol=1e-3))
        self.assertEqual(u, "mL")
        v, u = self.u.enforce_si(1, "tbsp")
        self.assertTrue(math.isclose(v, 14.7868, rel_tol=1e-3))

    def test_enforce_si_length(self):
        v, u = self.u.enforce_si(1, "inch")
        self.assertAlmostEqual(v, 0.0254)
        self.assertEqual(u, "m")

    def test_enforce_si_mass(self):
        v, u = self.u.enforce_si(1, "lb")
        self.assertAlmostEqual(v, 453.592)
        self.assertEqual(u, "g")

    def test_enforce_si_time(self):
        v, u = self.u.enforce_si(1, "h")
        self.assertEqual(v, 3600.0)
        self.assertEqual(u, "s")

    def test_enforce_si_explicit_family(self):
        """quantity_type hint overrides ambiguous-unit inference."""
        v, u = self.u.enforce_si(1, "mg", quantity_type="mass")
        self.assertAlmostEqual(v, 0.001)
        self.assertEqual(u, "g")

    def test_enforce_si_unknown_nonstrict_returns_none(self):
        v, u = self.u.enforce_si(1, "parsec")
        self.assertIsNone(v)
        self.assertEqual(u, "unconvertible")

    def test_enforce_si_unknown_strict_raises(self):
        with self.assertRaises(ValueError):
            self.u.enforce_si(1, "parsec", strict=True)


# ─────────────────────────────────────────────────────────────────────────────
# ExternalIdRegistry
# ─────────────────────────────────────────────────────────────────────────────

class TestExternalIdRegistry(unittest.TestCase):
    def test_link_and_get(self):
        r = ExternalIdRegistry()
        r.link("tomato", "usda_fdc", "170457")
        r.link("tomato", "foodb",    "FOOD00021")
        got = r.get_linked("tomato")
        self.assertEqual(got, {"usda_fdc": "170457", "foodb": "FOOD00021"})

    def test_multi_link_same_source_becomes_list(self):
        r = ExternalIdRegistry()
        r.link("tomato", "foodb", "FOOD00021")
        r.link("tomato", "foodb", "FOOD00099")
        got = r.get_linked("tomato")
        self.assertIsInstance(got["foodb"], list)
        self.assertIn("FOOD00021", got["foodb"])
        self.assertIn("FOOD00099", got["foodb"])

    def test_dump(self):
        r = ExternalIdRegistry()
        r.link("tomato", "usda_fdc", "170457")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "external_ids.json"
            r.dump(out)
            data = json.loads(out.read_text())
            self.assertEqual(data["external_ids"]["tomato"]["usda_fdc"], "170457")


# ─────────────────────────────────────────────────────────────────────────────
# BatchWriter
# ─────────────────────────────────────────────────────────────────────────────

class TestBatchWriter(unittest.TestCase):
    def test_write_and_finalize(self):
        with tempfile.TemporaryDirectory() as td:
            bw = BatchWriter(layer="l2a", source="test_src",
                             output_dir=td, flush_every=2,
                             required_fields=("id", "name"))
            n = bw.write([{"id": "1", "name": "a"}, {"id": "2", "name": "b"}])
            self.assertEqual(n, 2)
            # record missing 'name' → rejected
            n = bw.write([{"id": "3"}])
            self.assertEqual(n, 0)
            path = bw.finalize()
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            recs = [json.loads(l) for l in lines]
            self.assertEqual(recs[0]["name"], "a")
            self.assertEqual(bw.stats["written"], 2)
            self.assertEqual(bw.stats["rejected"], 1)

    # ── GPT-5.4 review fix 3: context manager + __del__ safety net ────
    def test_context_manager_auto_finalizes(self):
        """`with BatchWriter(...) as bw:` flushes on exit."""
        with tempfile.TemporaryDirectory() as td:
            with BatchWriter(layer="l2a", source="test_ctx",
                             output_dir=td, flush_every=100) as bw:
                bw.write([{"id": "1", "name": "a"}])
                bw.write([{"id": "2", "name": "b"}])
                # Nothing has been flushed yet (flush_every=100 not hit)
                self.assertEqual(bw._buf_len_for_test(), 2) if hasattr(bw, "_buf_len_for_test") else None
            # After context exit, records must be on disk
            out = Path(td) / "etl_staging" / "l2a" / "test_ctx.jsonl"
            self.assertTrue(out.exists())
            self.assertEqual(len(out.read_text().splitlines()), 2)

    def test_context_manager_exception_still_flushes(self):
        """Even if the `with` block raises, finalize still runs."""
        with tempfile.TemporaryDirectory() as td:
            class _Boom(Exception):
                pass
            try:
                with BatchWriter(layer="l2a", source="test_exc",
                                 output_dir=td, flush_every=100) as bw:
                    bw.write([{"id": "1", "name": "only"}])
                    raise _Boom("simulated crash")
            except _Boom:
                pass
            out = Path(td) / "etl_staging" / "l2a" / "test_exc.jsonl"
            self.assertTrue(out.exists())
            self.assertEqual(len(out.read_text().splitlines()), 1)

    def test_del_warns_and_salvages_unflushed(self):
        """Dropping a BatchWriter without finalize warns + salvages."""
        import gc
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "etl_staging" / "l2a" / "test_del.jsonl"
            bw = BatchWriter(layer="l2a", source="test_del",
                             output_dir=td, flush_every=100)
            bw.write([{"id": "1", "name": "never_flushed"}])
            # Do NOT finalize. Drop ref and GC.
            with warnings.catch_warnings(record=True) as wlist:
                warnings.simplefilter("always")
                del bw
                gc.collect()
                matched = [w for w in wlist
                           if issubclass(w.category, ResourceWarning)]
                self.assertTrue(matched,
                                f"expected ResourceWarning, got {wlist}")
            # __del__ should have salvaged the buffered record.
            self.assertTrue(out.exists())
            self.assertEqual(len(out.read_text().splitlines()), 1)


# ─────────────────────────────────────────────────────────────────────────────
# SuperNodeFilter
# ─────────────────────────────────────────────────────────────────────────────

class TestSuperNodeFilter(unittest.TestCase):
    def test_threshold_detection(self):
        s = SuperNodeFilter(threshold=3)
        for _ in range(5):
            s.add_edge("water")
        for _ in range(2):
            s.add_edge("saffron")
        self.assertTrue(s.is_super("water"))
        self.assertFalse(s.is_super("saffron"))
        self.assertEqual(s.universals(), {"water"})

    def test_add_edges_pairs(self):
        s = SuperNodeFilter(threshold=1)
        s.add_edges([("a", "b"), ("a", "c"), ("b", "c")])
        self.assertEqual(s.degree("a"), 2)
        self.assertEqual(s.degree("b"), 2)
        self.assertEqual(s.degree("c"), 2)


# ─────────────────────────────────────────────────────────────────────────────
# ConflictResolver
# ─────────────────────────────────────────────────────────────────────────────

class TestConflictResolver(unittest.TestCase):
    def setUp(self):
        self.r = ConflictResolver()

    def test_usda_wins_over_foodb(self):
        cands = [
            {"source": "foodb", "value": 95.0, "confidence": 0.9},
            {"source": "usda",  "value": 94.52, "confidence": 1.0},
        ]
        winner = self.r.resolve(cands)
        self.assertEqual(winner["source"], "usda")

    def test_textbook_over_video(self):
        cands = [
            {"source": "video",    "value": 1},
            {"source": "textbook", "value": 2},
        ]
        self.assertEqual(self.r.resolve(cands)["source"], "textbook")

    def test_rank_order(self):
        cands = [
            {"source": "video",    "v": 1},
            {"source": "usda",     "v": 2},
            {"source": "textbook", "v": 3},
            {"source": "foodb",    "v": 4},
        ]
        ranked = self.r.rank(cands)
        self.assertEqual([c["source"] for c in ranked],
                         ["usda", "foodb", "textbook", "video"])

    def test_empty(self):
        self.assertIsNone(self.r.resolve([]))

    def test_unknown_source_uses_default(self):
        cands = [
            {"source": "mystery", "confidence": 0.99},
            {"source": "video"},
        ]
        # 'video' (0.70) > default (0.50), so video wins
        self.assertEqual(self.r.resolve(cands)["source"], "video")


if __name__ == "__main__":
    unittest.main(verbosity=2)
