import os

for _proxy_key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_proxy_key, None)

import argparse
import sys
from pathlib import Path

from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.solver import mf_t01  # noqa: E402


URI = "bolt://localhost:7687"
AUTH = ("neo4j", "cmind_p1_33_proto")
OUTPUT_PATH = ROOT / "prototype" / "_smoke_test_output.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P1-33 Neo4j end-to-end smoke test.")
    parser.add_argument("--query", default="chicken + heating scenario")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def fetch_one(session, query: str, **params):
    record = session.run(query, **params).single()
    return dict(record) if record else None


def solve_temp(time_s: float) -> float:
    result = mf_t01.solve(
        {
            "T_init": 20.0,
            "T_boundary": 180.0,
            "alpha": 1.4e-7,
            "x_position": 0.005,
            "time": time_s,
            "thickness": 0.03,
        }
    )
    return float(result["result"]["value"])


def time_to_target(target_c: float) -> float:
    lo = 0.0
    hi = 7200.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if solve_temp(mid) >= target_c:
            hi = mid
        else:
            lo = mid
    return hi / 60.0


def main() -> None:
    args = parse_args()
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        with driver.session(database="neo4j") as session:
            ingredient = fetch_one(
                session,
                """
                MATCH (i:CKG_Ingredient {name_en: 'chicken'})
                RETURN i.id AS id, i.name_en AS name_en, i.name_zh AS name_zh
                """,
            )
            if not ingredient:
                raise SystemExit("Missing CKG_Ingredient chicken seed.")

            l0_paths = session.run(
                """
                MATCH (l0:CKG_L0_Principle)-[:EXHIBITS_PHENOMENON]->(phn:CKG_PHN)
                WHERE l0.scientific_statement CONTAINS 'chicken'
                   OR l0.scientific_statement CONTAINS '鸡肉'
                   OR l0.scientific_statement CONTAINS '烤鸡'
                   OR l0.scientific_statement CONTAINS '禽类'
                RETURN l0.id AS l0_id,
                       l0.scientific_statement AS statement,
                       phn.phn_id AS phn_id,
                       phn.name_en AS phn_name
                ORDER BY
                  CASE phn.phn_id
                    WHEN 'phn_maillard_browning' THEN 0
                    WHEN 'phn_thermal_protein_denaturation' THEN 1
                    ELSE 2
                  END,
                  l0.confidence DESC
                LIMIT 8
                """
            )
            path_rows = [dict(row) for row in l0_paths]
            if not path_rows:
                raise SystemExit("Missing chicken L0 -> PHN path. Run import_l0.py first.")

            maillard_l0 = next((row for row in path_rows if row["phn_id"] == "phn_maillard_browning"), None)
            protein_l0 = next(
                (row for row in path_rows if row["phn_id"] == "phn_thermal_protein_denaturation"),
                None,
            )
            if maillard_l0 is None:
                maillard_l0 = fetch_one(
                    session,
                    """
                    MATCH (l0:CKG_L0_Principle)-[:EXHIBITS_PHENOMENON]->(phn:CKG_PHN {phn_id: 'phn_maillard_browning'})
                    WHERE l0.scientific_statement CONTAINS 'chicken'
                       OR l0.scientific_statement CONTAINS '鸡肉'
                       OR l0.scientific_statement CONTAINS '烤鸡'
                    RETURN l0.id AS l0_id, l0.scientific_statement AS statement, phn.phn_id AS phn_id, phn.name_en AS phn_name
                    LIMIT 1
                    """,
                )
            if protein_l0 is None:
                protein_l0 = fetch_one(
                    session,
                    """
                    MATCH (l0:CKG_L0_Principle)-[:EXHIBITS_PHENOMENON]->(phn:CKG_PHN {phn_id: 'phn_thermal_protein_denaturation'})
                    WHERE l0.scientific_statement CONTAINS 'chicken'
                       OR l0.scientific_statement CONTAINS '鸡肉'
                       OR l0.scientific_statement CONTAINS '烤鸡'
                    RETURN l0.id AS l0_id, l0.scientific_statement AS statement, phn.phn_id AS phn_id, phn.name_en AS phn_name
                    LIMIT 1
                    """,
                )
            if maillard_l0 is None:
                raise SystemExit("Missing chicken -> maillard L0 path.")

            tool_path = fetch_one(
                session,
                """
                MATCH (phn:CKG_PHN {phn_id: 'phn_maillard_browning'})
                      -[:GOVERNED_BY_MF]->(mf:CKG_MF)
                      -[:IMPLEMENTED_BY]->(tool:CKG_ToolFunction)
                RETURN phn.phn_id AS phn_id,
                       phn.name_en AS phn_name,
                       mf.mf_id AS mf_id,
                       mf.canonical_name AS mf_name,
                       tool.tool_id AS tool_id,
                       tool.name AS tool_name
                LIMIT 1
                """,
            )
            if not tool_path:
                raise SystemExit("Missing PHN -> MF -> ToolFunction path.")

    temp_at_depth = solve_temp(120.0)
    minutes_to_70 = time_to_target(70.0)
    protein_statement = protein_l0["statement"] if protein_l0 else "No protein denaturation L0 matched for chicken subset."
    if temp_at_depth >= 70.0:
        endpoint_text = (
            f"0.5cm 深处约 {temp_at_depth:.2f} C，已高于 70C 安全终点；"
            f"按同一 Fourier_1D 假设约 {minutes_to_70:.1f} 分钟达到 70C。"
        )
    else:
        endpoint_text = (
            f"0.5cm 深处约 {temp_at_depth:.2f} C，仍低于 70C 安全终点，"
            f"按同一 Fourier_1D 假设约需 {minutes_to_70:.1f} 分钟达到 70C。"
        )

    lines = [
        "# P1-33 Neo4j Smoke Test",
        "",
        f"Query: {args.query}",
        "Scenario: chicken + pan-sear @ 180C, 2 min",
        "Cooking method: pan-sear",
        "",
        "Path: chicken -> cooking_method(pan-sear) -> "
        f"L0({maillard_l0['l0_id']}) -> PHN(maillard_browning) -> "
        f"L0(protein_denaturation: {protein_l0['l0_id'] if protein_l0 else 'missing'}) -> "
        f"MF({tool_path['mf_name']}) -> Tool(mf_t01) -> 推理答案",
        "",
        f"Maillard L0: {maillard_l0['statement']}",
        f"Protein denaturation L0: {protein_statement}",
        f"PHN: {tool_path['phn_id']} / {tool_path['phn_name']}",
        f"MF: {tool_path['mf_id']} / {tool_path['mf_name']}",
        f"Tool: {tool_path['tool_id']} / {tool_path['tool_name']}",
        f"Tool result: T(0.5cm depth, t=120s) = {temp_at_depth:.2f} C",
        "",
        "Inference: 鸡肉表面接近 180C 时可触发 Maillard 反应；" + endpoint_text,
    ]
    if args.verbose:
        lines.append("")
        lines.append("Verbose candidate rows:")
        for row in path_rows:
            lines.append(f"- {row['l0_id']} -> {row['phn_id']}: {row['statement'][:120]}")

    output = "\n".join(lines) + "\n"
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
