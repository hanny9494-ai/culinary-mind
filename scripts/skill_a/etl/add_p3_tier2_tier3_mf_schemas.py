#!/usr/bin/env python3
"""P3 Tier 2 + Tier 3: add 8 new MF solver_bounds + fingerprints."""
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
    # Tier 2
    "MF-M07": {
        "canonical_name": "Solubility_Partition",
        "inputs": [
            {"name": "logP", "min": -5.0, "max": 10.0, "unit": "dimensionless", "source": "P3 Tier 2"},
            {"name": "log_p", "min": -5.0, "max": 10.0, "unit": "dimensionless", "source": "P3 Tier 2 alias"},
            {"name": "S_water", "min": 1.0e-12, "max": 100.0, "unit": "mol/L", "source": "P3 Tier 2"},
            {"name": "T_C", "min": 0.0, "max": 100.0, "unit": "°C", "source": "P3 Tier 2"},
            {"name": "T_c", "min": 0.0, "max": 100.0, "unit": "°C", "source": "P3 Tier 2 alias"},
        ],
        "output": {"symbol": "K_partition", "min": 1.0e-5, "max": 1.0e10, "unit": "dimensionless"},
        "fp": {
            "display_name": "Octanol-Water Partition Coefficient (logP)",
            "domains": ["aroma_volatiles", "lipid_science"],
            "keywords_en": ["logP", "octanol-water", "partition coefficient", "solubility", "lipophilicity"],
            "keywords_zh": ["油水分配", "logP", "溶解度", "亲脂性"],
            "parameter_names": ["logP", "S_water", "T_C"],
            "typical_statements": ["K_partition = 10^logP"],
            "source_books": ["Sangster_1997", "Hansch_Leo_QSAR_1995"],
            "equation_latex": "K_{part} = 10^{\\log P}"
        },
    },
    "MF-M08": {
        "canonical_name": "Gas_Permeability",
        "inputs": [
            {"name": "P_O2", "min": 1.0e-5, "max": 1.0e4, "unit": "cm³·mil/(m²·day·atm)", "source": "P3 Tier 2"},
            {"name": "P_CO2", "min": 1.0e-5, "max": 5.0e4, "unit": "cm³·mil/(m²·day·atm)", "source": "P3 Tier 2"},
            {"name": "permeability", "min": 1.0e-5, "max": 5.0e4, "unit": "input units", "source": "P3 Tier 2 generic"},
            {"name": "thickness", "min": 1.0e-6, "max": 0.01, "unit": "m", "source": "P3 Tier 2"},
            {"name": "delta_p", "min": 0.0, "max": 100.0, "unit": "atm", "source": "P3 Tier 2"},
            {"name": "T_C", "min": -30.0, "max": 60.0, "unit": "°C", "source": "P3 Tier 2"},
            {"name": "RH", "min": 0.0, "max": 100.0, "unit": "%", "source": "P3 Tier 2"},
        ],
        "output": {"symbol": "Q_perm", "min": 0.0, "max": 1.0e10, "unit": "permeability·atm/m"},
        "fp": {
            "display_name": "Gas/Vapor Permeability through Packaging Films",
            "domains": ["mass_transfer", "equipment_physics"],
            "keywords_en": ["gas permeability", "OTR", "oxygen transmission", "WVTR", "packaging barrier"],
            "keywords_zh": ["气体渗透", "氧气透过率", "水蒸气渗透", "包装阻隔"],
            "parameter_names": ["P_O2", "P_CO2", "thickness", "delta_p", "T_C", "RH"],
            "typical_statements": ["Steady-state Fickian permeation: Q = P·ΔP/L"],
            "source_books": ["Robertson_Food_Packaging_2013", "ASTM_D3985"],
            "equation_latex": "Q = P \\cdot \\Delta p / L"
        },
    },
    "MF-T08": {
        "canonical_name": "Ohmic_Heating",
        "inputs": [
            {"name": "sigma_25", "min": 1.0e-3, "max": 10.0, "unit": "S/m", "source": "P3 Tier 2"},
            {"name": "sigma_T", "min": 1.0e-3, "max": 10.0, "unit": "S/m", "source": "P3 Tier 2 alias"},
            {"name": "sigma", "min": 1.0e-3, "max": 10.0, "unit": "S/m", "source": "P3 Tier 2 alias"},
            {"name": "alpha", "min": -0.1, "max": 0.5, "unit": "1/°C", "source": "P3 Tier 2"},
            {"name": "E_field", "min": 1.0, "max": 1.0e4, "unit": "V/m", "source": "P3 Tier 2"},
            {"name": "E", "min": 1.0, "max": 1.0e4, "unit": "V/m", "source": "P3 Tier 2 alias"},
            {"name": "T_C", "min": 0.0, "max": 150.0, "unit": "°C", "source": "P3 Tier 2"},
            {"name": "T_c", "min": 0.0, "max": 150.0, "unit": "°C", "source": "P3 Tier 2 alias"},
        ],
        "output": {"symbol": "Q_dot", "min": 0.0, "max": 1.0e9, "unit": "W/m³"},
        "fp": {
            "display_name": "Ohmic (Joule) Heating in Food",
            "domains": ["equipment_physics", "thermal_dynamics"],
            "keywords_en": ["ohmic heating", "joule heating", "electrical conductivity", "sigma"],
            "keywords_zh": ["欧姆加热", "焦耳热", "电导率"],
            "parameter_names": ["sigma_25", "alpha", "E_field", "T_C"],
            "typical_statements": ["Q = σ(T)·E², σ(T) = σ_25·(1+α·(T-25))"],
            "source_books": ["Sastry_Barach_Ohmic_2000", "Singh_Heldman_Ch5"],
            "equation_latex": "Q = \\sigma(T) \\cdot |E|^2"
        },
    },
    "MF-K07": {
        "canonical_name": "Binding_Equilibrium",
        "inputs": [
            {"name": "K_a", "min": 1.0, "max": 1.0e9, "unit": "L/mol", "source": "P3 Tier 2"},
            {"name": "Ka", "min": 1.0, "max": 1.0e9, "unit": "L/mol", "source": "P3 Tier 2 alias"},
            {"name": "K_d", "min": 1.0e-9, "max": 1.0, "unit": "mol/L", "source": "P3 Tier 2"},
            {"name": "Kd", "min": 1.0e-9, "max": 1.0, "unit": "mol/L", "source": "P3 Tier 2 alias"},
            {"name": "L_total", "min": 1.0e-9, "max": 1.0, "unit": "mol/L", "source": "P3 Tier 2"},
            {"name": "L", "min": 1.0e-9, "max": 1.0, "unit": "mol/L", "source": "P3 Tier 2 alias"},
            {"name": "P_total", "min": 1.0e-9, "max": 1.0, "unit": "mol/L", "source": "P3 Tier 2"},
            {"name": "P", "min": 1.0e-9, "max": 1.0, "unit": "mol/L", "source": "P3 Tier 2 alias"},
        ],
        "output": {"symbol": "f_bound", "min": 0.0, "max": 1.0, "unit": "dimensionless"},
        "fp": {
            "display_name": "Ligand-Protein Binding Equilibrium",
            "domains": ["protein_science", "aroma_volatiles"],
            "keywords_en": ["binding constant", "association constant", "Ka", "ligand", "affinity"],
            "keywords_zh": ["结合常数", "亲和力", "配体"],
            "parameter_names": ["K_a", "K_d", "L_total", "P_total"],
            "typical_statements": ["1:1 binding, L_free ≈ L_total"],
            "source_books": ["Bell_Labuza_Moisture", "Tinoco_PhysChem"],
            "equation_latex": "f_{bound} = \\frac{K_a L}{1+K_a L}"
        },
    },
    # Tier 3
    "MF-T09": {
        "canonical_name": "Respiration_Heat",
        "inputs": [
            {"name": "a", "min": 1.0e-3, "max": 10.0, "unit": "W/kg", "source": "P3 Tier 3"},
            {"name": "a_coef", "min": 1.0e-3, "max": 10.0, "unit": "W/kg", "source": "P3 Tier 3 alias"},
            {"name": "b", "min": 0.0, "max": 0.2, "unit": "1/°C", "source": "P3 Tier 3"},
            {"name": "b_coef", "min": 0.0, "max": 0.2, "unit": "1/°C", "source": "P3 Tier 3 alias"},
            {"name": "T_C", "min": -5.0, "max": 35.0, "unit": "°C", "source": "P3 Tier 3"},
            {"name": "T_c", "min": -5.0, "max": 35.0, "unit": "°C", "source": "P3 Tier 3 alias"},
        ],
        "output": {"symbol": "Q_resp", "min": 0.0, "max": 1000.0, "unit": "W/kg"},
        "fp": {
            "display_name": "Postharvest Respiration Heat",
            "domains": ["equipment_physics"],
            "keywords_en": ["respiration heat", "postharvest", "cold storage", "produce"],
            "keywords_zh": ["呼吸热", "果蔬冷藏", "采后"],
            "parameter_names": ["a", "b", "T_C"],
            "typical_statements": ["Q = a·exp(b·T)"],
            "source_books": ["ASHRAE_Refrigeration_2022", "Becker_Misra_Fricke_1996"],
            "equation_latex": "Q_{resp} = a \\cdot \\exp(b \\cdot T)"
        },
    },
    "MF-M09": {
        "canonical_name": "Osmotic_Pressure",
        "inputs": [
            {"name": "M", "min": 1.0e-4, "max": 10.0, "unit": "mol/L", "source": "P3 Tier 3"},
            {"name": "M_osmolar", "min": 1.0e-4, "max": 10.0, "unit": "mol/L", "source": "P3 Tier 3 alias"},
            {"name": "c", "min": 1.0e-4, "max": 10.0, "unit": "mol/L", "source": "P3 Tier 3 alias"},
            {"name": "T_K", "min": 250.0, "max": 400.0, "unit": "K", "source": "P3 Tier 3"},
            {"name": "T_C", "min": -20.0, "max": 100.0, "unit": "°C", "source": "P3 Tier 3"},
            {"name": "T_c", "min": -20.0, "max": 100.0, "unit": "°C", "source": "P3 Tier 3 alias"},
            {"name": "i", "min": 0.5, "max": 10.0, "unit": "dimensionless", "source": "P3 Tier 3 van't Hoff factor"},
        ],
        "output": {"symbol": "pi", "min": 0.0, "max": 5.0e8, "unit": "Pa"},
        "fp": {
            "display_name": "Osmotic Pressure (van't Hoff)",
            "domains": ["mass_transfer"],
            "keywords_en": ["osmotic pressure", "van't Hoff", "osmosis"],
            "keywords_zh": ["渗透压", "范特霍夫", "渗透"],
            "parameter_names": ["M", "T_K", "i"],
            "typical_statements": ["π = i·M·R·T; M in mol/L → factor 1000 to convert to mol/m³"],
            "source_books": ["Atkins_PhysChem", "Singh_Heldman_Osmotic"],
            "equation_latex": "\\pi = i M R T"
        },
    },
    "MF-M11": {
        "canonical_name": "SCFE_Solubility",
        "inputs": [
            {"name": "rho_CO2", "min": 200.0, "max": 1100.0, "unit": "kg/m³", "source": "P3 Tier 3"},
            {"name": "rho", "min": 200.0, "max": 1100.0, "unit": "kg/m³", "source": "P3 Tier 3 alias"},
            {"name": "T_K", "min": 304.0, "max": 500.0, "unit": "K", "source": "P3 Tier 3 (above critical)"},
            {"name": "T_C", "min": 31.0, "max": 200.0, "unit": "°C", "source": "P3 Tier 3"},
            {"name": "T_c", "min": 31.0, "max": 200.0, "unit": "°C", "source": "P3 Tier 3 alias"},
            {"name": "k", "min": 0.0, "max": 50.0, "unit": "dimensionless", "source": "P3 Tier 3 Chrastil exponent"},
            {"name": "a", "min": -10000.0, "max": 10000.0, "unit": "K", "source": "P3 Tier 3 Chrastil"},
            {"name": "b", "min": -100.0, "max": 100.0, "unit": "dimensionless", "source": "P3 Tier 3 Chrastil"},
        ],
        "output": {"symbol": "y_solute", "min": 0.0, "max": 1.0, "unit": "dimensionless (mole fraction)"},
        "fp": {
            "display_name": "Supercritical CO2 Extraction Solubility (Chrastil)",
            "domains": ["mass_transfer"],
            "keywords_en": ["supercritical CO2", "SCFE", "Chrastil", "supercritical extraction"],
            "keywords_zh": ["超临界 CO2", "超临界萃取"],
            "parameter_names": ["rho_CO2", "T_K", "k", "a", "b"],
            "typical_statements": ["Chrastil 1982: ln(y) = k·ln(rho) + a/T + b"],
            "source_books": ["Chrastil_1982_JPhysChem", "Brunner_Gas_Extraction"],
            "equation_latex": "\\ln y = k \\ln \\rho + a/T + b"
        },
    },
    "MF-M10": {
        "canonical_name": "Membrane_Transport",
        "inputs": [
            {"name": "P_solute", "min": 1.0e-12, "max": 1.0e-4, "unit": "m/s", "source": "P3 Tier 3"},
            {"name": "P", "min": 1.0e-12, "max": 1.0e-4, "unit": "m/s", "source": "P3 Tier 3 alias"},
            {"name": "thickness", "min": 1.0e-9, "max": 1.0e-3, "unit": "m", "source": "P3 Tier 3"},
            {"name": "L", "min": 1.0e-9, "max": 1.0e-3, "unit": "m", "source": "P3 Tier 3 alias"},
            {"name": "dC", "min": -10000.0, "max": 10000.0, "unit": "mol/m³", "source": "P3 Tier 3"},
            {"name": "dc", "min": -10000.0, "max": 10000.0, "unit": "mol/m³", "source": "P3 Tier 3 alias"},
            {"name": "delta_c", "min": -10000.0, "max": 10000.0, "unit": "mol/m³", "source": "P3 Tier 3 alias"},
        ],
        "output": {"symbol": "J_solute", "min": -1.0e3, "max": 1.0e3, "unit": "mol/(m²·s)"},
        "fp": {
            "display_name": "Membrane Solute Flux (linear-driving-force)",
            "domains": ["mass_transfer"],
            "keywords_en": ["membrane permeability", "solute flux", "ultrafiltration", "membrane transport"],
            "keywords_zh": ["膜传质", "膜分离", "超滤"],
            "parameter_names": ["P_solute", "thickness", "dC"],
            "typical_statements": ["J = P·ΔC/L"],
            "source_books": ["Mulder_Membrane_1996", "Cheryan_UF_MF_1998"],
            "equation_latex": "J = P \\Delta C / L"
        },
    },
}

def apply_solver_bounds():
    data = yaml.load(open(SB_FILE))
    added = []
    for mf_id, spec in NEW_MFS.items():
        if mf_id in data["solvers"]:
            print(f"  ! {mf_id} already exists")
            continue
        data["solvers"][mf_id] = {
            "canonical_name": spec["canonical_name"],
            "inputs": spec["inputs"],
            "output": spec["output"],
        }
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
            print(f"  ! {mf_id} fingerprint exists")
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
    print("=== P3 Tier 2+3: Add 8 MFs (M07/M08/T08/K07/T09/M09/M11/M10) ===")
    apply_solver_bounds()
    apply_fingerprints()
