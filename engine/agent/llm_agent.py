#!/usr/bin/env python3
"""Real LLM agent using Codex CLI + MF Tool Registry.

Architecture (ReAct-style):
  user query → LLM (Codex) chooses MF tool + extracts params
  → execute via engine.agent.tool_registry → tool result
  → LLM synthesizes answer with citations + reasoning chain

No LangGraph dependency — uses subprocess + Codex CLI.
For 真实 LangGraph upgrade later: drop in any LLM agent framework.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.agent.tool_registry import get_all_mf_tools, get_mf_tool


CODEX_CMD = [
    "codex", "exec",
    "--ephemeral",
    "--ignore-user-config",
    "--dangerously-bypass-approvals-and-sandbox",
    "-s", "read-only",
    "-m", "gpt-5.4",
    "-c", "model_reasoning_effort=low",
]


def build_tool_catalog():
    """Return text description of all 39 MF tools for LLM prompt."""
    lines = ["Available MF (Mother Formula) tools (40 physical/chemical solvers):"]
    for t in get_all_mf_tools():
        # Skip aliases — show one entry per canonical MF
        fields = [f for f in t.inputs_schema.keys() if not f.startswith("_")][:5]
        lines.append(f"  - {t.mf_id} {t.canonical_name}: inputs={fields}")
    return "\n".join(lines)


def call_codex(prompt: str, timeout=120) -> str:
    """Run Codex CLI with prompt, return stdout."""
    proc = subprocess.run(
        CODEX_CMD + [prompt],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "NO_PROXY": "*"},
        stdin=subprocess.DEVNULL,
    )
    # Extract LLM body after "codex" marker
    out = proc.stdout
    idx = out.rfind("\ncodex\n")
    if idx < 0: idx = out.rfind("codex\n")
    if idx >= 0:
        body = out[idx + len("\ncodex\n"):]
        end = body.find("\ntokens used\n")
        if end > 0: body = body[:end]
        return body.strip()
    return out.strip()


def parse_tool_call(llm_response: str):
    """Extract JSON tool_call from LLM response (balanced brace)."""
    if not llm_response: return None
    # Find first { containing mf_id, then balance-match
    idx = llm_response.find('"mf_id"')
    if idx < 0: return None
    # Walk back to find opening {
    start = llm_response.rfind("{", 0, idx)
    if start < 0: return None
    # Forward balanced-brace match
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(llm_response)):
        ch = llm_response[i]
        if esc: esc = False; continue
        if ch == "\\": esc = True; continue
        if ch == '"' and not esc: in_str = not in_str; continue
        if in_str: continue
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(llm_response[start:i+1])
                except json.JSONDecodeError:
                    return None
    return None


def answer_query(user_query: str, verbose=True) -> dict:
    """End-to-end: query → tool selection → execute → synthesize answer."""
    if verbose:
        print(f"\n{'='*80}")
        print(f"USER: {user_query}")
        print('='*80)

    # Step 1: LLM chooses tool + params
    catalog = build_tool_catalog()
    system = f"""You are a food science reasoning agent. You have access to 40 MF solver tools.

{catalog}

Task: Given a user query, decide ONE tool to invoke and what params.
Reply with strict JSON only (no prose, no markdown):
{{"mf_id": "MF-T03", "params": {{"A": 1e10, "Ea": 50000, "T_K": 363}}, "reason": "Arrhenius rate at 90°C"}}

If no tool fits, reply: {{"mf_id": "none", "reason": "..."}}"""

    prompt = f"<system>\n{system}\n</system>\n\n<user>\n{user_query}\n</user>"
    if verbose: print(f"\nStep 1: Asking LLM to choose tool...")
    llm_out = call_codex(prompt)
    if verbose: print(f"LLM reply: {llm_out[:300]}")

    call = parse_tool_call(llm_out)
    if not call or call.get("mf_id") == "none":
        return {"answer": "Cannot determine tool", "llm_raw": llm_out}

    mf_id = call["mf_id"]
    params = call.get("params", {})
    reason = call.get("reason", "")

    if verbose: print(f"\nStep 2: Invoke {mf_id} with {params}")

    # Step 2: invoke
    try:
        tool = get_mf_tool(mf_id)
        result = tool.run(params)
    except Exception as e:
        return {"answer": f"Tool error: {e}", "mf_id": mf_id, "params": params}

    if verbose:
        print(f"\nResult: validity={result['validity']['passed']}")
        print(f"        value={result['result']['value']} {result['result']['unit']}")

    # Step 3: synthesize answer
    syn_prompt = f"""<system>
You are a food science explainer. Convert this tool result into a natural-language answer in {'Chinese' if any(ord(c)>127 for c in user_query) else 'English'}.
</system>

<user>
Query: {user_query}
Tool: {mf_id} ({tool.canonical_name})
Reason for choosing: {reason}
Params: {json.dumps(params, ensure_ascii=False)}
Result: {result['result']['symbol']} = {result['result']['value']:.4g} {result['result']['unit']}
Validity: {result['validity']['passed']}
Assumptions: {result['assumptions']}

Compose a short answer with citation to {mf_id}.
</user>"""

    if verbose: print(f"\nStep 3: Synthesize answer...")
    final = call_codex(syn_prompt)

    return {
        "answer": final,
        "mf_id": mf_id,
        "canonical_name": tool.canonical_name,
        "params": params,
        "result": result["result"],
        "validity": result["validity"]["passed"],
    }


def main():
    queries = [
        "若以 90°C 加热酶，活化能 60 kJ/mol，速率常数是多少？",
        "5cm 牛肉块沸水煮 30 分钟，中心温度估计是多少？",
        "凝固蛋白的 sigmoid 温度范围，T_d=65°C dH=400 kJ/mol，65°C 时 native fraction?",
    ]
    for q in queries:
        result = answer_query(q, verbose=True)
        print(f"\n{'='*80}\nFINAL ANSWER:\n{result.get('answer', 'N/A')[:500]}")
        print('='*80)


if __name__ == "__main__":
    main()
