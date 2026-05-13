#!/usr/bin/env python3
"""LLM agent v2: multi-tool ReAct chain.

Difference from v1:
- v1: query → choose ONE tool → invoke → answer (single-step)
- v2: query → reason → invoke multiple tools in sequence (chain dependent calculations)
  e.g. "煮牛肉 30 min, 中心 protein 变性 fraction?"
       → Step 1: MF-T02-CP/RHO/K → α
       → Step 2: MF-T01 Fourier → T_center
       → Step 3: MF-T06 → f_native at T_center
  Each step's output feeds the next.
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
    "-c", "model_reasoning_effort=medium",
]


def call_codex(prompt: str, timeout=180) -> str:
    proc = subprocess.run(
        CODEX_CMD + [prompt],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "NO_PROXY": "*"},
        stdin=subprocess.DEVNULL,
    )
    out = proc.stdout
    idx = out.rfind("\ncodex\n")
    if idx < 0: idx = out.rfind("codex\n")
    if idx >= 0:
        body = out[idx + len("\ncodex\n"):]
        end = body.find("\ntokens used\n")
        if end > 0: body = body[:end]
        return body.strip()
    return out.strip()


def parse_json(text: str):
    """Extract a JSON object from text using balanced braces."""
    if not text: return None
    idx = text.find('"plan"')  # outer wrapper FIRST
    if idx < 0: idx = text.find('"action"')
    if idx < 0: idx = text.find('"mf_id"')
    if idx < 0: idx = text.find("{")
    if idx < 0: return None
    start = text.rfind("{", 0, idx + 1)
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
                except: return None
    return None


def build_tool_catalog():
    """Build LLM-friendly catalog with USE descriptions."""
    USAGE = {
        "MF-T01": "1D heat conduction in slab; T(x,t)",
        "MF-T02-K": "Choi-Okos food thermal conductivity k from composition",
        "MF-T02-CP": "Choi-Okos food specific heat Cp from composition",
        "MF-T02-RHO": "Choi-Okos food density rho from composition",
        "MF-T03": "Arrhenius rate constant k(T) from A,Ea,T_K",
        "MF-T04": "Nusselt correlation for heat transfer",
        "MF-T05": "Plank freezing time",
        "MF-T06": "Protein denaturation sigmoid f_native(T_C, T_d, dH_d)",
        "MF-T07": "Microwave/RF volumetric heating P_abs",
        "MF-T08": "Ohmic Joule heating Q from sigma+E",
        "MF-T09": "Postharvest respiration heat Q=a·exp(b·T)",
        "MF-T10": "Starch gelatinization Avrami α(t,T)",
        "MF-K01": "Michaelis-Menten enzyme kinetics v(S,Km,Vmax)",
        "MF-K02": "Thermal D-value (microbial decimal reduction time)",
        "MF-K03": "z-value (D vs T temperature dependence)",
        "MF-K04": "F-value sterilization equivalent",
        "MF-K05": "Gompertz microbial growth log10(N/N0)",
        "MF-K06": "Microbial growth hurdle limit (boolean)",
        "MF-K07": "Ligand-protein binding equilibrium f_bound",
        "MF-M01": "Fick 2nd law diffusion C(x,t)",
        "MF-M02": "GAB sorption isotherm W(a_w)",
        "MF-M03": "Antoine vapor pressure of substance",
        "MF-M04": "Henderson-Hasselbalch pH of buffer",
        "MF-M05": "Henry law aroma volatility c_aq(p_gas)",
        "MF-M06": "Latent heat of substance",
        "MF-M07": "Octanol-water partition K=10^logP",
        "MF-M08": "Gas permeability through film Q=P·Δp/L",
        "MF-M09": "Van't Hoff osmotic pressure π=iMRT",
        "MF-M10": "Membrane solute flux J=P·ΔC/L",
        "MF-M11": "SCFE-CO2 Chrastil solubility y(ρ,T)",
        "MF-R01": "Power-law fluid viscosity τ=K·γ^n",
        "MF-R02": "Herschel-Bulkley yield-stress fluid",
        "MF-R03": "Casson model fluid",
        "MF-R04": "Gordon-Taylor Tg mix",
        "MF-R05": "WLF time-temperature superposition",
        "MF-R06": "Stevens psychophysical power law",
        "MF-R07": "Griffith fracture stress",
        "MF-C01": "Stokes sedimentation velocity v",
        "MF-C02": "HLB Griffin emulsifier balance",
        "MF-C03": "DLVO colloid stability V_T",
        "MF-C04": "Laplace pressure ΔP across curved interface",
        "MF-C05": "Q10 temperature rate doubling",
    }
    lines = ["Available MF tools (40 total). USE descriptions:"]
    for t in get_all_mf_tools():
        desc = USAGE.get(t.mf_id, t.canonical_name)
        fields = list(t.inputs_schema.keys())[:5]
        out_sym = t.output_schema.get("symbol", "?")
        lines.append(f"  - {t.mf_id}: {desc}  | inputs: {fields} → out: {out_sym}")
    return "\n".join(lines)


def plan_steps(user_query: str):
    """Step 1: Ask LLM to plan a sequence of MF tool invocations."""
    catalog = build_tool_catalog()
    system = f"""You are a food science reasoning planner. Decompose the user query
into a SEQUENCE of MF tool calls. Each call may use outputs from prior calls.

{catalog}

Output strict JSON only:
{{
  "plan": [
    {{"step": 1, "mf_id": "MF-T02-CP", "params": {{...}}, "uses": "X"}},
    {{"step": 2, "mf_id": "MF-T02-K", "params": {{...}}, "uses": "X"}},
    {{"step": 3, "mf_id": "MF-T01", "params": {{...alpha from steps 1+2...}}, "uses": "T_center"}},
    {{"step": 4, "mf_id": "MF-T06", "params": {{"T_C": "{{step3.value}}", ...}}, "uses": "f_native"}}
  ],
  "rationale": "..."
}}

Reference prior step outputs with {{stepN.value}}.
Max 5 steps. If 1 tool suffices, plan with 1 step.
If no tool fits, plan=[]."""
    prompt = f"<system>\n{system}\n</system>\n\n<user>\n{user_query}\n</user>"
    return call_codex(prompt)


def execute_plan(plan, verbose=True):
    """Execute steps in sequence, substituting prior outputs."""
    history = []  # step results
    for step_def in plan:
        step_n = step_def.get("step")
        mf_id = step_def.get("mf_id")
        params = dict(step_def.get("params", {}))
        if mf_id == "none": continue
        # P0 fix (Codex 5th): safe step reference resolution by actual step number
        step_map = {h.get("step"): h for h in history}
        for k, v in list(params.items()):
            if isinstance(v, str) and "{step" in v:
                m = re.match(r"\{step(\d+)\.(\w+)\}", v.strip())
                if m:
                    ref_step = int(m.group(1))
                    ref_field = m.group(2)
                    ref_result = step_map.get(ref_step)
                    if ref_result is None or "value" not in ref_result:
                        # Step failed or no output; cannot resolve — mark error and skip tool
                        params[k] = None
                        # Tool will likely fail validation; record reason
                        continue
                    if ref_field == "value":
                        params[k] = ref_result.get("value")
                    else:
                        params[k] = ref_result.get(ref_field)
        # Skip step if any param is None due to unresolved reference
        if None in params.values() and any(isinstance(v, str) and "{step" in v for v in step_def.get("params", {}).values()):
            history.append({"step": step_n, "mf_id": mf_id, "error": "unresolved step reference"})
            if verbose: print(f"  ⚠ Step {step_n}: unresolved reference, skipping")
            continue
        try:
            tool = get_mf_tool(mf_id)
        except KeyError as e:
            if verbose: print(f"  Step {step_n}: tool {mf_id} not found")
            history.append({"step": step_n, "mf_id": mf_id, "error": str(e)})
            continue
        try:
            out = tool.run(params)
            v = out["result"]["value"]
            sym = out["result"]["symbol"]
            unit = out["result"]["unit"]
            passed = out["validity"]["passed"]
            history.append({"step": step_n, "mf_id": mf_id, "value": v, "symbol": sym,
                            "unit": unit, "validity": passed, "params": params})
            if verbose:
                ok = "✅" if passed else "⚠️"
                print(f"  {ok} Step {step_n} {mf_id}: {sym} = {v} {unit}")
        except Exception as e:
            history.append({"step": step_n, "mf_id": mf_id, "error": str(e)})
            if verbose: print(f"  ❌ Step {step_n} {mf_id}: {e}")
    return history


def synthesize(user_query, plan_text, plan, history):
    """LLM composes final answer with chain reasoning."""
    chain_summary = "\n".join(
        f"  Step {h['step']} {h['mf_id']}: " +
        (f"{h.get('symbol','?')} = {h.get('value','?')} {h.get('unit','?')} {'✓' if h.get('validity') else '⚠ validity-fail'}" if "value" in h else f"ERROR: {h.get('error')}")
        for h in history
    )
    syn_prompt = f"""<system>
You are a food science explainer. Compose a brief natural-language answer
(in the user's language) for this multi-step MF chain.
Cite each MF tool used. Note any validity issues.
</system>

<user>
Query: {user_query}

Reasoning chain executed:
{chain_summary}

Compose answer.
</user>"""
    return call_codex(syn_prompt)


def answer_multistep(user_query, verbose=True):
    if verbose:
        print(f"\n{'='*90}\nUSER: {user_query}\n{'='*90}")
        print("\n[Step 1] Planning multi-MF chain...")
    plan_text = plan_steps(user_query)
    p = parse_json(plan_text)
    if not p or not p.get("plan"):
        return {"answer": "Cannot decompose query", "plan_raw": plan_text}
    plan = p["plan"]
    if verbose:
        print(f"Plan: {len(plan)} step(s)")
        for s in plan:
            print(f"  Step {s.get('step')}: {s.get('mf_id')} — {s.get('uses')}")
    history = execute_plan(plan, verbose=verbose)
    if verbose: print(f"\n[Step 2] Synthesizing answer...")
    final = synthesize(user_query, plan_text, plan, history)
    return {"answer": final, "plan": plan, "history": history}


def main():
    queries = [
        "5cm 牛肉块沸水煮 30 分钟，中心蛋白质变性大概几成？(用 Choi-Okos 算 α，再 Fourier 算中心温度，最后 sigmoid 估变性)",
        "75°C 鸡蛋蛋白质 (T_d=70°C dH=400) 多久达到 95% 变性？",
    ]
    for q in queries:
        r = answer_multistep(q, verbose=True)
        print(f"\n{'='*90}\nFINAL ANSWER:\n{r.get('answer','')[:800]}")
        print('='*90)


if __name__ == "__main__":
    main()
