#!/usr/bin/env python3
"""P4-Be2 lite: feed real Skill A values into MF solvers."""
import importlib
import json
import math
import yaml
from collections import defaultdict
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

ROOT = Path("/Users/jeff/culinary-mind")
RECORDS_FILE = ROOT / "output/skill_a/mf_parameter_records_clean.jsonl"
REPORT_FILE = ROOT / "output/skill_a/mf_benchmark_report.yaml"
DETAIL_FILE = ROOT / "output/skill_a/mf_benchmark_records.jsonl"

DEFAULTS = {
    "MF-T01": {"T_init": 25.0, "T_boundary": 100.0, "time": 600.0, "x_position": 0.01, "alpha": 1.4e-7, "thickness": 0.02, "k": 0.5, "rho": 1000.0, "Cp": 3800.0},
    "MF-T02-K": {"T_C": 25.0, "composition.water": 0.7, "composition.protein": 0.15, "composition.fat": 0.1, "composition.carb": 0.04, "composition.fiber": 0.005, "composition.ash": 0.005},
    "MF-T02-CP": {"T_C": 25.0, "composition.water": 0.7, "composition.protein": 0.15, "composition.fat": 0.1, "composition.carb": 0.04, "composition.fiber": 0.005, "composition.ash": 0.005},
    "MF-T02-RHO": {"T_C": 25.0, "composition.water": 0.7, "composition.protein": 0.15, "composition.fat": 0.1, "composition.carb": 0.04, "composition.fiber": 0.005, "composition.ash": 0.005},
    "MF-T03": {"A": 1.0e10, "Ea": 50000.0, "T_K": 363.0},
    "MF-T04": {"Re": 1.0e4, "Pr": 7.0, "C": 0.023, "m": 0.8, "n": 0.4},
    "MF-T05": {"rho": 1000.0, "L_f": 3.34e5, "d": 0.01, "a": 1.0, "T_f": 0.0, "T_inf": -20.0, "T_m": 0.0, "h": 50.0, "k": 0.5},
    "MF-T06": {"T_d": 70.0, "dH_d": 300.0, "T_C": 70.0},
    "MF-T07": {"epsilon_double_prime": 10.0, "frequency": 2.45e9, "E_field": 1000.0},
    "MF-T08": {"sigma_25": 0.5, "alpha": 0.02, "E_field": 100.0, "T_C": 50.0},
    "MF-T09": {"a": 0.05, "b": 0.08, "T_C": 4.0},
    "MF-T10": {"T_C": 80.0, "time": 600.0, "A": 1.0e8, "Ea": 80000.0, "n": 1.5},
    "MF-K01": {"Vmax": 1.0e-5, "Km": 1.0e-4, "S": 1.0e-3},
    "MF-K02": {"t": 60.0, "N": 1.0e2, "N0": 1.0e6},
    "MF-K03": {"T1": 121.1, "T2": 100.0, "D1": 12.0, "D2": 36.0},
    "MF-K04": {"T_ref": 121.1, "z": 10.0, "T_C": 121.1, "time": 180.0},
    "MF-K05": {"A": 1.0, "mu_max": 0.5, "lam": 1.0, "t": 5.0},
    "MF-K06": {"pH_min": 4.6, "a_w_min": 0.92, "T_min": 5.0, "MIC": 100.0, "pH": 5.0, "a_w": 0.93, "T_C": 10.0, "substance_conc": 50.0},
    "MF-K07": {"K_a": 1.0e6, "L_total": 1.0e-6, "P_total": 1.0e-7},
    "MF-M01": {"C_init": 0.0, "C_boundary": 100.0, "D": 1.0e-9, "D_eff": 1.0e-9, "x": 0.005, "x_position": 0.005, "time": 3600.0, "thickness": 0.02},
    "MF-M02": {"a_w": 0.5, "W_m": 0.08, "Xm": 0.08, "C": 10.0, "K": 0.9},
    "MF-M03": {"T_C": 80.0, "substance": "water"},
    "MF-M04": {"pKa": 4.76, "A_minus_conc": 0.5, "HA_conc": 0.5},
    "MF-M05": {"H": 1.0e5, "p_gas": 1000.0, "T_C": 25.0},
    "MF-M06": {"T_C": 25.0, "substance": "water"},
    "MF-M07": {"logP": 1.0, "S_water": 0.01, "T_C": 25.0},
    "MF-M08": {"P_O2": 100.0, "thickness": 1.0e-4, "delta_p": 0.21, "T_C": 25.0, "RH": 50.0},
    "MF-M09": {"M": 0.5, "T_K": 298.15, "i": 1.0},
    "MF-M10": {"P_solute": 1.0e-7, "thickness": 1.0e-4, "dC": 100.0},
    "MF-M11": {"rho_CO2": 800.0, "T_K": 313.0, "k": 4.85, "a": -7000.0, "b": -23.0},
    "MF-R01": {"K": 1.0, "n": 0.5, "gamma_dot": 100.0},
    "MF-R02": {"tau_0": 5.0, "K": 1.0, "n": 0.5, "gamma_dot": 100.0},
    "MF-R03": {"tau_0": 5.0, "K_C": 1.0, "gamma_dot": 100.0},
    "MF-R04": {"w1": 0.5, "w2": 0.5, "Tg1": -100.0, "Tg2": 100.0, "k": 1.0},
    "MF-R05": {"T": 80.0, "Tg": 50.0, "C1": 17.44, "C2": 51.6},
    "MF-R06": {"k": 1.0, "I": 100.0, "n": 0.3},
    "MF-R07": {"E": 1.0e9, "gamma_s": 1.0, "a": 1.0e-4},
    "MF-C01": {"r": 1.0e-6, "rho_p": 1100.0, "rho_f": 1000.0, "eta": 1.0e-3, "g": 9.81},
    "MF-C02": {"M_h": 100.0, "M_l": 200.0, "M": 300.0},
    "MF-C03": {"A_H": 1.0e-20, "kappa": 1.0e8, "zeta": 0.03, "epsilon_r": 80.0, "T": 298.0, "D": 5.0e-9},
    "MF-C04": {"sigma": 0.07, "R": 1.0e-3},
    "MF-C05": {"k1": 1.0e-5, "k2": 5.0e-5, "T1": 25.0, "T2": 35.0},
}

def main():
    records = []
    with open(RECORDS_FILE) as f:
        for line in f:
            records.append(json.loads(line))
    print(f"Loaded {len(records):,} clean records")

    by_mf_field = defaultdict(list)
    for r in records:
        by_mf_field[(r["best_mf"], r["canonical_field"])].append(r)

    SAMPLE_LIMIT = 30
    bench_results = []
    by_mf_stats = defaultdict(lambda: {
        "total_records": 0, "tested": 0,
        "validity_passed": 0, "validity_failed": 0,
        "nan_output": 0, "no_solver": 0, "no_default": 0,
        "issues_by_type": defaultdict(int),
    })

    for (mf, field), recs in sorted(by_mf_field.items()):
        stats = by_mf_stats[mf]
        stats["total_records"] += len(recs)
        # MF-T02 is parent_only; route to T02-K/-CP/-RHO children based on field
        # For benchmark purposes we test each record against MF-T02-CP (most common: composition fields)
        if mf == "MF-T02":
            # Route to MF-T02-CP as default child for parent records (cp uses all composition + T_C)
            mf_for_solve = "MF-T02-CP"
            mod_name = "engine.solver.mf_t02_cp"
        else:
            mf_for_solve = mf
            mod_name = f"engine.solver.{mf.lower().replace('-', '_')}"
        try:
            solver_mod = importlib.import_module(mod_name)
        except ModuleNotFoundError:
            stats["no_solver"] += len(recs); continue
        if not hasattr(solver_mod, "solve"):
            stats["no_solver"] += len(recs); continue
        defaults = DEFAULTS.get(mf_for_solve, DEFAULTS.get(mf))
        if defaults is None:
            stats["no_default"] += len(recs); continue

        sampled = recs[:SAMPLE_LIMIT]
        for r in sampled:
            stats["tested"] += 1
            v = r.get("value_si")
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                stats["nan_output"] += 1; continue
            params = dict(defaults)
            params[field] = v
            try:
                out = solver_mod.solve(params)
            except Exception as exc:
                stats["validity_failed"] += 1
                stats["issues_by_type"]["exception"] += 1
                bench_results.append({"mf": mf, "field": field, "value": v, "status": "exception", "error": str(exc)[:200]})
                continue
            passed = out["validity"]["passed"]
            value_out = out["result"]["value"]
            if passed:
                stats["validity_passed"] += 1
                if isinstance(value_out, float) and (math.isnan(value_out) or math.isinf(value_out)):
                    stats["nan_output"] += 1
            else:
                stats["validity_failed"] += 1
                for issue in out["validity"]["issues"]:
                    if "outside bounds" in issue: stats["issues_by_type"]["bounds_violation"] += 1
                    elif "finite" in issue: stats["issues_by_type"]["non_finite"] += 1
                    else: stats["issues_by_type"]["other"] += 1
            bench_results.append({
                "mf": mf, "field": field,
                "value_si": v, "unit_si": r.get("unit_si"),
                "book": r["book"], "page": r.get("page"),
                "passed": passed,
                "output_symbol": out["result"]["symbol"],
                "output_value": value_out if isinstance(value_out, (int, float)) and math.isfinite(value_out) else str(value_out),
                "output_unit": out["result"]["unit"],
                "issues_count": len(out["validity"]["issues"]),
            })

    with open(DETAIL_FILE, "w") as f:
        for r in bench_results: f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {}
    for mf in sorted(by_mf_stats):
        s = by_mf_stats[mf]
        pass_rate = round(s["validity_passed"] * 100 / s["tested"], 1) if s["tested"] else 0
        summary[mf] = {
            "total_records": s["total_records"], "tested": s["tested"],
            "passed": s["validity_passed"], "failed": s["validity_failed"],
            "pass_rate_pct": pass_rate, "nan_output": s["nan_output"],
            "no_solver": s["no_solver"], "issues_by_type": dict(s["issues_by_type"]),
        }
    overall_tested = sum(s["tested"] for s in by_mf_stats.values())
    overall_passed = sum(s["validity_passed"] for s in by_mf_stats.values())
    report = {
        "version": "1.0",
        "generated_at": "2026-05-11",
        "description": "P4-Be2 lite: real Skill A values fed into 40 MF solvers",
        "global": {
            "total_records": sum(s["total_records"] for s in by_mf_stats.values()),
            "total_tested": overall_tested,
            "total_passed": overall_passed,
            "global_pass_rate_pct": round(overall_passed * 100 / overall_tested, 1) if overall_tested else 0,
        },
        "by_mf": summary,
    }
    REPORT_FILE.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))
    print(f"\n=== Benchmark ===")
    print(f"Tested: {overall_tested}  Passed: {overall_passed}  ({report['global']['global_pass_rate_pct']}%)")
    print()
    print(f"{'MF':<10} {'rec':>5} {'test':>5} {'pass':>5} {'%':>6}  Top issue")
    print("-"*68)
    for mf in sorted(summary):
        s = summary[mf]
        top = max(s["issues_by_type"].items(), key=lambda x: x[1], default=("-", 0))
        print(f"{mf:<10} {s['total_records']:>5} {s['tested']:>5} {s['passed']:>5} {s['pass_rate_pct']:>5}%  {top[0]}={top[1]}")

if __name__ == "__main__":
    main()
