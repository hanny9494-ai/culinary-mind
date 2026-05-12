#!/usr/bin/env python3
"""Advanced smoke test: Recipe → Step → PHN ← L0 (evidence) + MF (tool).

For a real recipe, walk:
  Recipe → Step → PHN  ← L0 (causal evidence)
                  ← MF (computational tool, invoked with step params)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.agent.tool_registry import get_mf_tool
from neo4j import GraphDatabase


def show_recipe(session, recipe_id):
    q_recipe = """
    MATCH (r:CKG_L2B_TMP_Recipe {recipe_id: $rid})
    OPTIONAL MATCH (r)-[:USES_INGREDIENT]->(ing:CKG_L2B_TMP_Ingredient)
    RETURN r.name AS name, r.book_id AS book, r.yield_text AS yield_text,
           collect(DISTINCT ing.item_raw)[..10] AS ingredients
    """
    return session.run(q_recipe, rid=recipe_id).single()


def get_full_chain(session, recipe_id):
    q = """
    MATCH (r:CKG_L2B_TMP_Recipe {recipe_id: $rid})-[:HAS_STEP]->(s:CKG_L2B_TMP_Step)
          -[:TRIGGERS_PHN]->(p:CKG_PHN)
    OPTIONAL MATCH (m:CKG_MF)-[:GOVERNS_PHN]->(p)
    OPTIONAL MATCH (l:CKG_L0_TMP_Principle)-[:TAGGED_BY_PHN]->(p)
    WITH s, p, collect(DISTINCT m.mf_id)[..3] AS mfs,
         collect(DISTINCT l.scientific_statement)[..2] AS l0_evidence,
         count(DISTINCT l) AS n_l0
    RETURN s.order AS order, s.text AS text, s.action AS action,
           s.temp_c AS temp_c, s.duration_min AS duration_min,
           p.phn_id AS phn,
           mfs, l0_evidence, n_l0
    ORDER BY s.order
    """
    return list(session.run(q, rid=recipe_id))


def find_richest_recipes(session, n=3):
    q = """
    MATCH (r:CKG_L2B_TMP_Recipe)-[:HAS_STEP]->(s:CKG_L2B_TMP_Step)
          -[:TRIGGERS_PHN]->(p:CKG_PHN)<-[:TAGGED_BY_PHN]-(l:CKG_L0_TMP_Principle)
    WHERE s.temp_c IS NOT NULL
    WITH r, count(DISTINCT s) AS n_steps, count(DISTINCT p) AS n_phn,
         count(DISTINCT l) AS n_l0_evidence
    WHERE n_steps >= 2 AND n_l0_evidence >= 5
    RETURN r.recipe_id AS recipe_id, r.name AS name, r.book_id AS book,
           n_steps, n_phn, n_l0_evidence
    ORDER BY n_l0_evidence DESC, n_steps DESC
    LIMIT $n
    """
    return list(session.run(q, n=n))


def invoke_with_step(mf_id, step):
    try:
        tool = get_mf_tool(mf_id)
    except KeyError: return None
    t = step.get("temp_c"); d = step.get("duration_min")
    params = None
    if mf_id == "MF-T03" and t is not None:
        params = {"A": 1e10, "Ea": 80000, "T_K": t + 273.15}
    elif mf_id == "MF-T06" and t is not None:
        params = {"T_d": 65, "dH_d": 400, "T_C": t}
    elif mf_id == "MF-T10" and t is not None and d is not None:
        params = {"T_C": t, "time": d*60, "A": 1e8, "Ea": 80000, "n": 1.5}
    elif mf_id == "MF-K02" and d is not None:
        params = {"t": d*60, "N0": 1e6, "N": 1.0}
    if params:
        out = tool.run(params)
        return out
    return None


def main():
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "cmind_p1_33_proto"))
    with driver.session() as sess:
        print("=" * 95)
        print("FULL-CHAIN SMOKE TEST: Recipe → Step → PHN ← {L0 evidence, MF tools}")
        print("=" * 95)
        print()
        recipes = find_richest_recipes(sess, 3)
        if not recipes:
            print("No recipes with L0+MF rich chain. Trying without L0 evidence filter.")
            return
        for r in recipes:
            print(f"\n### {r['name']} ({r['book']})")
            print(f"    {r['n_steps']} active steps × {r['n_phn']} PHNs × {r['n_l0_evidence']} L0 evidence")
            print("-" * 95)
            for row in get_full_chain(sess, r["recipe_id"]):
                print(f"\nStep {row['order']}: [{row['action']}] {row['temp_c']}°C × {row['duration_min']}min")
                print(f"  Text: {(row['text'] or '')[:100]}")
                print(f"  → PHN: {row['phn']}")
                if row['l0_evidence']:
                    print(f"  → L0 evidence ({row['n_l0']} statements):")
                    for ev in row['l0_evidence'][:2]:
                        print(f"    · {(ev or '')[:120]}")
                if row['mfs']:
                    print(f"  → MF tools available: {row['mfs']}")
                    for mf in row['mfs']:
                        out = invoke_with_step(mf, dict(row))
                        if out and out["validity"]["passed"]:
                            v = out["result"]["value"]; sym = out["result"]["symbol"]
                            print(f"    ✅ {mf} → {sym}={v:.3g} {out['result']['unit']}")
                        elif out:
                            print(f"    ⚠️  {mf} → {out['validity']['issues'][:1]}")
        print()
        print("=" * 95)
        print("✅ Full graph reasoning chain: Recipe ←→ Step ←→ PHN ←→ {L0, MF, solver}")
        print("=" * 95)
    driver.close()

if __name__ == "__main__":
    main()
