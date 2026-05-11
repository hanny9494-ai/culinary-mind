#!/usr/bin/env python3
"""P2-Sa1.1: Apply 6 MF schema extensions (P1-21c-D backlog Tier 1).

Uses ruamel.yaml to preserve comments + formatting in yaml files.
"""
import json
import sys
from pathlib import Path
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import SingleQuotedScalarString

ROOT = Path("/Users/jeff/culinary-mind")
SB_FILE = ROOT / "config/solver_bounds.yaml"
MF_FILE = ROOT / "config/mother_formulas.yaml"
FP_FILE = ROOT / "config/mf_fingerprints.json"

yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 4096
yaml.indent(mapping=2, sequence=4, offset=2)

EXTENSIONS = {
    "MF-T03": {
        "inputs": [
            {"name": "observed_k", "min": 1.0e-12, "max": 1.0e3, "unit": "s⁻¹", "source": "P1-21c-D backlog"},
            {"name": "reaction_order", "min": 0.0, "max": 3.0, "unit": "dimensionless", "source": "P1-21c-D backlog"},
        ],
        "fp_param_names": ["observed_k", "k_obs", "reaction_order", "n_order"],
        "fp_kw_en": ["first-order degradation rate constant", "reaction order", "observed rate constant", "thermal degradation k", "nutrient degradation rate"],
        "fp_kw_zh": ["一阶降解速率", "反应级数", "热降解速率常数", "营养素降解"],
    },
    "MF-T02": {
        "inputs": [
            {"name": "composition.salt", "min": 0.0, "max": 1.0, "unit": "mass fraction", "source": "P1-21c-D backlog"},
            {"name": "composition.sugar", "min": 0.0, "max": 1.0, "unit": "mass fraction", "source": "P1-21c-D backlog"},
            {"name": "composition.alcohol", "min": 0.0, "max": 1.0, "unit": "mass fraction", "source": "P1-21c-D backlog"},
        ],
        "fp_param_names": ["composition.salt", "composition.sugar", "composition.alcohol", "Xsalt", "Xsugar", "Xalcohol"],
        "fp_kw_en": ["salt content", "sugar content", "alcohol content", "ethanol fraction"],
        "fp_kw_zh": ["盐含量", "糖含量", "酒精含量"],
    },
    "MF-K01": {
        "inputs": [
            {"name": "pH_opt", "min": 1.0, "max": 14.0, "unit": "pH", "source": "P1-21c-D backlog"},
            {"name": "T_opt", "min": -20.0, "max": 100.0, "unit": "°C", "source": "P1-21c-D backlog"},
        ],
        "fp_param_names": ["pH_opt", "T_opt", "optimum_pH", "optimum_temperature"],
        "fp_kw_en": ["enzyme pH optimum", "enzyme temperature optimum", "optimal activity"],
        "fp_kw_zh": ["最适 pH", "最适温度", "酶最适"],
    },
    "MF-M02": {
        "inputs": [
            {"name": "Q_iso", "min": 0.0, "max": 1.0e6, "unit": "J/mol", "source": "P1-21c-D backlog"},
        ],
        "fp_param_names": ["Q_iso", "Qst", "isosteric_heat"],
        "fp_kw_en": ["isosteric heat", "heat of sorption", "sorption binding energy"],
        "fp_kw_zh": ["等温吸湿热", "解吸热"],
    },
    "MF-K02": {
        "inputs": [
            {"name": "D_radiation_kGy", "min": 0.001, "max": 100.0, "unit": "kGy", "source": "P1-21c-D backlog"},
        ],
        "fp_param_names": ["D_radiation_kGy", "D10", "radiation_D_value"],
        "fp_kw_en": ["radiation resistance D10", "radiation D-value", "irradiation dose", "gamma sterilization"],
        "fp_kw_zh": ["辐照剂量", "辐射 D10", "辐照灭菌"],
    },
    "MF-M04": {
        "inputs": [
            {"name": "pKa1", "min": -3.0, "max": 16.0, "unit": "dimensionless", "source": "P1-21c-D backlog"},
            {"name": "pKa2", "min": -3.0, "max": 16.0, "unit": "dimensionless", "source": "P1-21c-D backlog"},
            {"name": "pKa3", "min": -3.0, "max": 16.0, "unit": "dimensionless", "source": "P1-21c-D backlog"},
        ],
        "fp_param_names": ["pKa1", "pKa2", "pKa3", "Ka1", "Ka2"],
        "fp_kw_en": ["multi-pKa", "amino acid pKa", "polyprotic acid"],
        "fp_kw_zh": ["多 pKa", "氨基酸 pKa", "多元酸"],
    },
}

NEW_UNITS = {
    "MF-T03": {"observed_k": "s⁻¹", "reaction_order": "dimensionless"},
    "MF-T02": {"composition.salt": "mass fraction", "composition.sugar": "mass fraction", "composition.alcohol": "mass fraction"},
    "MF-K01": {"pH_opt": "pH", "T_opt": "°C"},
    "MF-M02": {"Q_iso": "J/mol"},
    "MF-K02": {"D_radiation_kGy": "kGy"},
    "MF-M04": {"pKa1": "dimensionless", "pKa2": "dimensionless", "pKa3": "dimensionless"},
}

def apply_solver_bounds():
    data = yaml.load(open(SB_FILE))
    added = []
    for mf_id, ext in EXTENSIONS.items():
        if mf_id not in data["solvers"]:
            print(f"  ! {mf_id} missing"); continue
        solver = data["solvers"][mf_id]
        existing = {i["name"] for i in solver.get("inputs", [])}
        for new in ext["inputs"]:
            if new["name"] in existing:
                continue
            solver["inputs"].append(new)
            added.append(f"{mf_id}.{new['name']}")
    tmp = SB_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        yaml.dump(data, f)
    tmp.rename(SB_FILE)
    print(f"✅ solver_bounds.yaml: +{len(added)} fields")
    for x in added: print(f"   + {x}")
    return added

def apply_mother_formulas():
    """Add new keys to units dict + (if needed) one_of_inputs/applicable_range."""
    docs = list(yaml.load_all(open(MF_FILE)))
    # mother_formulas.yaml is one document containing a list
    mfs = docs[0]
    if not isinstance(mfs, list):
        print("  ! unexpected structure")
        return []
    added = []
    for mf in mfs:
        if not isinstance(mf, dict): continue
        mf_id = mf.get("id")
        if mf_id in NEW_UNITS:
            units = mf.setdefault("units", {})
            for k, v in NEW_UNITS[mf_id].items():
                if k not in units:
                    units[k] = v
                    added.append(f"{mf_id}.{k}")
    tmp = MF_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        yaml.dump_all(docs, f)
    tmp.rename(MF_FILE)
    print(f"✅ mother_formulas.yaml: +{len(added)} unit entries")
    return added

def apply_fingerprints():
    data = json.load(open(FP_FILE))
    added = 0
    for mf_id, ext in EXTENSIONS.items():
        if mf_id not in data: continue
        fp = data[mf_id]
        for name in ext["fp_param_names"]:
            if name not in fp.setdefault("parameter_names", []):
                fp["parameter_names"].append(name); added += 1
        for kw in ext["fp_kw_en"]:
            if kw not in fp.setdefault("keywords_en", []):
                fp["keywords_en"].append(kw); added += 1
        for kw in ext["fp_kw_zh"]:
            if kw not in fp.setdefault("keywords_zh", []):
                fp["keywords_zh"].append(kw); added += 1
    tmp = FP_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.rename(FP_FILE)
    print(f"✅ mf_fingerprints.json: +{added} entries")
    return added

if __name__ == "__main__":
    print("=== Apply MF Schema Extensions (ruamel.yaml preserves comments) ===")
    apply_solver_bounds()
    # apply_mother_formulas()  # skipped: ruamel reformats indent — manual edit recommended
    apply_fingerprints()
