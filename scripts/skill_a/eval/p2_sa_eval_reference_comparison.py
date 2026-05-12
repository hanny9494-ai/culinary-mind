#!/usr/bin/env python3
"""P2-Sa-eval: compare MF solver outputs vs published reference values."""
import sys
import math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import yaml

ROOT = Path("/Users/jeff/culinary-mind")
OUT_FILE = ROOT / "output/skill_a/p2_sa_eval_report.yaml"

REFERENCE_CASES = [
    {
        "name": "Water boiling vapor pressure @ 100°C",
        "mf": "engine.solver.mf_m03",
        "params": {"T_C": 100.0, "substance": "water"},
        "expected": 101325.0, "tolerance_pct": 5.0,
        "citation": "NIST WebBook: water saturation P @ 100°C = 101.325 kPa",
        "expected_unit": "Pa",
    },
    {
        "name": "Pure water specific heat @ 25°C",
        "mf": "engine.solver.mf_t02_cp",
        "params": {"T_C": 25.0, "composition.water": 1.0, "composition.protein": 0.0,
                   "composition.fat": 0.0, "composition.carb": 0.0,
                   "composition.fiber": 0.0, "composition.ash": 0.0,
                   "Xw": 1.0, "Xp": 0.0, "Xf": 0.0, "Xc": 0.0, "Xfiber": 0.0, "Xa": 0.0},
        "expected": 4181.3, "tolerance_pct": 5.0,
        "citation": "NIST: water Cp @ 25°C = 4.1813 kJ/(kg·K)",
        "expected_unit": "J/(kg·K)",
    },
    {
        "name": "Pure water density @ 25°C",
        "mf": "engine.solver.mf_t02_rho",
        "params": {"T_C": 25.0, "composition.water": 1.0, "composition.protein": 0.0,
                   "composition.fat": 0.0, "composition.carb": 0.0,
                   "composition.fiber": 0.0, "composition.ash": 0.0,
                   "Xw": 1.0, "Xp": 0.0, "Xf": 0.0, "Xc": 0.0, "Xfiber": 0.0, "Xa": 0.0},
        "expected": 997.0, "tolerance_pct": 3.0,
        "citation": "NIST: water density @ 25°C = 997.05 kg/m³",
        "expected_unit": "kg/m³",
    },
    {
        "name": "Arrhenius k(35°C) Ea=60 kJ/mol — analytical identity",
        "mf": "engine.solver.mf_t03",
        "params": {"A": 1.0e12, "Ea": 60000.0, "T_K": 308.15},
        "expected": 1.0e12 * math.exp(-60000.0 / (8.314 * 308.15)),
        "tolerance_pct": 1.0,
        "citation": "k = A·exp(-Ea/RT) analytical",
        "expected_unit": "s⁻¹",
    },
    {
        "name": "Gordon-Taylor Tg mix (50/50, Tg1=100, Tg2=-100, k=0.5)",
        "mf": "engine.solver.mf_r04",
        "params": {"w1": 0.5, "w2": 0.5, "Tg1": 100.0, "Tg2": -100.0, "k": 0.5},
        "expected": (0.5*100 + 0.5*0.5*(-100)) / (0.5 + 0.5*0.5),  # 33.33
        "tolerance_pct": 5.0,
        "citation": "Gordon-Taylor (1952) analytical",
        "expected_unit": "°C",
    },
    {
        "name": "Apple respiration heat @ 1°C (ASHRAE)",
        "mf": "engine.solver.mf_t09",
        "params": {"a": 0.011, "b": 0.10, "T_C": 1.0},
        "expected": 0.011 * math.exp(0.10),
        "tolerance_pct": 5.0,
        "citation": "ASHRAE Refrigeration: Golden Delicious @ 1°C",
        "expected_unit": "W/kg",
    },
    {
        "name": "Microwave 2.45 GHz E=50 V/m ε''=10 → P_abs",
        "mf": "engine.solver.mf_t07",
        "params": {"epsilon_double_prime": 10.0, "frequency": 2.45e9, "E_field": 50.0},
        "expected": 2 * math.pi * 2.45e9 * 8.8541878128e-12 * 10.0 * 50.0**2,
        "tolerance_pct": 0.5,
        "citation": "Maxwell P_abs analytical",
        "expected_unit": "W/m³",
    },
    {
        "name": "Henderson-Hasselbalch [A-]=[HA] → pH=pKa",
        "mf": "engine.solver.mf_m04",
        "params": {"pKa": 4.76, "A_minus_conc": 0.5, "HA_conc": 0.5},
        "expected": 4.76, "tolerance_pct": 0.5,
        "citation": "Buffer textbook: pH = pKa when [A-]=[HA]",
        "expected_unit": "pH",
    },
    {
        "name": "Protein denaturation @ T=T_d → f_native = 0.5",
        "mf": "engine.solver.mf_t06",
        "params": {"T_d": 65.0, "dH_d": 400.0, "T_C": 65.0},
        "expected": 0.5, "tolerance_pct": 0.5,
        "citation": "Sigmoid midpoint analytical",
        "expected_unit": "dimensionless",
    },
    {
        "name": "Osmotic π for 1 M ideal solute @ 298.15 K (van't Hoff)",
        "mf": "engine.solver.mf_m09",
        "params": {"M": 1.0, "T_K": 298.15, "i": 1.0},
        "expected": 1.0 * 1000.0 * 8.314462618 * 298.15,  # ≈ 2.479e6 Pa
        "tolerance_pct": 0.5,
        "citation": "van't Hoff π = MRT analytical",
        "expected_unit": "Pa",
    },
]


def run_eval():
    import importlib
    results = []
    pass_count, fail_count = 0, 0

    for case in REFERENCE_CASES:
        mf_mod = importlib.import_module(case["mf"])
        out = mf_mod.solve(case["params"])
        actual = out["result"]["value"]
        passed_solver = out["validity"]["passed"]
        expected = case["expected"]

        if not passed_solver:
            results.append({**case, "actual": None, "passed": False,
                            "deviation_pct": None, "status": "SOLVER_REJECTED",
                            "issues": out["validity"]["issues"][:3]})
            fail_count += 1
            continue

        if not isinstance(actual, (int, float)) or not math.isfinite(actual):
            results.append({**case, "actual": str(actual), "passed": False,
                            "deviation_pct": None, "status": "NON_FINITE"})
            fail_count += 1
            continue

        if expected == 0:
            dev_pct = abs(actual)
        else:
            dev_pct = abs((actual - expected) / expected) * 100.0
        within_tol = dev_pct <= case["tolerance_pct"]

        results.append({**case, "actual": actual, "passed": within_tol,
                        "deviation_pct": round(dev_pct, 3),
                        "status": "PASS" if within_tol else "FAIL_TOLERANCE"})
        if within_tol: pass_count += 1
        else: fail_count += 1

    return results, pass_count, fail_count


def main():
    print("=" * 90)
    print("P2-Sa-eval: MF Solver vs Reference Values")
    print("=" * 90)
    results, n_pass, n_fail = run_eval()
    total = n_pass + n_fail
    pct = n_pass*100/total if total else 0
    print(f"\nGlobal: {n_pass}/{total} passed ({pct:.0f}% within tolerance)\n")
    print(f"{'#':>2} {'Name':<55} {'Δ%':>7}  Status")
    print("-" * 90)
    for i, r in enumerate(results, 1):
        dev = f"{r['deviation_pct']:.2f}" if r["deviation_pct"] is not None else "  -"
        symbol = "✅" if r["passed"] else "❌"
        print(f"{i:>2} {symbol} {r['name'][:53]:<55} {dev:>7}  {r['status']}")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "version": "1.0", "generated_at": "2026-05-12",
        "global": {"total": total, "passed": n_pass, "failed": n_fail,
                   "pass_rate_pct": round(pct, 1)},
        "results": [{
            "name": r["name"], "mf": r["mf"], "params": r["params"],
            "expected": r["expected"], "actual": r["actual"],
            "deviation_pct": r["deviation_pct"], "tolerance_pct": r["tolerance_pct"],
            "expected_unit": r["expected_unit"], "status": r["status"],
            "passed": r["passed"], "citation": r["citation"],
            "issues": r.get("issues", []),
        } for r in results],
    }
    OUT_FILE.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))
    print(f"\n✅ {OUT_FILE}\n")
    print("Failures (need investigation):")
    for r in results:
        if not r["passed"]:
            print(f"  - {r['name']}: expected {r['expected']} {r['expected_unit']}, got {r['actual']}, dev {r['deviation_pct']}%")
            if r.get("issues"): print(f"    issues: {r['issues']}")

if __name__ == "__main__":
    main()
