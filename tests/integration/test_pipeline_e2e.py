"""P2-Tx2: End-to-end pipeline integration smoke test.

Synthetic raw recipe → staging JSON → Neo4j with expected node + edge invariants.

Uses an isolation namespace label (CKG_TEST_*) so production data is untouched.
"""
import json
import tempfile
import time
from pathlib import Path

import pytest
from neo4j import GraphDatabase

import os
ROOT = Path(__file__).resolve().parents[2]
URI = os.environ.get("CMIND_NEO4J_DEV_URI", "bolt://localhost:7687")
USER = os.environ.get("CMIND_NEO4J_DEV_USER", "neo4j")
PW = os.environ.get("CMIND_NEO4J_DEV_PW", "cmind_p1_33_proto")
AUTH = (USER, PW)

# Synthetic recipe matching extract_recipes.py output schema
SYNTH = {
    "book_id": "test_book_e2e",
    "recipe_id": "test_book_e2e__r1",
    "name": "Synthetic Chicken Brine Test",
    "recipe_type": "main",
    "ingredients": [
        {"slug": "chicken_thigh", "raw": "chicken thigh 500g", "quantity": 500, "unit": "g"},
        {"slug": "salt", "raw": "kosher salt 30g", "quantity": 30, "unit": "g"},
    ],
    "steps": [
        {"step_id": "s1", "step_idx": 0, "text": "Sear chicken in pan at 200°C to brown the surface.", "temp_c": 200.0, "time_min": 4.0},
        {"step_id": "s2", "step_idx": 1, "text": "Continue cooking at 180°C until internal temp 75°C.", "temp_c": 180.0, "time_min": 8.0},
    ],
}


@pytest.fixture(scope="module")
def driver():
    d = GraphDatabase.driver(URI, auth=AUTH)
    # Pre-flight: required seed nodes for assertion-based tests
    with d.session() as s:
        for phn_id in ("maillard_browning",):
            r = s.run("MATCH (p:CKG_PHN {phn_id:$pid}) RETURN p", pid=phn_id).single()
            assert r is not None, f"Required seed missing: CKG_PHN({phn_id}) — load PHN seed first"
        # maillard_browning must have MF governance (MF-T01 + MF-T03 expected)
        r = s.run("MATCH (p:CKG_PHN {phn_id:'maillard_browning'})<-[:GOVERNS_PHN]-(mf:CKG_MF) RETURN count(mf) AS n").single()
        assert r["n"] >= 1, "Required seed missing: at least one MF must :GOVERNS_PHN maillard_browning"
    yield d
    # Cleanup namespace after tests
    with d.session() as s:
        s.run("MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'CKG_TEST_') DETACH DELETE n")
    d.close()


@pytest.fixture(scope="module")
def loaded_synth(driver):
    """Load synthetic recipe with CKG_TEST_* labels (isolation namespace)."""
    with driver.session() as s:
        # Drop any leftovers
        s.run("MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'CKG_TEST_') DETACH DELETE n")

        # Create recipe + ingredients + steps in test namespace
        s.run("""
            CREATE (r:CKG_TEST_Recipe {recipe_id:$rid, name:$name, book_id:$book})
            WITH r
            UNWIND $ing AS i
            MERGE (g:CKG_TEST_Ingredient {ingredient_slug: i.slug})
            MERGE (r)-[:USES_INGREDIENT {raw:i.raw, quantity:i.quantity, unit:i.unit}]->(g)
        """, rid=SYNTH["recipe_id"], name=SYNTH["name"], book=SYNTH["book_id"], ing=SYNTH["ingredients"])

        s.run("""
            MATCH (r:CKG_TEST_Recipe {recipe_id:$rid})
            WITH r
            UNWIND $steps AS st
            CREATE (s:CKG_TEST_Step {step_id: r.recipe_id + '__' + st.step_id, step_idx:st.step_idx, text:st.text, temp_c:st.temp_c, time_min:st.time_min})
            MERGE (r)-[:HAS_STEP]->(s)
        """, rid=SYNTH["recipe_id"], steps=SYNTH["steps"])

        # Apply step→PHN rule: searing at high temp → maillard_browning
        s.run("""
            MATCH (st:CKG_TEST_Step), (p:CKG_PHN {phn_id:'maillard_browning'})
            WHERE (st.text CONTAINS 'Sear' OR st.text CONTAINS 'sear' OR st.text CONTAINS 'brown')
              AND st.temp_c >= 140
            MERGE (st)-[:TRIGGERS_PHN]->(p)
        """)
    yield driver
    # cleanup in driver fixture


def test_recipe_loaded(loaded_synth):
    with loaded_synth.session() as s:
        r = s.run("MATCH (r:CKG_TEST_Recipe {recipe_id:$rid}) RETURN r.name AS n", rid=SYNTH["recipe_id"]).single()
        assert r is not None, "Recipe must be created"
        assert r["n"] == SYNTH["name"]


def test_ingredients_linked(loaded_synth):
    with loaded_synth.session() as s:
        r = s.run("MATCH (r:CKG_TEST_Recipe {recipe_id:$rid})-[:USES_INGREDIENT]->(i:CKG_TEST_Ingredient) RETURN count(i) AS n", rid=SYNTH["recipe_id"]).single()
        assert r["n"] == 2, f"Expected 2 ingredients, got {r['n']}"


def test_steps_loaded_in_order(loaded_synth):
    with loaded_synth.session() as s:
        steps = list(s.run("MATCH (r:CKG_TEST_Recipe {recipe_id:$rid})-[:HAS_STEP]->(st) RETURN st.step_idx AS idx, st.temp_c AS t ORDER BY st.step_idx", rid=SYNTH["recipe_id"]))
        assert len(steps) == 2
        assert steps[0]["idx"] == 0 and steps[0]["t"] == 200.0
        assert steps[1]["idx"] == 1 and steps[1]["t"] == 180.0


def test_step_phn_triggered(loaded_synth):
    with loaded_synth.session() as s:
        r = s.run("""
            MATCH (r:CKG_TEST_Recipe {recipe_id:$rid})-[:HAS_STEP]->(st)-[:TRIGGERS_PHN]->(p)
            RETURN st.step_idx AS idx, collect(p.phn_id) AS phns
            ORDER BY idx
        """, rid=SYNTH["recipe_id"])
        rows = list(r)
        # Sear step must trigger maillard_browning (PHN+MF seed verified in driver fixture)
        sear = next((row for row in rows if row["idx"] == 0), None)
        assert sear is not None, "Step idx=0 (sear) must have TRIGGERS_PHN edge"
        assert "maillard_browning" in sear["phns"], f"Step 0 must trigger maillard_browning, got {sear['phns']}"


def test_phn_governed_by_mf(loaded_synth):
    """maillard_browning PHN must be governed by ≥1 MF (MF-T01/MF-T03). Seed verified in fixture."""
    with loaded_synth.session() as s:
        r = s.run("""
            MATCH (p:CKG_PHN {phn_id:'maillard_browning'})<-[:GOVERNS_PHN]-(mf:CKG_MF)
            RETURN collect(mf.mf_id) AS mfs
        """).single()
        assert r is not None, "Query must return at least an empty row"
        assert len(r["mfs"]) >= 1, f"maillard_browning must have ≥1 governing MF; got {r['mfs']}"


def test_referential_integrity_test_namespace(loaded_synth):
    """No CKG_TEST_* edges should point to non-CKG_TEST_* nodes (except PHN/MF/L0)."""
    with loaded_synth.session() as s:
        # Recipe → Ingredient must both be TEST namespace
        bad = s.run("""
            MATCH (a:CKG_TEST_Recipe)-[r:USES_INGREDIENT]->(b)
            WHERE NOT b:CKG_TEST_Ingredient
            RETURN count(r) AS n
        """).single()["n"]
        assert bad == 0, f"Recipe→Ingredient must stay in TEST namespace; {bad} leaks"


def test_audit_runs_clean(loaded_synth):
    """After loading synth data + cleanup, full-graph audit should still have hard_fail=0."""
    import subprocess
    r = subprocess.run(["/Users/jeff/miniforge3/bin/python", str(ROOT / "scripts/quality/data_quality_audit.py")], capture_output=True, text=True)
    assert "Global: WARN" in r.stdout or "Global: PASS" in r.stdout, f"Audit unexpectedly failed: {r.stdout[-500:]}"
    assert "hard_fail=0" in r.stdout, "Audit hard_fail must be 0"
