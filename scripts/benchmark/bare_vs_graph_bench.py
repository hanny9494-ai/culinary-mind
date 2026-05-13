#!/usr/bin/env python3
"""P4-Be Benchmark: bare LLM vs +graph+tools (culinary-mind LLM agent).

Setup:
- Pipeline A (bare): Codex gpt-5.4 直接回答, 无 graph 无 tool
- Pipeline B (our agent): engine.agent.llm_agent.answer_query
                          (uses tool registry + Neo4j optional)

For each query:
  - Run A, save answer + tokens
  - Run B, save answer + tokens + which tools invoked
  - Compare side-by-side (manual or auto rubric)

Output: output/benchmark/bench_results.yaml
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.agent.llm_agent import answer_query as agent_answer

CODEX = ["codex", "exec", "--ephemeral", "--ignore-user-config",
         "--dangerously-bypass-approvals-and-sandbox", "-s", "read-only",
         "-m", "gpt-5.4", "-c", "model_reasoning_effort=low"]


def bare_llm(query, timeout=90):
    """Pipeline A: bare Codex, no system prompt, no tools."""
    t0 = time.time()
    proc = subprocess.run(
        CODEX + [query],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "NO_PROXY": "*"},
        stdin=subprocess.DEVNULL,
    )
    elapsed = time.time() - t0
    out = proc.stdout
    idx = out.rfind("\ncodex\n")
    if idx >= 0:
        body = out[idx+len("\ncodex\n"):]
        end = body.find("\ntokens used\n")
        # capture tokens used
        toks = 0
        if end > 0:
            tail = body[end:end+200]
            import re
            m = re.search(r"tokens used\s*(\d+)", tail)
            if m: toks = int(m.group(1))
            body = body[:end]
        return {"answer": body.strip(), "tokens": toks, "elapsed_s": round(elapsed, 1)}
    return {"answer": out.strip(), "tokens": 0, "elapsed_s": round(elapsed, 1)}


def graph_agent(query):
    """Pipeline B: our culinary-mind LLM agent."""
    t0 = time.time()
    result = agent_answer(query, verbose=False)
    elapsed = time.time() - t0
    return {
        "answer": result.get("answer", ""),
        "mf_id": result.get("mf_id"),
        "validity": result.get("validity"),
        "tool_value": result.get("result", {}).get("value"),
        "tool_unit": result.get("result", {}).get("unit"),
        "elapsed_s": round(elapsed, 1),
    }


# Benchmark queries — food science questions where bare LLM may hallucinate
# but tool-augmented should give precise numbers + citations
BENCH_QUERIES = [
    {
        "id": "Q1_arrhenius",
        "category": "kinetics",
        "query": "维生素 C 在 90°C 下的降解速率常数。已知前指因子 A=1e10 s⁻¹，活化能 Ea=80 kJ/mol。",
        "expected_value": 1.45e-2,  # k = 1e10·exp(-80000/(8.314·363)) ≈ 1.45e-2
        "expected_unit": "s⁻¹",
        "expected_tool": "MF-T03",
    },
    {
        "id": "Q2_protein_denat",
        "category": "thermal",
        "query": "蛋白质 T_d=65°C, dH=400 kJ/mol, 在 70°C 时 native fraction 是多少？",
        "expected_value": 0.072,  # sigmoid at T=Td+5°C with sigma=R·T_d²/dH ≈ steep
        "expected_unit": "dimensionless",
        "expected_tool": "MF-T06",
    },
    {
        "id": "Q3_fourier_beef",
        "category": "heat_transfer",
        "query": "5cm 厚牛肉块，初温 4°C，沸水 100°C 煮 30 分钟，中心温度估算多少？热扩散率 α=1.4e-7 m²/s。",
        "expected_value": 27.8,
        "expected_unit": "°C",
        "expected_tool": "MF-T01",
    },
    {
        "id": "Q4_choi_okos_water",
        "category": "thermal_props",
        "query": "纯水在 25°C 的比热容，用 Choi-Okos 模型估算。",
        "expected_value": 4180,
        "expected_unit": "J/(kg·K)",
        "expected_tool": "MF-T02-CP",
    },
    {
        "id": "Q5_water_density",
        "category": "thermal_props",
        "query": "纯水在 25°C 密度，用 Choi-Okos 估算。",
        "expected_value": 997,
        "expected_unit": "kg/m³",
        "expected_tool": "MF-T02-RHO",
    },
    {
        "id": "Q6_microwave",
        "category": "dielectric",
        "query": "2.45 GHz 微波，电场 E=2000 V/m，ε''=15，吸收功率密度多少？",
        "expected_value": 5.46e6,
        "expected_unit": "W/m³",
        "expected_tool": "MF-T07",
    },
    {
        "id": "Q7_pasteurization_F",
        "category": "food_safety",
        "query": "T=121.1°C 持续 5 分钟的 F 值（z=10°C）",
        "expected_value": 5.0,
        "expected_unit": "min",
        "expected_tool": "MF-K04",
    },
    {
        "id": "Q8_arrhenius_q10",
        "category": "kinetics",
        "query": "什么是 Q10 法则？计算 25°C 到 35°C 反应加速倍数（k1=1.0, k2=2.0）",
        "expected_value": 2.0,
        "expected_unit": "dimensionless",
        "expected_tool": "MF-C05",
    },
]


def main():
    out_dir = Path("/Users/jeff/culinary-mind/output/benchmark")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    print("=" * 90)
    print(f"P4-Bench: bare GPT 5.4 vs culinary-mind agent on {len(BENCH_QUERIES)} food science queries")
    print("=" * 90)

    for q in BENCH_QUERIES:
        print(f"\n[{q['id']}] {q['query'][:80]}...")
        print(f"  Expected: {q['expected_value']} {q['expected_unit']} via {q['expected_tool']}")

        # Pipeline A: bare
        print("  Running bare LLM...", end="", flush=True)
        bare_r = bare_llm(q["query"])
        print(f" {bare_r['elapsed_s']}s")

        # Pipeline B: our agent
        print("  Running culinary-mind agent...", end="", flush=True)
        agent_r = graph_agent(q["query"])
        print(f" {agent_r['elapsed_s']}s, tool={agent_r.get('mf_id', '-')}")

        # Score: tool match + value accuracy
        tool_match = agent_r.get("mf_id") == q["expected_tool"]
        v = agent_r.get("tool_value")
        if isinstance(v, (int, float)) and q["expected_value"]:
            dev_pct = abs(v - q["expected_value"]) / abs(q["expected_value"]) * 100
            value_close = dev_pct < 30
        else:
            dev_pct = None
            value_close = False

        results.append({
            "id": q["id"],
            "category": q["category"],
            "query": q["query"],
            "expected": {"value": q["expected_value"], "unit": q["expected_unit"], "tool": q["expected_tool"]},
            "bare_llm": bare_r,
            "graph_agent": agent_r,
            "scoring": {
                "tool_match": tool_match,
                "value_deviation_pct": dev_pct,
                "value_close_30pct": value_close,
            }
        })

    # Aggregate
    import yaml
    out_file = out_dir / "bench_bare_vs_graph.yaml"
    out_file.write_text(yaml.safe_dump({
        "version": "1.0",
        "generated_at": "2026-05-13",
        "n_queries": len(BENCH_QUERIES),
        "global": {
            "tool_match_rate": sum(1 for r in results if r["scoring"]["tool_match"]) / len(results),
            "value_close_30pct_rate": sum(1 for r in results if r["scoring"]["value_close_30pct"]) / len(results),
        },
        "results": results,
    }, allow_unicode=True, sort_keys=False))
    print()
    print("=" * 90)
    print("SUMMARY")
    print("=" * 90)
    print(f"  Tool match rate: {sum(1 for r in results if r['scoring']['tool_match'])} / {len(results)}")
    print(f"  Value close (<30%): {sum(1 for r in results if r['scoring']['value_close_30pct'])} / {len(results)}")
    print()
    print(f"{'Query':<25} {'Tool match':<11} {'Dev%':>7}  Bare LLM (truncated):")
    print(f"{'-'*25} {'-'*11} {'-'*7}")
    for r in results:
        tm = "✅" if r["scoring"]["tool_match"] else "❌"
        dp = r["scoring"]["value_deviation_pct"]
        dp_str = f"{dp:.1f}" if dp is not None else "-"
        bare_snip = (r["bare_llm"]["answer"] or "")[:50].replace("\n", " ")
        print(f"  {r['id']:<23} {tm:<11} {dp_str:>7}  {bare_snip}...")
    print(f"\n✅ {out_file}")


if __name__ == "__main__":
    main()
