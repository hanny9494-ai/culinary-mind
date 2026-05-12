#!/usr/bin/env python3
"""Advanced case studies: chocolate tempering + SCFE caffeine + sourdough fermentation.

Each chain exercises 3-6 MFs across thermal/kinetic/mass-transfer domains.
"""
import sys
import math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from engine.solver import (
    mf_t02_k, mf_t02_cp, mf_t02_rho,
    mf_t01, mf_t03, mf_t05, mf_t06,
    mf_k01, mf_k02, mf_k05,
    mf_m01, mf_m02, mf_m11,
)


def _h(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def case_chocolate_tempering():
    _h("CASE A: Chocolate Tempering (cocoa butter Form V crystallization)")
    print("  Setup: melted dark chocolate cooled from 50→27→32°C controlled cycle")
    print()
    # Chocolate composition (rough)
    choc = {
        "composition.water": 0.01, "composition.protein": 0.07,
        "composition.fat": 0.34, "composition.carb": 0.55,
        "composition.fiber": 0.005, "composition.ash": 0.025,
        "Xw": 0.01, "Xp": 0.07, "Xf": 0.34, "Xc": 0.55, "Xfiber": 0.005, "Xa": 0.025,
    }
    for T in [50.0, 27.0, 32.0, 18.0]:
        out_k = mf_t02_k.solve({**choc, "T_C": T})
        out_cp = mf_t02_cp.solve({**choc, "T_C": T})
        out_rho = mf_t02_rho.solve({**choc, "T_C": T})
        print(f"  T={T:>5.1f}°C: k={out_k['result']['value']:.3f} W/(m·K), "
              f"Cp={out_cp['result']['value']:.0f} J/(kg·K), "
              f"ρ={out_rho['result']['value']:.0f} kg/m³")

    # Form V cocoa butter Td = 33.8°C (Belitz Food Chemistry)
    print()
    print("  Form V cocoa butter melt-fraction (treating as 'reverse' protein analogy):")
    print(f"    T_d=33.8°C (Form V), σ=2°C empirical width")
    for T in [27.0, 30.0, 32.0, 33.8, 36.0, 40.0]:
        out = mf_t06.solve({"T_d": 33.8, "T_C": T, "sigma_override": 2.0})
        f_native = out["result"]["value"]
        f_melt = 1 - f_native
        print(f"    T={T:>5.1f}°C → solid fraction {f_native:.3f}, melt {f_melt:.3f}")
    print()
    print("  → Tempering at 32°C: solid fraction ~73% (Form V solid, others melted)")


def case_scfe_caffeine():
    _h("CASE B: SCFE Caffeine Extraction (Chrastil-style)")
    print("  Setup: caffeine in supercritical CO2 at 313 K, varying ρ")
    print()
    # Chrastil caffeine params (Brunner 1994)
    KW = {"k": 4.85, "a": -7000.0, "b": -23.0}
    print(f"  Chrastil constants for caffeine: k={KW['k']}, a={KW['a']}, b={KW['b']}")
    print()
    print(f"  {'ρ_CO2 (kg/m³)':>14}  {'y_solute':>12}  {'mg/kg CO2':>11}")
    for rho in [300, 500, 700, 800, 900, 1000]:
        out = mf_m11.solve({"rho_CO2": float(rho), "T_K": 313.0, **KW})
        y = out["result"]["value"]
        if isinstance(y, float) and math.isfinite(y):
            # Convert mole fraction → mg caffeine per kg CO2 (caffeine MW=194, CO2=44)
            mg_per_kg = y * 194.0 / 44.0 * 1e6
            print(f"  {rho:>14}  {y:>12.4e}  {mg_per_kg:>11.2f}")

    print()
    print("  → Higher CO2 density (deeper sub-critical to supercritical) → exponentially more caffeine extracted")


def case_sourdough_fermentation():
    _h("CASE C: Sourdough Fermentation (Lactic Acid Bacteria growth)")
    print("  Setup: refresh whole-wheat dough at 28°C, 12h fermentation")
    print()
    # Gompertz parameters for L. plantarum @ 28°C (literature)
    A = 7.5
    mu_max = 0.6  # /h slower than yogurt
    lam = 2.0
    print(f"  Gompertz: A={A} log10, μ_max={mu_max} /h, λ={lam} h")
    print()
    print(f"  {'time (h)':>9}  {'log10(N/N0)':>13}  {'Population (×N0)':>17}")
    for t in [0, 2, 4, 6, 8, 10, 12, 24]:
        out = mf_k05.solve({"A": A, "mu_max": mu_max, "lambda": lam, "t": float(t)})
        v = out["result"]["value"]
        if isinstance(v, float) and math.isfinite(v):
            print(f"  {t:>9}  {v:>13.3f}  {10**v:>17.2e}")

    # Arrhenius for acidification rate vs T
    print()
    print(f"  Acidification rate (Arrhenius, Ea=70 kJ/mol):")
    for T_C in [22.0, 25.0, 28.0, 30.0, 35.0]:
        T_K = T_C + 273.15
        out = mf_t03.solve({"A": 1e10, "Ea": 70000.0, "T_K": T_K})
        k = out["result"]["value"]
        rel = k / 0.0001  # baseline
        if isinstance(k, float) and math.isfinite(k):
            print(f"    {T_C:>5}°C → k={k:.3e} s⁻¹ ({rel:.2f}× baseline)")


def main():
    case_chocolate_tempering()
    case_scfe_caffeine()
    case_sourdough_fermentation()
    print("\n" + "=" * 72)
    print("✅ 3 ADVANCED CASE STUDIES COMPLETE")
    print("   Used MFs: T02-K/CP/RHO, T03, T06, K05, M11")
    print("=" * 72)


if __name__ == "__main__":
    main()
