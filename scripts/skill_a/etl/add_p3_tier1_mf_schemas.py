#!/usr/bin/env python3
"""P3 Tier 1: add 4 new MF solver_bounds + fingerprints (mother_formulas manual edit later).

ruamel.yaml preserves comments in solver_bounds.yaml.
"""
import json
from pathlib import Path
from ruamel.yaml import YAML

ROOT = Path("/Users/jeff/culinary-mind")
SB_FILE = ROOT / "config/solver_bounds.yaml"
FP_FILE = ROOT / "config/mf_fingerprints.json"

yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 4096
yaml.indent(mapping=2, sequence=4, offset=2)

NEW_MFS = {
    "MF-T06": {
        "canonical_name": "Protein_Denaturation",
        "inputs": [
            {"name": "T_d", "min": 30.0, "max": 130.0, "unit": "°C", "source": "P3 Tier 1 — DSC midpoint"},
            {"name": "dH_d", "min": 50.0, "max": 2000.0, "unit": "kJ/mol", "source": "P3 Tier 1"},
            {"name": "T_C", "min": -20.0, "max": 250.0, "unit": "°C", "source": "P3 Tier 1"},
            {"name": "T_c", "min": -20.0, "max": 250.0, "unit": "°C", "source": "P3 Tier 1 alias"},
            {"name": "sigma_override", "min": 0.01, "max": 50.0, "unit": "°C", "source": "P3 Tier 1 optional"},
        ],
        "output": {"symbol": "f_native", "min": 0.0, "max": 1.0, "unit": "dimensionless"},
        "fp": {
            "display_name": "Protein Denaturation (van't Hoff sigmoid)",
            "domains": ["protein_science"],
            "keywords_en": ["protein denaturation", "denaturation temperature", "Td", "van't Hoff", "DSC", "native fraction", "thermal stability of protein"],
            "keywords_zh": ["蛋白质变性", "变性温度", "天然态分数", "热稳定性"],
            "parameter_names": ["T_d", "dH_d", "T_C", "sigma_override"],
            "typical_statements": ["WARNING: dH_d in kJ/mol; sigma derived from van't Hoff if not supplied"],
            "source_books": ["Belitz_Food_Chemistry_Ch1", "Privalov_1974"],
            "equation_latex": "f_{native}(T) = \\frac{1}{1+\\exp((T-T_d)/\\sigma)}"
        },
    },
    "MF-K06": {
        "canonical_name": "Growth_Limit",
        "inputs": [
            {"name": "pH_min", "min": 1.0, "max": 14.0, "unit": "pH", "source": "P3 Tier 1"},
            {"name": "a_w_min", "min": 0.5, "max": 1.0, "unit": "dimensionless", "source": "P3 Tier 1"},
            {"name": "T_min", "min": -10.0, "max": 60.0, "unit": "°C", "source": "P3 Tier 1"},
            {"name": "MIC", "min": 0.001, "max": 100000.0, "unit": "ppm", "source": "P3 Tier 1"},
            {"name": "pH", "min": 0.0, "max": 14.0, "unit": "pH", "source": "P3 Tier 1 current"},
            {"name": "a_w", "min": 0.0, "max": 1.0, "unit": "dimensionless", "source": "P3 Tier 1 current"},
            {"name": "T_C", "min": -30.0, "max": 100.0, "unit": "°C", "source": "P3 Tier 1 current"},
            {"name": "T_c", "min": -30.0, "max": 100.0, "unit": "°C", "source": "P3 Tier 1 alias"},
            {"name": "substance_conc", "min": 0.0, "max": 1.0e6, "unit": "ppm", "source": "P3 Tier 1"},
        ],
        "output": {"symbol": "growth_inhibited", "min": 0.0, "max": 1.0, "unit": "boolean"},
        "fp": {
            "display_name": "Microbial Growth Limit Boundary",
            "domains": ["food_safety"],
            "keywords_en": ["minimum pH growth", "minimum water activity", "MIC", "growth limit", "hurdle technology"],
            "keywords_zh": ["生长极限", "最低生长 pH", "最低水活度", "MIC", "栅栏技术"],
            "parameter_names": ["pH_min", "a_w_min", "T_min", "MIC", "pH", "a_w", "T_C", "substance_conc"],
            "typical_statements": ["AND-combination of all supplied hurdles"],
            "source_books": ["ICMSF_2018_v6", "Pitt_Hocking_Fungi"],
            "equation_latex": "\\text{growth} = (pH \\geq pH_{min}) \\wedge (a_w \\geq a_{w,min}) \\wedge (T \\geq T_{min}) \\wedge ([s] \\leq MIC)"
        },
    },
    "MF-T07": {
        "canonical_name": "Dielectric_Properties",
        "inputs": [
            {"name": "epsilon_double_prime", "min": 0.0, "max": 100.0, "unit": "dimensionless", "source": "P3 Tier 1"},
            {"name": "epsilon_pp", "min": 0.0, "max": 100.0, "unit": "dimensionless", "source": "P3 Tier 1 alias"},
            {"name": "frequency", "min": 1.0e6, "max": 3.0e10, "unit": "Hz", "source": "P3 Tier 1 (RF/MW)"},
            {"name": "f", "min": 1.0e6, "max": 3.0e10, "unit": "Hz", "source": "P3 Tier 1 alias"},
            {"name": "E_field", "min": 0.0, "max": 1.0e6, "unit": "V/m", "source": "P3 Tier 1"},
            {"name": "E", "min": 0.0, "max": 1.0e6, "unit": "V/m", "source": "P3 Tier 1 alias"},
        ],
        "output": {"symbol": "P_abs", "min": 0.0, "max": 1.0e9, "unit": "W/m³"},
        "fp": {
            "display_name": "Dielectric Properties for RF/Microwave Heating",
            "domains": ["equipment_physics", "thermal_dynamics"],
            "keywords_en": ["dielectric constant", "loss factor", "microwave heating", "RF heating", "permittivity", "absorbed power"],
            "keywords_zh": ["介电常数", "介电损耗", "微波加热", "射频加热", "吸收功率"],
            "parameter_names": ["epsilon_double_prime", "epsilon_pp", "frequency", "E_field"],
            "typical_statements": ["P_abs = 2π·f·ε₀·ε''·|E|²"],
            "source_books": ["Singh_Heldman_Ch5", "Datta_MW_Food_2000", "Buffler_MW_Cooking"],
            "equation_latex": "P_{abs} = 2\\pi f \\varepsilon_0 \\varepsilon'' |E|^2"
        },
    },
    "MF-T10": {
        "canonical_name": "Starch_Gelatinization",
        "inputs": [
            {"name": "T_C", "min": 0.0, "max": 150.0, "unit": "°C", "source": "P3 Tier 1"},
            {"name": "T_c", "min": 0.0, "max": 150.0, "unit": "°C", "source": "P3 Tier 1 alias"},
            {"name": "time", "min": 0.0, "max": 86400.0, "unit": "s", "source": "P3 Tier 1"},
            {"name": "t", "min": 0.0, "max": 86400.0, "unit": "s", "source": "P3 Tier 1 alias"},
            {"name": "A", "min": 1.0e-3, "max": 1.0e30, "unit": "s⁻¹", "source": "P3 Tier 1 Arrhenius preexp"},
            {"name": "Ea", "min": 0.0, "max": 5.0e5, "unit": "J/mol", "source": "P3 Tier 1"},
            {"name": "n", "min": 0.1, "max": 5.0, "unit": "dimensionless", "source": "P3 Tier 1 Avrami exp"},
            {"name": "water_content", "min": 0.0, "max": 1.0, "unit": "mass fraction", "source": "P3 Tier 1 advisory"},
        ],
        "output": {"symbol": "alpha", "min": 0.0, "max": 1.0, "unit": "dimensionless"},
        "fp": {
            "display_name": "Starch Gelatinization Kinetics (Avrami)",
            "domains": ["carbohydrate"],
            "keywords_en": ["starch gelatinization", "Avrami", "gelatinization extent", "T_gel", "starch hydration"],
            "keywords_zh": ["淀粉糊化", "糊化程度", "Avrami 动力学"],
            "parameter_names": ["T_C", "time", "A", "Ea", "n", "water_content"],
            "typical_statements": ["α(t) = 1 - exp(-k(T)·t^n); k follows Arrhenius"],
            "source_books": ["BeMiller_Whistler_Starch_Ch7", "Marabi_2003_JFE", "Lund_1984"],
            "equation_latex": "\\alpha(t) = 1 - \\exp(-k(T) t^n)"
        },
    },
}

def apply_solver_bounds():
    data = yaml.load(open(SB_FILE))
    if "solvers" not in data:
        print("! malformed solver_bounds.yaml"); return
    added = []
    for mf_id, spec in NEW_MFS.items():
        if mf_id in data["solvers"]:
            print(f"  ! {mf_id} already exists, skipping")
            continue
        solver_entry = {
            "canonical_name": spec["canonical_name"],
            "inputs": spec["inputs"],
            "output": spec["output"],
        }
        data["solvers"][mf_id] = solver_entry
        added.append(mf_id)
    tmp = SB_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        yaml.dump(data, f)
    tmp.rename(SB_FILE)
    print(f"✅ solver_bounds.yaml: +{len(added)} MFs: {added}")
    return added

def apply_fingerprints():
    data = json.load(open(FP_FILE))
    added = []
    for mf_id, spec in NEW_MFS.items():
        if mf_id in data:
            print(f"  ! {mf_id} fingerprint already exists, skipping")
            continue
        fp = spec["fp"]
        data[mf_id] = {
            "id": mf_id,
            "canonical_name": spec["canonical_name"],
            "display_name": fp["display_name"],
            "domains": fp["domains"],
            "keywords_en": fp["keywords_en"],
            "keywords_zh": fp["keywords_zh"],
            "parameter_names": fp["parameter_names"],
            "typical_statements": fp["typical_statements"],
            "source_books": fp["source_books"],
            "equation_latex": fp["equation_latex"],
        }
        added.append(mf_id)
    tmp = FP_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.rename(FP_FILE)
    print(f"✅ mf_fingerprints.json: +{len(added)} MFs: {added}")
    return added

if __name__ == "__main__":
    print("=== P3 Tier 1: Add 4 new MF schemas (T06/K06/T07/T10) ===")
    apply_solver_bounds()
    apply_fingerprints()
