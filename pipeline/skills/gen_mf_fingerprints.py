#!/usr/bin/env python3
"""
pipeline/skills/gen_mf_fingerprints.py
Phase 1.5: Generate MF fingerprint library from mother_formulas.yaml

Input:  config/mother_formulas.yaml (28 MFs)
Output: config/mf_fingerprints.json

Each fingerprint contains search keywords derived from the MF definition:
- equation LaTeX, domain tags, parameter names, notes, source books
"""

import os
import sys
import json
import re
import yaml
from pathlib import Path

# ── Proxy bypass ──────────────────────────────────────────────────────────────
for k in ["http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY","all_proxy","ALL_PROXY"]:
    os.environ.pop(k, None)

REPO_ROOT = Path(__file__).resolve().parents[2]
YAML_PATH = REPO_ROOT / "config" / "mother_formulas.yaml"
OUT_PATH  = REPO_ROOT / "config" / "mf_fingerprints.json"

# ── Domain → common keywords ──────────────────────────────────────────────────

DOMAIN_KEYWORDS_EN: dict[str, list[str]] = {
    "thermal_dynamics":       ["heat transfer", "thermal conductivity", "specific heat", "temperature", "cooling", "heating", "thermal diffusivity"],
    "protein_science":        ["protein", "denaturation", "gelation", "collagen", "myosin", "actin", "unfolding", "aggregation"],
    "maillard_caramelization":["Maillard", "browning", "caramelization", "Amadori", "reducing sugar", "melanoidin", "color development"],
    "enzyme":                 ["enzyme", "catalysis", "substrate", "inhibition", "activity", "Michaelis", "turnover"],
    "food_safety":            ["pathogen", "microbial", "sterilization", "pasteurization", "decimal reduction", "D-value", "z-value", "F-value", "lethality"],
    "lipid_science":          ["fat", "lipid", "oxidation", "rancidity", "fatty acid", "triglyceride", "emulsification", "melting point"],
    "carbohydrate":           ["starch", "gelatinization", "retrogradation", "sugar", "glucose", "sucrose", "amylose", "amylopectin"],
    "fermentation":           ["fermentation", "yeast", "bacteria", "pH", "lactic acid", "acetic acid", "alcohol", "CO2"],
    "water_activity":         ["water activity", "aw", "moisture", "sorption isotherm", "ERH", "BET", "GAB", "glass transition"],
    "mass_transfer":          ["diffusion", "mass transfer", "concentration gradient", "permeability", "Fick", "effective diffusivity"],
    "texture_rheology":       ["viscosity", "rheology", "yield stress", "elasticity", "gel", "flow behavior", "Power Law", "shear"],
    "taste_perception":       ["taste", "perception", "threshold", "bitterness", "sweetness", "umami", "saltiness", "sour"],
    "aroma_volatiles":        ["aroma", "volatile", "headspace", "partition coefficient", "Henry", "odor threshold", "flavor compound"],
    "color_pigment":          ["color", "pigment", "chlorophyll", "anthocyanin", "carotenoid", "Maillard browning", "lightness", "L* a* b*"],
    "oxidation_reduction":    ["oxidation", "reduction", "antioxidant", "free radical", "peroxide", "Eh", "redox"],
    "salt_acid_chemistry":    ["pH", "buffer", "acid", "alkali", "pKa", "Henderson-Hasselbalch", "salt", "ionic strength"],
    "equipment_physics":      ["heat exchanger", "pump", "pressure drop", "Reynolds", "Nusselt", "Prandtl", "friction factor"],
}

DOMAIN_KEYWORDS_ZH: dict[str, list[str]] = {
    "thermal_dynamics":       ["导热系数", "热扩散率", "比热容", "传热", "冷却", "加热"],
    "protein_science":        ["蛋白质", "变性", "凝胶化", "胶原蛋白", "肌球蛋白", "展开", "聚集"],
    "maillard_caramelization":["美拉德反应", "焦糖化", "褐变", "还原糖", "色泽发展"],
    "enzyme":                 ["酶", "催化", "底物", "抑制", "活性", "米氏常数"],
    "food_safety":            ["病原体", "微生物", "灭菌", "巴氏杀菌", "D值", "z值", "F值", "致死率"],
    "lipid_science":          ["脂肪", "脂质", "氧化", "酸败", "脂肪酸", "甘油三酯", "乳化", "熔点"],
    "carbohydrate":           ["淀粉", "糊化", "回生", "糖", "葡萄糖", "蔗糖"],
    "fermentation":           ["发酵", "酵母", "细菌", "乳酸", "醋酸", "乙醇"],
    "water_activity":         ["水活度", "水分活度", "水分", "吸附等温线", "玻璃化转变"],
    "mass_transfer":          ["扩散", "传质", "浓度梯度", "渗透性", "菲克定律"],
    "texture_rheology":       ["黏度", "流变", "屈服应力", "弹性", "凝胶", "剪切"],
    "taste_perception":       ["味觉", "感知", "阈值", "苦味", "甜味", "鲜味", "咸味", "酸味"],
    "aroma_volatiles":        ["香气", "挥发物", "顶空", "分配系数", "亨利定律", "气味阈值"],
    "color_pigment":          ["颜色", "色素", "叶绿素", "花青素", "类胡萝卜素", "褐变", "亮度"],
    "oxidation_reduction":    ["氧化", "还原", "抗氧化", "自由基", "过氧化物"],
    "salt_acid_chemistry":    ["pH值", "缓冲液", "酸", "碱", "盐", "离子强度"],
    "equipment_physics":      ["换热器", "泵", "压降", "雷诺数", "努塞尔数"],
}

# ── LaTeX symbol → keyword extraction ────────────────────────────────────────

LATEX_SYMBOL_MAP: dict[str, list[str]] = {
    r"\\alpha":    ["thermal diffusivity", "alpha"],
    r"E_a|E_{a}":  ["activation energy", "Ea"],
    r"\\mu_{max}": ["maximum specific growth rate", "mu_max"],
    r"K_m|K_{m}":  ["Michaelis constant", "Km"],
    r"V_{max}|V_max": ["maximum velocity", "Vmax"],
    r"D_eff|D_{eff}": ["effective diffusivity", "D_eff"],
    r"a_w":        ["water activity", "aw"],
    r"T_g":        ["glass transition temperature", "Tg"],
    r"\\tau_0":    ["yield stress", "tau_0"],
    r"X_m|X_{m}":  ["monolayer moisture content", "Xm"],
}

def extract_latex_params(latex: str) -> list[str]:
    """Pull human-readable keywords from a LaTeX equation string."""
    kws: list[str] = []
    for pattern, names in LATEX_SYMBOL_MAP.items():
        if re.search(pattern, latex):
            kws.extend(names)
    # Extract bare letter symbols like k, n, K, D, z
    symbols = re.findall(r'\\([A-Za-z]+)', latex)
    kws.extend([s for s in symbols if len(s) <= 3 and s not in ('frac','partial','cdot','sqrt','log','int')])
    return list(dict.fromkeys(kws))  # dedup preserving order

def extract_unit_keywords(units: dict) -> list[str]:
    """Turn unit strings into searchable keywords."""
    kws: list[str] = []
    for _param, unit_str in units.items():
        if isinstance(unit_str, str):
            # Extract numeric/unit patterns like J/mol, W/(m·K)
            clean = re.sub(r'[()·]', ' ', unit_str)
            for tok in clean.split():
                tok = tok.strip('/,')
                if len(tok) >= 2 and not tok.isdigit():
                    kws.append(tok)
    return list(dict.fromkeys(kws))

def build_fingerprint(mf: dict) -> dict:
    """Build fingerprint dict from a single MF YAML entry."""
    mf_id  = mf.get("id", "")
    domains = mf.get("domain", [])
    params  = mf.get("parameters_needed", [])
    notes   = mf.get("notes", "")
    latex   = mf.get("equation_latex", "")
    units   = mf.get("units", {})
    source_books = mf.get("source_books", [])
    canonical_name = mf.get("canonical_name", "")
    display_name   = mf.get("display_name", "")

    # --- English keywords ---
    kw_en: list[str] = []

    # From display name / canonical name
    kw_en.append(canonical_name.replace("_", " "))
    if display_name:
        kw_en.append(display_name)

    # From domains
    for d in domains:
        kw_en.extend(DOMAIN_KEYWORDS_EN.get(d, [])[:4])  # top 4 per domain

    # From LaTeX
    kw_en.extend(extract_latex_params(latex))

    # From parameter names (already human-readable)
    kw_en.extend(params)

    # From notes (extract key phrases)
    note_phrases = re.findall(r'[A-Za-z][a-z ]{3,30}[a-z]', notes)
    kw_en.extend([p for p in note_phrases[:6] if len(p) > 5])

    # From units
    kw_en.extend(extract_unit_keywords(units))

    # Deduplicate, strip short tokens
    seen: set[str] = set()
    clean_en: list[str] = []
    for k in kw_en:
        k2 = k.strip()
        if k2 and k2.lower() not in seen and len(k2) >= 2:
            seen.add(k2.lower())
            clean_en.append(k2)

    # --- Chinese keywords ---
    kw_zh: list[str] = []
    for d in domains:
        kw_zh.extend(DOMAIN_KEYWORDS_ZH.get(d, [])[:3])
    kw_zh.extend(params)  # param names (often same in ZH)

    # --- Typical statements ---
    typical_stmts: list[str] = []
    if notes:
        # Extract sentences containing numbers or comparisons
        sents = re.split(r'[;。；]', notes)
        for s in sents:
            s = s.strip()
            if s and re.search(r'\d', s) and len(s) > 10:
                typical_stmts.append(s[:120])
    if not typical_stmts and notes:
        typical_stmts.append(notes[:150])

    return {
        "id":               mf_id,
        "canonical_name":   canonical_name,
        "display_name":     display_name,
        "domains":          domains,
        "keywords_en":      clean_en[:25],
        "keywords_zh":      list(dict.fromkeys(kw_zh))[:15],
        "parameter_names":  params,
        "typical_statements": typical_stmts[:3],
        "source_books":     source_books,
        "equation_latex":   latex,
    }

def main() -> None:
    if not YAML_PATH.exists():
        print(f"ERROR: {YAML_PATH} not found", file=sys.stderr)
        sys.exit(1)

    with open(YAML_PATH) as f:
        mfs = yaml.safe_load(f)

    if not isinstance(mfs, list):
        print(f"ERROR: expected list from {YAML_PATH}", file=sys.stderr)
        sys.exit(1)

    fingerprints: dict = {}
    for mf in mfs:
        mf_id = mf.get("id", "")
        if not mf_id:
            continue
        fp = build_fingerprint(mf)
        fingerprints[mf_id] = fp

    # Write output
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(fingerprints, f, ensure_ascii=False, indent=2)

    print(f"Generated {len(fingerprints)} MF fingerprints → {OUT_PATH}")

    # Quick sanity check
    print("\n── Pilot check: MF-T01, MF-T03, MF-K02 ──")
    for check_id in ["MF-T01", "MF-T03", "MF-K02"]:
        fp = fingerprints.get(check_id)
        if fp:
            print(f"\n{check_id}: {fp['canonical_name']}")
            print(f"  domains:      {fp['domains']}")
            print(f"  keywords_en:  {fp['keywords_en'][:8]}")
            print(f"  keywords_zh:  {fp['keywords_zh'][:5]}")
            print(f"  param_names:  {fp['parameter_names']}")
        else:
            print(f"\n{check_id}: NOT FOUND")

if __name__ == "__main__":
    main()
