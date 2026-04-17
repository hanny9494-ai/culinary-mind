#!/usr/bin/env python3
"""
Demo: 2cm 牛排 200°C 煎到 55°C 要多久?
==========================================
Uses Choi-Okos + 1D FDM to simulate pan-searing a 2cm ribeye steak
from room temperature (20°C) to medium-rare (55°C center).

Usage:
    python3 scripts/demo_steak.py
    python3 scripts/demo_steak.py --thickness 0.02 --T-init 20 --T-env 200 --target 55
"""

import os
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_k, None)

import sys
import argparse
from pathlib import Path

# Add scripts dir to path
_scripts = Path(__file__).resolve().parent
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

from choi_okos import choi_okos_properties
from fdm_solver import FDMSolverInput, solve_fdm


def run_demo(
    thickness_m: float = 0.01,   # half-thickness (0.01m = 2cm steak)
    T_init: float = 20.0,
    T_env: float = 200.0,
    target_T: float = 55.0,
    bc_type: str = "convection",
):
    # ── Steak composition (ribeye, approximate) ────────────────────────────
    RIBEYE_COMPOSITION = {
        "water":   0.70,
        "protein": 0.20,
        "fat":     0.08,
        "carb":    0.01,
        "ash":     0.01,
    }

    total_thickness_cm = thickness_m * 2 * 100  # cm, both sides

    print("=" * 62)
    print(f"  DEMO: Pan-Searing a {total_thickness_cm:.0f}cm Ribeye Steak")
    print("=" * 62)
    print(f"  Initial T:   {T_init}°C (room temperature)")
    print(f"  Pan T:       {T_env}°C (cast iron, very hot)")
    print(f"  Target:      {target_T}°C center (medium-rare)")
    print(f"  Geometry:    {total_thickness_cm:.0f}cm slab (symmetric, both sides)")
    print(f"  Composition: water=70% protein=20% fat=8% (ribeye)")
    print()

    # ── Choi-Okos properties at mean temperature ──────────────────────────
    T_mean = (T_init + target_T) / 2.0
    props = choi_okos_properties(RIBEYE_COMPOSITION, T_mean)
    print(f"  Choi-Okos Properties @ {T_mean:.0f}°C (mean):")
    print(f"    Cp  = {props.Cp_J_kgK:>8.1f} J/(kg·K)")
    print(f"    k   = {props.k_W_mK:>8.5f} W/(m·K)")
    print(f"    ρ   = {props.rho_kg_m3:>8.1f} kg/m³")
    print(f"    α   = {props.alpha_m2_s:>8.3e} m²/s")
    print()

    # Characteristic time estimate: L²/α
    t_char = thickness_m**2 / props.alpha_m2_s
    print(f"  Characteristic time L²/α = {t_char:.0f}s ≈ {t_char/60:.1f} min")
    print()

    # ── FDM simulation ─────────────────────────────────────────────────────
    print("  Running FDM simulation...")
    inp = FDMSolverInput(
        shape="slab",
        thickness_m=thickness_m,
        initial_T=T_init,
        env_T=T_env,
        h_conv=30.0,   # 30 W/m²K: effective coeff for pan+imperfect contact
        bc_type=bc_type,
        target_center_T=target_T,
        max_time_s=1800.0,
        composition=RIBEYE_COMPOSITION,
        n_nodes=25,
    )

    result = solve_fdm(inp)

    # ── Results ────────────────────────────────────────────────────────────
    print()
    print("=" * 62)
    print("  RESULTS")
    print("=" * 62)

    if result.time_to_target_s > 0:
        t_s = result.time_to_target_s
        t_min = t_s / 60.0
        print(f"  ✓ Reached {target_T}°C center in:")
        print(f"    {t_s:.0f} seconds  ({t_min:.1f} minutes)")
        print()

        # Physical reasonableness check
        if 240 <= t_s <= 900:
            verdict = "✓ PHYSICALLY REASONABLE (4-15 min range)"
        elif t_s < 240:
            verdict = "⚠ Fast — check BC or composition"
        else:
            verdict = "⚠ Slow — check thickness or BC"
        print(f"  Physical check: {verdict}")
        print()

        # Note about real cooking
        if bc_type == "convection":
            print("  Note: h=30 W/m²K represents effective heat transfer through")
            print("  pan surface + imperfect contact (typical for cast iron pan-searing).")
            print("  Higher h → faster (e.g. h=100 → ~3.5 min); lower h → slower.")
        elif bc_type == "constant_surface":
            print("  Note: 'constant_surface' BC (Bi→∞) overestimates rate.")
            print("  Use --bc convection --h-conv 30 for a more realistic scenario.")
    else:
        print(f"  ⚠ Center temperature did NOT reach {target_T}°C within simulation time.")
        t_last, T_last = result.center_T_history[-1]
        print(f"    Final center T at t={t_last:.0f}s: {T_last:.1f}°C")

    # ── Temperature profile ────────────────────────────────────────────────
    print()
    print("  Center temperature over time:")
    prev_t = -30.0
    for t, T in result.center_T_history:
        if t - prev_t >= 30.0:
            bar_len = max(1, int((T - T_init) / (T_env - T_init) * 30))
            bar = "█" * bar_len
            print(f"    {t:5.0f}s ({t/60:4.1f}m): {T:5.1f}°C  {bar}")
            prev_t = t

    # ── Final temperature profile ──────────────────────────────────────────
    print()
    print("  Final temperature profile (center → surface):")
    for r_m, T in result.final_T_profile[::max(1, len(result.final_T_profile)//6)]:
        pos_pct = r_m / thickness_m * 100
        print(f"    r={r_m*100:.2f}cm ({pos_pct:3.0f}%): {T:.1f}°C")

    print()
    print(f"  FDM metadata: dt={result.metadata.get('dt_s',0):.3f}s, "
          f"Fo={result.metadata.get('stability_Fo','?')}, "
          f"nodes={inp.n_nodes}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Demo: 2cm 牛排 200°C 煎到 55°C")
    parser.add_argument("--thickness", type=float, default=0.01,
                        help="Half-thickness in meters (default 0.01 = 2cm steak)")
    parser.add_argument("--T-init",  type=float, default=20.0,  help="Initial temp (°C)")
    parser.add_argument("--T-env",   type=float, default=200.0, help="Pan temperature (°C)")
    parser.add_argument("--target",  type=float, default=55.0,  help="Target center temp (°C)")
    parser.add_argument("--bc",      choices=["constant_surface","convection","evaporation"],
                        default="convection", help="Boundary condition")
    args = parser.parse_args()

    run_demo(
        thickness_m=args.thickness,
        T_init=args.T_init,
        T_env=args.T_env,
        target_T=args.target,
        bc_type=args.bc,
    )


if __name__ == "__main__":
    main()
