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
        # FALLBACK: knowledge query — use graph context + Codex direct answer
        if verbose: print(f"\n  No MF tool fits; trying knowledge query with graph context...")
        return knowledge_query_fallback(user_query, verbose=verbose)

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




def knowledge_query_fallback(user_query: str, verbose=True) -> dict:
    """Science-grounded knowledge query.

    Strategy:
    1. Extract keywords + map to PHN (Chinese culinary terms → phn_id)
    2. For each PHN, pull MF tools + L0 evidence + parameter ranges
    3. Match recipes by name (loose)
    4. LLM synthesizes answer USING graph science, not fallback to general knowledge
    """
    import re
    import json as _json

    # 1. PHN keyword mapping (Chinese + English → real phn_id in graph)
    PHN_KEYWORDS = [
        (r"腌渍|腌|盐渍|盐腌|brining|brine|cure|curing|salt[- ]cure", "brining_curing"),
        (r"风干|挂水|脱水|干燥|dehydrate|drying|air[- ]?dry", "moisture_migration"),
        (r"炸|油炸|deep[- ]?fry|frying", "deep_frying_dynamics"),
        (r"美拉德|焦|褐变|maillard|browning|焦化", "maillard_browning"),
        (r"焦糖|caramel|caramelize", "caramelization"),
        (r"脆|crisp|crunch|脆度", "crispness_fracture_mechanics"),
        (r"蛋白质.*变性|protein.*denat|protein.*coag|凝固", "protein_thermal_denaturation"),
        (r"水活度|water activity|\baw\b|a_w", "water_activity_preservation"),
        (r"巴氏|pasteur|灭菌|sterilize|杀菌|thermal kill", "thermal_microbial_inactivation"),
        (r"发酵|ferment|leaven|乳酸", "lactic_acid_fermentation"),
        (r"乳化|emulsion|乳浊", "emulsion_formation_stability"),
        (r"冷冻|freeze|结冰|ice crystal", "freezing_ice_crystal_formation"),
        (r"淀粉.*糊化|starch.*gel|gelatinization", "starch_gelatinization"),
        (r"sous[- ]?vide|低温慢煮|低温烹饪", "sous_vide_precision_cooking"),
        (r"扩散|diffusion", "osmotic_diffusion"),
        (r"鲜味|umami", "umami_taste_synergy"),
        (r"弹性|texture|质构|firm", "texture_firming_window"),
        (r"glutamate|MSG|味精", "umami_taste_synergy"),
    ]

    matched_phns = []
    for pat, phn_id in PHN_KEYWORDS:
        if re.search(pat, user_query, re.IGNORECASE):
            if phn_id not in matched_phns:
                matched_phns.append(phn_id)
    if verbose: print(f"  PHN matched: {matched_phns}")

    # 2. Extract general keywords (for Recipe / L0 / L2A name search)
    chinese = re.findall(r"[\u4e00-\u9fff]{2,8}", user_query)
    english = re.findall(r"[a-zA-Z]{3,20}", user_query)
    keywords = list(dict.fromkeys(chinese + english))[:6]

    science_blocks = []
    recipe_examples = []
    l2a_pieces = []

    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "cmind_p1_33_proto"))
        with driver.session() as sess:
            # 3. For each matched PHN, pull governing MFs + L0 evidence
            for phn_id in matched_phns:
                phn_node = sess.run(
                    "MATCH (p:CKG_PHN {phn_id: $phn}) RETURN p.phn_id AS phn, p.name_en AS name_en, p.l0_atom_count AS n_l0",
                    phn=phn_id
                ).single()
                if not phn_node: continue
                mfs = sess.run(
                    "MATCH (m:CKG_MF)-[:GOVERNS_PHN]->(p:CKG_PHN {phn_id: $phn}) "
                    "RETURN m.mf_id AS mf_id, m.canonical_name AS name",
                    phn=phn_id
                ).data()
                l0s = sess.run(
                    "MATCH (l:CKG_L0_TMP_Principle)-[:TAGGED_BY_PHN]->(p:CKG_PHN {phn_id: $phn}) "
                    "RETURN l.scientific_statement AS stmt, l.book_id AS book LIMIT 4",
                    phn=phn_id
                ).data()
                # Sample real recipe steps that trigger this PHN
                steps = sess.run(
                    "MATCH (s:CKG_L2B_TMP_Step)-[:TRIGGERS_PHN]->(p:CKG_PHN {phn_id: $phn}) "
                    "WHERE s.temp_c IS NOT NULL "
                    "RETURN s.action AS action, s.temp_c AS T, s.duration_min AS dur LIMIT 3",
                    phn=phn_id
                ).data()
                science_blocks.append({
                    "phn": phn_id,
                    "n_l0_total": phn_node.get("n_l0"),
                    "governing_mfs": mfs,
                    "l0_evidence": l0s,
                    "real_recipe_examples": steps,
                })

            # 4. L2A ingredient lookup (chicken/duck/etc)
            for kw in keywords[:3]:
                if len(kw) < 2: continue
                ings = sess.run(
                    "MATCH (i:CKG_L2A_Ingredient) "
                    "WHERE i.display_name_zh CONTAINS $kw OR i.display_name_en CONTAINS $kw "
                    "OPTIONAL MATCH (i)-[:IS_A]->(p) "
                    "RETURN i.canonical_id AS cid, i.display_name_zh AS zh, collect(DISTINCT p.canonical_id) AS parents LIMIT 2",
                    kw=kw
                ).data()
                for i in ings:
                    l2a_pieces.append(f"{i['cid']} ({i.get('zh','')}) IS_A {i['parents']}")

            # 5. Recipe examples (existing)
            for kw in keywords[:3]:
                if len(kw) < 2: continue
                recipes = sess.run(
                    "MATCH (r:CKG_L2B_TMP_Recipe) WHERE r.name CONTAINS $kw "
                    "RETURN r.name AS name, r.book_id AS book LIMIT 2",
                    kw=kw
                ).data()
                for r in recipes:
                    recipe_examples.append(f"{r['name']} ({r['book']})")

        driver.close()
    except Exception as e:
        if verbose: print(f"  Neo4j unreachable: {e}")

    # 6. Build prompt with structured science context
    science_text = ""
    for sb in science_blocks:
        science_text += f"\n\n### PHN: {sb['phn']}\n"
        if sb.get('governing_mfs'):
            mfs_str = ", ".join(f"{m['mf_id']} ({m['name']})" for m in sb['governing_mfs'])
            science_text += f"  Governing MF tools: {mfs_str}\n"
        if sb.get('real_recipe_examples'):
            ex = ", ".join(f"{e['action']}@{e['T']}°C×{e['dur']}min" for e in sb['real_recipe_examples'] if e['T'])
            science_text += f"  Real recipe examples: {ex}\n"
        if sb.get('l0_evidence'):
            science_text += "  L0 scientific evidence:\n"
            for e in sb['l0_evidence'][:3]:
                science_text += f"    - {(e['stmt'] or '')[:200]} ({e.get('book','')})\n"

    if not science_blocks:
        science_text = "(No PHN matched in graph; will use general knowledge)"

    recipes_text = "\n".join(f"- {r}" for r in recipe_examples[:5]) if recipe_examples else "(无 direct recipe match)"
    l2a_text = "\n".join(f"- {l}" for l in l2a_pieces[:5]) if l2a_pieces else ""

    syn_prompt = f"""<system>
You are a food-science assistant grounded in a knowledge graph (PHN/MF/L0).

REQUIRED behavior:
1. For each step or claim, identify which PHN (phenomenon) governs it
2. Cite the MF tool(s) that model that PHN
3. Provide specific numerical ranges (temperature, time, concentration) — pull from L0 evidence or real recipe examples in the context
4. Reference L0 evidence in the format: "(L0: book_id - statement excerpt)"
5. Only mark "(从通用知识)" for things NOT in the graph context
6. Reply in 中文 if 中文 query, else English

Available graph science:
{science_text}

Real recipe examples (by name match):
{recipes_text}

L2A ingredient context (if relevant):
{l2a_text}
</system>

<user>
{user_query}
</user>"""

    if verbose: print(f"  Graph science blocks: {len(science_blocks)} PHNs, {len(recipe_examples)} recipes, {len(l2a_pieces)} L2A pieces")

    final = call_codex(syn_prompt, timeout=180)
    return {
        "answer": final,
        "mode": "knowledge_query_science",
        "matched_phns": matched_phns,
        "n_governing_mfs": sum(len(sb.get('governing_mfs') or []) for sb in science_blocks),
        "n_l0_evidence": sum(len(sb.get('l0_evidence') or []) for sb in science_blocks),
        "n_recipe_examples": len(recipe_examples),
        "keywords": keywords,
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
