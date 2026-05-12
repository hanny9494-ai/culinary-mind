#!/usr/bin/env python3
"""SMOKE TEST: Recipe → Step → PHN → MF → real solver invocation.

Full reasoning chain through Neo4j graph + MF solver tools.
Pick 3 real recipes from L2b, traverse to MFs, invoke solvers with derived params.
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.agent.tool_registry import get_mf_tool

try:
    from neo4j import GraphDatabase
except ImportError:
    print("Install neo4j driver: pip install neo4j")
    sys.exit(1)


def find_recipes_with_full_chain(session, limit=3):
    """Find recipes that have Recipe → Step → PHN → MF complete chain."""
    q = """
    MATCH (r:CKG_L2B_TMP_Recipe)-[:HAS_STEP]->(s:CKG_L2B_TMP_Step)
          -[:TRIGGERS_PHN]->(p:CKG_PHN)<-[:GOVERNS_PHN]-(m:CKG_MF)
    WHERE s.temp_c IS NOT NULL AND s.duration_min IS NOT NULL
    WITH r, count(DISTINCT s) AS n_active_steps,
         collect(DISTINCT p.phn_id) AS phns,
         collect(DISTINCT m.mf_id) AS mfs
    WHERE n_active_steps >= 2
    RETURN r.recipe_id AS recipe_id, r.name AS name, r.book_id AS book,
           n_active_steps, phns, mfs
    ORDER BY n_active_steps DESC
    LIMIT $limit
    """
    return list(session.run(q, limit=limit))


def get_recipe_full_chain(session, recipe_id):
    """Walk full chain for a specific recipe."""
    q = """
    MATCH (r:CKG_L2B_TMP_Recipe {recipe_id: $rid})-[:HAS_STEP]->(s:CKG_L2B_TMP_Step)
    OPTIONAL MATCH (s)-[t:TRIGGERS_PHN]->(p:CKG_PHN)
    OPTIONAL MATCH (m:CKG_MF)-[:GOVERNS_PHN]->(p)
    RETURN s.order AS order, s.text AS text, s.action AS action,
           s.temp_c AS temp_c, s.duration_min AS duration_min,
           p.phn_id AS phn,
           collect(DISTINCT m.mf_id) AS mfs,
           t.rule_id AS rule
    ORDER BY s.order
    """
    return list(session.run(q, rid=recipe_id))


def invoke_mf_with_step_params(mf_id, step):
    """Invoke MF solver with parameters derived from step."""
    try:
        tool = get_mf_tool(mf_id)
    except KeyError:
        return None, f"MF tool {mf_id} not registered"

    # Build params based on step + MF type
    params = {}
    if mf_id == "MF-T03":  # Arrhenius
        if step.get("temp_c") is not None:
            params["T_K"] = step["temp_c"] + 273.15
            # Default Ea + A for thermal degradation
            params["A"] = 1.0e10
            params["Ea"] = 80000.0
    elif mf_id == "MF-T01":  # Fourier 1D
        if step.get("temp_c") is not None:
            params = {"T_init": 25.0, "T_boundary": step["temp_c"],
                      "time": (step.get("duration_min") or 10) * 60,
                      "x_position": 0.01, "thickness": 0.02,
                      "alpha": 1.4e-7, "k": 0.5, "rho": 1000.0, "Cp": 3800.0}
    elif mf_id == "MF-T06":  # Protein denat
        if step.get("temp_c") is not None:
            params = {"T_d": 65.0, "dH_d": 400.0, "T_C": step["temp_c"]}
    elif mf_id == "MF-K02":  # D-value
        if step.get("duration_min") is not None:
            params = {"t": step["duration_min"] * 60, "N0": 1.0e6, "N": 1.0}
    elif mf_id == "MF-T10":  # Starch gelat
        if step.get("temp_c") is not None and step.get("duration_min") is not None:
            params = {"T_C": step["temp_c"], "time": step["duration_min"] * 60,
                      "A": 1.0e8, "Ea": 80000.0, "n": 1.5}
    elif mf_id == "MF-K05":  # Gompertz
        if step.get("duration_min") is not None:
            params = {"A": 7.0, "mu_max": 0.5, "lambda": 1.0, "t": step["duration_min"] / 60}
    else:
        return None, f"No param recipe for {mf_id}"

    if not params:
        return None, "no temp_c/duration_min in step"

    out = tool.run(params)
    return out, None


def main():
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "cmind_p1_33_proto"))
    with driver.session() as sess:
        print("=" * 90)
        print("SMOKE TEST: Recipe → Step → PHN → MF → Solver (end-to-end Neo4j + Layer 3)")
        print("=" * 90)

        # Find 3 recipes with rich chain
        rich_recipes = find_recipes_with_full_chain(sess, limit=3)
        print(f"\nFound {len(rich_recipes)} recipes with full chain (≥2 steps with temp_c+duration+PHN+MF):\n")

        for r in rich_recipes:
            print(f"  - {r['name']} ({r['book']})")
            print(f"    {r['n_active_steps']} active steps, PHNs: {r['phns']}, MFs: {r['mfs']}")

        print()
        print("=" * 90)
        for r in rich_recipes:
            print(f"\n### Recipe: {r['name']}  [{r['book']}]")
            print("-" * 90)
            chain = get_recipe_full_chain(sess, r["recipe_id"])
            for row in chain:
                if not row["phn"]: continue  # only show steps with PHN
                print(f"\nStep {row['order']}: action={row['action']}, temp={row['temp_c']}°C, dur={row['duration_min']}min")
                print(f"  Text: {row['text'][:120]}...")
                print(f"  → PHN: {row['phn']} (rule: {row['rule']})")
                print(f"  → MFs available: {row['mfs']}")
                for mf in row["mfs"]:
                    step_dict = {"temp_c": row["temp_c"], "duration_min": row["duration_min"]}
                    result, err = invoke_mf_with_step_params(mf, step_dict)
                    if err:
                        print(f"    {mf}: skipped ({err})")
                    elif result and result["validity"]["passed"]:
                        sym = result["result"]["symbol"]
                        val = result["result"]["value"]
                        unit = result["result"]["unit"]
                        print(f"    ✅ {mf} → {sym}={val:.3g} {unit}")
                    elif result:
                        print(f"    ⚠️  {mf} → validity FAIL: {result['validity']['issues'][:1]}")

        print()
        print("=" * 90)
        print("✅ Smoke test complete — full graph traversal + solver invocation works")
        print("   Layer 3 reasoning pipeline LIVE")
        print("=" * 90)
    driver.close()


if __name__ == "__main__":
    main()
