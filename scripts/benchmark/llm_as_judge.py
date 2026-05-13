#!/usr/bin/env python3
"""P4-Bj1: LLM-as-Judge auto-scoring for benchmark answers.

For each (bare_answer, agent_answer) pair, ask a Codex judge to score:
- correctness (1-5)
- numerical_precision (1-5)
- citation_quality (1-5)
- clarity (1-5)

Pairs come from output/benchmark/bench_bare_vs_graph.yaml.
"""
import os
import re
import subprocess
import sys
import time
import json
import yaml
from pathlib import Path

ROOT = Path("/Users/jeff/culinary-mind")
BENCH = ROOT / "output/benchmark/bench_bare_vs_graph.yaml"
OUT = ROOT / "output/benchmark/llm_judge_results.yaml"

CODEX = ["codex", "exec", "--ephemeral", "--ignore-user-config",
         "--dangerously-bypass-approvals-and-sandbox", "-s", "read-only",
         "-m", "gpt-5.4", "-c", "model_reasoning_effort=medium"]


def call_codex(prompt, timeout=120):
    proc = subprocess.run(CODEX + [prompt], capture_output=True, text=True,
                          timeout=timeout, env={**os.environ, "NO_PROXY": "*"},
                          stdin=subprocess.DEVNULL)
    out = proc.stdout
    idx = out.rfind("\ncodex\n")
    if idx < 0: return out.strip()
    body = out[idx+7:]
    end = body.find("\ntokens used\n")
    if end > 0: body = body[:end]
    return body.strip()


def parse_score(text):
    """Extract outer JSON {bare, agent, winner} — anchor on '"winner"' to find outer."""
    if not text: return None
    # Anchor: '"bare"' is in the outer object
    idx = text.find('"bare"')
    if idx < 0: return None
    start = text.rfind("{", 0, idx)
    if start < 0: return None
    depth = 0; in_str = False; esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if esc: esc = False; continue
        if ch == "\\": esc = True; continue
        if ch == '"' and not esc: in_str = not in_str; continue
        if in_str: continue
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try: return json.loads(text[start:i+1])
                except json.JSONDecodeError: return None
    return None


def judge_pair(query, expected, bare_answer, agent_answer, mf_id):
    prompt = f"""<system>
You are an impartial food-science judge. Score TWO answers to the same query.

Output strict JSON only:
{{
  "bare": {{"correctness": 1-5, "numerical_precision": 1-5, "citation_quality": 1-5, "clarity": 1-5, "notes": "..."}},
  "agent": {{"correctness": 1-5, "numerical_precision": 1-5, "citation_quality": 1-5, "clarity": 1-5, "notes": "..."}},
  "winner": "bare|agent|tie",
  "reason": "..."
}}

Scoring criteria:
- correctness: physical/chemical accuracy of the answer
- numerical_precision: how close to the expected value, with proper units
- citation_quality: explicit references to formulas/MF tools/sources
- clarity: well-structured natural-language answer
</system>

<user>
Query: {query}
Expected value: {expected.get('value')} {expected.get('unit', '')} (via tool {expected.get('tool')})

=== Bare LLM Answer ===
{bare_answer[:1500]}

=== Agent Answer (with MF tool {mf_id}) ===
{agent_answer[:1500]}
</user>"""
    resp = call_codex(prompt)
    return parse_score(resp), resp


def main():
    bench = yaml.safe_load(open(BENCH))
    judge_results = []
    winner_count = {"bare": 0, "agent": 0, "tie": 0}
    
    print(f"=== Judging {len(bench['results'])} bench queries ===\n")
    for r in bench["results"]:
        print(f"[{r['id']}] judging...", end=" ", flush=True)
        score, raw = judge_pair(
            r["query"], r["expected"],
            r["bare_llm"]["answer"], r["graph_agent"]["answer"],
            r["graph_agent"].get("mf_id", ""),
        )
        if score:
            w = score.get("winner", "tie")
            winner_count[w] = winner_count.get(w, 0) + 1
            print(f"winner={w}")
            judge_results.append({"id": r["id"], "score": score, "raw": raw[:500]})
        else:
            print("parse failed")
            judge_results.append({"id": r["id"], "score": None, "raw": raw[:500]})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "version": "1.0",
        "n_queries": len(bench["results"]),
        "winner_count": winner_count,
        "results": judge_results,
    }
    OUT.write_text(yaml.safe_dump(summary, allow_unicode=True, sort_keys=False))

    print(f"\n=== Verdict ===")
    print(f"  Agent wins: {winner_count.get('agent', 0)} / {len(bench['results'])}")
    print(f"  Bare wins:  {winner_count.get('bare', 0)}")
    print(f"  Tie:        {winner_count.get('tie', 0)}")

    # Avg scores
    bare_avg = {k: 0 for k in ["correctness", "numerical_precision", "citation_quality", "clarity"]}
    agent_avg = dict(bare_avg)
    n = 0
    for r in judge_results:
        if r["score"] and isinstance(r["score"], dict) and "bare" in r["score"] and "agent" in r["score"]:
            try:
                for k in bare_avg:
                    bare_avg[k] += r["score"]["bare"].get(k, 0)
                    agent_avg[k] += r["score"]["agent"].get(k, 0)
                n += 1
            except (KeyError, TypeError): pass
    if n:
        print(f"\nAvg scores (1-5):")
        print(f"  {'Metric':<22} {'Bare':>6} {'Agent':>6}")
        for k in bare_avg:
            print(f"  {k:<22} {bare_avg[k]/n:>6.2f} {agent_avg[k]/n:>6.2f}")
    print(f"\n✅ {OUT}")


if __name__ == "__main__":
    main()
