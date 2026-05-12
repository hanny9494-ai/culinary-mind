#!/usr/bin/env python3
"""Simple demo: natural-language query → MF tool routing (keyword-based).

This is a STUB for real LangGraph integration. It demonstrates how a future
agent would dispatch MF tools based on user intent.

Example:
    python engine/agent/demo_simple_router.py "煮 70°C 30min 蛋白质变性多少"
"""
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.agent.tool_registry import get_all_mf_tools, get_mf_tool


# Keyword → MF mapping (manual; would be LLM-driven in production)
INTENT_MAP = {
    "protein.*denaturation|蛋白质.*变性|protein.*coagulation|肉.*嫩": "MF-T06",
    "growth.*limit|microbial.*growth|食品安全|MIC|pH.*min": "MF-K06",
    "microwave|RF.*heat|dielectric|微波|射频": "MF-T07",
    "starch.*gelatinization|淀粉.*糊化|淀粉.*糊化": "MF-T10",
    "logP|partition.*coefficient|溶解度.*油水|octanol": "MF-M07",
    "gas.*permeability|packaging|包装.*透.*气|WVTR|O2.*transmission": "MF-M08",
    "ohmic.*heating|joule.*heat|焦耳|电导率.*加热": "MF-T08",
    "binding.*equilibrium|ligand.*protein|配体|结合常数": "MF-K07",
    "respiration|呼吸.*热|cold.*storage.*produce": "MF-T09",
    "osmotic.*pressure|渗透压|van.t.*hoff": "MF-M09",
    "supercritical|SCFE|超临界": "MF-M11",
    "membrane.*transport|膜.*分离|membrane.*flux": "MF-M10",
    "arrhenius|reaction.*rate|activation.*energy|Ea": "MF-T03",
    "fourier|heat.*conduction|热传导|temperature.*center": "MF-T01",
    "Choi.Okos|composition|specific.*heat|Cp.*food": "MF-T02-CP",
    "Michaelis.Menten|enzyme.*kinetics|Vmax|Km": "MF-K01",
    "D.value|thermal.*death|pasteurization.*D": "MF-K02",
    "F.value|pasteurization|F0": "MF-K04",
    "Gompertz|microbial.*growth.*curve": "MF-K05",
    "GAB|sorption.*isotherm|water.*activity": "MF-M02",
    "Antoine|vapor.*pressure": "MF-M03",
    "Henderson.Hasselbalch|pKa.*buffer|pH.*buffer": "MF-M04",
    "Henry.law|aroma.*volatile": "MF-M05",
    "latent.*heat|相变.*焓": "MF-M06",
    "viscosity|粘度|power.*law": "MF-R01",
    "Casson|yield.*stress": "MF-R03",
    "WLF|glass.*transition.*shift": "MF-R05",
    "Stokes|sedimentation|沉降": "MF-C01",
    "DLVO|colloid.*stability": "MF-C03",
    "Q10.*rule|温度系数": "MF-C05",
}


def route_query(query: str) -> list[tuple[str, str]]:
    """Return list of (mf_id, matched_keyword)."""
    matches = []
    for pattern, mf_id in INTENT_MAP.items():
        if re.search(pattern, query, re.IGNORECASE):
            matches.append((mf_id, pattern.split("|")[0]))
    return matches


def main():
    if len(sys.argv) < 2:
        print("Usage: demo_simple_router.py '<natural language query>'")
        print("\nExamples:")
        print("  '蛋白质变性温度多少'           → MF-T06")
        print("  '微波加热鸡肉 200g'             → MF-T07")
        print("  '淀粉糊化温度'                  → MF-T10")
        print("  '冰箱苹果呼吸热'                → MF-T09")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    print(f"Query: '{query}'")
    print()
    matches = route_query(query)
    if not matches:
        print("No MF matched. Try keywords like: protein denaturation / microwave / starch gelatinization")
        sys.exit(0)
    print(f"Matched {len(matches)} MF tool(s):")
    for mf_id, kw in matches:
        try:
            tool = get_mf_tool(mf_id)
            print(f"\n  → {tool.name} ({mf_id}: {tool.canonical_name})")
            print(f"    Triggered by keyword: '{kw}'")
            print(f"    Description: {tool.description}")
            print(f"    {tool.get_input_summary()}")
        except KeyError as e:
            print(f"  → {mf_id} (tool not loaded: {e})")


if __name__ == "__main__":
    main()
