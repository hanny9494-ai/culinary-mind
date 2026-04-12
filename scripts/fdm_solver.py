#!/usr/bin/env python3
"""
1D FDM 热传导求解器
====================
Solves the generalized 1D heat conduction equation:

    ∂T/∂t = (1/r^m) · ∂/∂r(r^m · k · ∂T/∂r) / (ρ·Cp)

where m = 0 (slab), 1 (cylinder), 2 (sphere).

Boundary conditions supported:
    - constant_surface (Dirichlet): T_surface = T_env
    - convection (Robin):           -k·∂T/∂r = h·(T_surface − T_env)
    - insulated (Neumann):          ∂T/∂r = 0 (used at center by symmetry)
    - evaporation (extended Robin): -k·∂T/∂r = h·(T_s − T_env) − h_fg·m_dot

This solver is designed as a LangGraph Tool for the L3 reasoning engine.

Usage (Python API):
    from scripts.fdm_solver import FDMSolverInput, FDMSolverOutput, solve_fdm

    result = solve_fdm(FDMSolverInput(
        shape="slab",
        thickness_m=0.01,          # half-thickness (m)
        initial_T=20.0,
        env_T=200.0,
        h_conv=500.0,
        bc_type="constant_surface",
        target_center_T=55.0,
        max_time_s=600.0,
        composition={"water": 0.7, "protein": 0.2, "fat": 0.08, "carb": 0.01, "ash": 0.01},
    ))
    print(f"Time to target: {result.time_to_target_s:.1f}s ({result.time_to_target_s/60:.1f}min)")

CLI:
    python3 scripts/fdm_solver.py --shape slab --thickness 0.01 --T-init 20 --T-env 200 \\
                                   --bc constant_surface --target 55
"""

import os
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_k, None)

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# Add repo root to path for choi_okos import
_repo = Path(__file__).resolve().parents[1]
if str(_repo / "scripts") not in sys.path:
    sys.path.insert(0, str(_repo / "scripts"))


# ══════════════════════════════════════════════════════════════════════════════
# Data models (LangGraph Tool API compatible)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FDMSolverInput:
    """Input parameters for the 1D FDM heat conduction solver."""
    shape: Literal["slab", "cylinder", "sphere"]
    """Geometry: slab (m=0), cylinder (m=1), sphere (m=2)."""

    thickness_m: float
    """Half-thickness (slab) or radius (cylinder/sphere) in meters."""

    initial_T: float
    """Uniform initial temperature of food (°C)."""

    env_T: float
    """Environment / pan / oil temperature (°C)."""

    h_conv: float = 500.0
    """Convective heat transfer coefficient (W/m²·K).
    Typical values: pan-sear ~500-2000, oven ~10-50, deep-fry ~300-700.
    Only used for bc_type='convection' or 'evaporation'."""

    bc_type: Literal["constant_surface", "convection", "insulated", "evaporation"] = "constant_surface"
    """Boundary condition at outer surface."""

    target_center_T: float = 55.0
    """Target center temperature to stop simulation (°C). Use None to run to max_time_s."""

    max_time_s: float = 1800.0
    """Maximum simulation time in seconds."""

    composition: dict = field(default_factory=lambda: {
        "water": 0.70, "protein": 0.20, "fat": 0.08, "carb": 0.01, "ash": 0.01
    })
    """Mass fractions for Choi-Okos property calculation."""

    h_fg_J_kg: float = 2260e3
    """Latent heat of water evaporation (J/kg). Used for evaporation BC."""

    m_dot_evap: float = 0.001
    """Evaporative mass flux (kg/m²·s). Used for evaporation BC."""

    n_nodes: int = 20
    """Number of spatial nodes (more → more accurate, slower)."""


@dataclass
class FDMSolverOutput:
    """Output from the 1D FDM heat conduction solver."""
    time_to_target_s: float
    """Time (s) to reach target center temperature. -1 if not reached."""

    center_T_history: list
    """List of (time_s, T_degC) tuples for center node."""

    surface_T_history: list
    """List of (time_s, T_degC) tuples for surface node."""

    final_T_profile: list
    """List of (r_m, T_degC) tuples at end of simulation."""

    metadata: dict = field(default_factory=dict)
    """Solver metadata: dt_s, stability_r, properties used, etc."""


# ══════════════════════════════════════════════════════════════════════════════
# Solver core
# ══════════════════════════════════════════════════════════════════════════════

_SHAPE_TO_M = {"slab": 0, "cylinder": 1, "sphere": 2}


def solve_fdm(inp: FDMSolverInput) -> FDMSolverOutput:
    """
    Solve 1D heat conduction using explicit finite differences.

    Uses adaptive time stepping to satisfy the stability condition:
        Fo = alpha * dt / dx² <= 0.4
    """
    try:
        import numpy as np
    except ImportError:
        # Pure Python fallback
        return _solve_fdm_pure(inp)

    m = _SHAPE_TO_M[inp.shape]
    N = inp.n_nodes - 1  # index of surface node (0 = center)
    L = inp.thickness_m
    dx = L / N

    # Get properties at mean temperature
    T_mean = (inp.initial_T + inp.env_T) / 2.0
    try:
        from choi_okos import choi_okos_properties
        props = choi_okos_properties(inp.composition, T_mean)
        k = props.k_W_mK
        rho = props.rho_kg_m3
        Cp = props.Cp_J_kgK
        alpha = props.alpha_m2_s
    except ImportError:
        # Fallback to typical beef values
        k, rho, Cp = 0.48, 1060.0, 3550.0
        alpha = k / (rho * Cp)

    # Stability: choose dt such that Fo <= 0.4
    Fo_max = 0.4
    dt = Fo_max * dx**2 / alpha
    dt = min(dt, 1.0)      # cap at 1 second per step
    dt = max(dt, 1e-4)     # floor at 0.1ms

    Fo = alpha * dt / dx**2

    # Build spatial grid: r[i] = i * dx
    r = np.linspace(0.0, L, N + 1)

    # Initialize temperature field
    T = np.full(N + 1, inp.initial_T)

    # Storage for output (sample every ~10s to keep memory manageable)
    sample_dt = max(dt, 10.0)
    next_sample = 0.0
    center_history = [(0.0, float(T[0]))]
    surface_history = [(0.0, float(T[N]))]

    t = 0.0
    time_to_target = -1.0

    max_steps = int(inp.max_time_s / dt) + 1

    for step in range(max_steps):
        T_new = T.copy()

        # ── Interior nodes (1 to N-1) ─────────────────────────────────────
        for i in range(1, N):
            d2T = (T[i-1] - 2*T[i] + T[i+1]) / dx**2
            if m > 0:
                dT_dr = (T[i+1] - T[i-1]) / (2 * dx)
                d2T += m * dT_dr / r[i]
            T_new[i] = T[i] + alpha * dt * d2T

        # ── Center node (i=0): symmetry → T_new[0] via L'Hopital ─────────
        # (1/r^m) * d/dr(r^m * dT/dr)|_{r=0} = (m+1) * d²T/dr²|_{r=0}
        # Using ghost node T[-1] = T[1]:
        T_new[0] = T[0] + (m + 1) * alpha * dt * 2 * (T[1] - T[0]) / dx**2

        # ── Surface node (i=N): boundary condition ────────────────────────
        if inp.bc_type == "constant_surface":
            T_new[N] = inp.env_T

        elif inp.bc_type == "convection":
            # -k*(T[N] - T[N-1])/dx = h*(T[N] - T_env)
            # T[N] = (k/dx * T[N-1] + h * T_env) / (k/dx + h)
            T_new[N] = (k / dx * T[N] + inp.h_conv * inp.env_T) / (k / dx + inp.h_conv)
            # Actually use explicit: update T[N-1] first, then apply Robin
            T_new[N] = (k / dx * T_new[N-1] + inp.h_conv * inp.env_T) / (k / dx + inp.h_conv)

        elif inp.bc_type == "insulated":
            T_new[N] = T_new[N-1]

        elif inp.bc_type == "evaporation":
            # -k*(T[N]-T[N-1])/dx = h*(T[N]-T_env) - h_fg*m_dot
            # T[N] = (k/dx * T[N-1] + h*T_env + h_fg*m_dot) / (k/dx + h)
            T_new[N] = (
                k / dx * T_new[N-1] + inp.h_conv * inp.env_T + inp.h_fg_J_kg * inp.m_dot_evap
            ) / (k / dx + inp.h_conv)

        T = T_new
        t += dt

        # ── Sample output ─────────────────────────────────────────────────
        if t >= next_sample:
            center_history.append((round(t, 2), float(T[0])))
            surface_history.append((round(t, 2), float(T[N])))
            next_sample = t + sample_dt

        # ── Check target ──────────────────────────────────────────────────
        if inp.target_center_T is not None and T[0] >= inp.target_center_T:
            if time_to_target < 0:
                time_to_target = t
            break

    # Final profile
    final_profile = [(round(float(r[i]), 5), round(float(T[i]), 2)) for i in range(N + 1)]

    return FDMSolverOutput(
        time_to_target_s=time_to_target,
        center_T_history=center_history,
        surface_T_history=surface_history,
        final_T_profile=final_profile,
        metadata={
            "shape": inp.shape,
            "m": m,
            "dt_s": dt,
            "dx_m": dx,
            "stability_Fo": round(Fo, 4),
            "n_steps_run": step + 1,
            "properties": {
                "T_mean_C": T_mean,
                "k_W_mK": round(k, 4),
                "rho_kg_m3": round(rho, 1),
                "Cp_J_kgK": round(Cp, 1),
                "alpha_m2_s": f"{alpha:.3e}",
            },
        },
    )


def _solve_fdm_pure(inp: FDMSolverInput) -> FDMSolverOutput:
    """Pure Python fallback (no numpy). Slower but dependency-free."""
    m = _SHAPE_TO_M[inp.shape]
    N = inp.n_nodes - 1
    L = inp.thickness_m
    dx = L / N

    T_mean = (inp.initial_T + inp.env_T) / 2.0
    try:
        from choi_okos import choi_okos_properties
        props = choi_okos_properties(inp.composition, T_mean)
        k = props.k_W_mK
        rho = props.rho_kg_m3
        Cp = props.Cp_J_kgK
        alpha = props.alpha_m2_s
    except ImportError:
        k, rho, Cp = 0.48, 1060.0, 3550.0
        alpha = k / (rho * Cp)

    Fo_max = 0.4
    dt = Fo_max * dx**2 / alpha
    dt = min(dt, 1.0)
    dt = max(dt, 1e-4)
    Fo = alpha * dt / dx**2

    r = [i * dx for i in range(N + 1)]
    T = [inp.initial_T] * (N + 1)

    sample_dt = max(dt, 10.0)
    next_sample = 0.0
    center_history = [(0.0, T[0])]
    surface_history = [(0.0, T[N])]

    t = 0.0
    time_to_target = -1.0
    max_steps = int(inp.max_time_s / dt) + 1
    step = 0

    for step in range(max_steps):
        T_new = T[:]

        # Interior
        for i in range(1, N):
            d2T = (T[i-1] - 2*T[i] + T[i+1]) / dx**2
            if m > 0:
                dT_dr = (T[i+1] - T[i-1]) / (2 * dx)
                d2T += m * dT_dr / r[i]
            T_new[i] = T[i] + alpha * dt * d2T

        # Center (L'Hopital)
        T_new[0] = T[0] + (m + 1) * alpha * dt * 2 * (T[1] - T[0]) / dx**2

        # Surface BC
        if inp.bc_type == "constant_surface":
            T_new[N] = inp.env_T
        elif inp.bc_type == "convection":
            T_new[N] = (k / dx * T_new[N-1] + inp.h_conv * inp.env_T) / (k / dx + inp.h_conv)
        elif inp.bc_type == "insulated":
            T_new[N] = T_new[N-1]
        elif inp.bc_type == "evaporation":
            T_new[N] = (
                k / dx * T_new[N-1] + inp.h_conv * inp.env_T + inp.h_fg_J_kg * inp.m_dot_evap
            ) / (k / dx + inp.h_conv)

        T = T_new
        t += dt

        if t >= next_sample:
            center_history.append((round(t, 2), round(T[0], 2)))
            surface_history.append((round(t, 2), round(T[N], 2)))
            next_sample = t + sample_dt

        if inp.target_center_T is not None and T[0] >= inp.target_center_T:
            if time_to_target < 0:
                time_to_target = t
            break

    final_profile = [(round(r[i], 5), round(T[i], 2)) for i in range(N + 1)]

    return FDMSolverOutput(
        time_to_target_s=time_to_target,
        center_T_history=center_history,
        surface_T_history=surface_history,
        final_T_profile=final_profile,
        metadata={
            "shape": inp.shape,
            "dt_s": dt,
            "stability_Fo": round(Fo, 4),
            "n_steps_run": step + 1,
            "properties": {
                "k_W_mK": round(k, 4),
                "rho_kg_m3": round(rho, 1),
                "Cp_J_kgK": round(Cp, 1),
                "alpha_m2_s": f"{alpha:.3e}",
            },
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="1D FDM 热传导求解器")
    parser.add_argument("--shape", choices=["slab", "cylinder", "sphere"], default="slab")
    parser.add_argument("--thickness", type=float, default=0.01, help="Half-thickness or radius (m)")
    parser.add_argument("--T-init",  type=float, default=20.0,  help="Initial temperature (°C)")
    parser.add_argument("--T-env",   type=float, default=200.0, help="Environment temperature (°C)")
    parser.add_argument("--h-conv",  type=float, default=500.0, help="Convection coefficient (W/m²K)")
    parser.add_argument("--bc",      choices=["constant_surface","convection","insulated","evaporation"],
                        default="constant_surface")
    parser.add_argument("--target",  type=float, default=55.0,  help="Target center temperature (°C)")
    parser.add_argument("--max-time", type=float, default=1800.0, help="Max simulation time (s)")
    parser.add_argument("--water",   type=float, default=0.70)
    parser.add_argument("--protein", type=float, default=0.20)
    parser.add_argument("--fat",     type=float, default=0.08)
    parser.add_argument("--carb",    type=float, default=0.01)
    parser.add_argument("--ash",     type=float, default=0.01)
    parser.add_argument("--nodes",   type=int,   default=20,    help="Number of spatial nodes")
    parser.add_argument("--json-out",action="store_true",       help="Output result as JSON")
    args = parser.parse_args()

    inp = FDMSolverInput(
        shape=args.shape,
        thickness_m=args.thickness,
        initial_T=args.T_init,
        env_T=args.T_env,
        h_conv=args.h_conv,
        bc_type=args.bc,
        target_center_T=args.target,
        max_time_s=args.max_time,
        composition={
            "water": args.water, "protein": args.protein,
            "fat": args.fat, "carb": args.carb, "ash": args.ash,
        },
        n_nodes=args.nodes,
    )

    result = solve_fdm(inp)

    if args.json_out:
        print(json.dumps({
            "time_to_target_s": result.time_to_target_s,
            "time_to_target_min": round(result.time_to_target_s / 60, 2) if result.time_to_target_s > 0 else -1,
            "center_T_history": result.center_T_history[:10],  # first 10 samples
            "final_T_profile": result.final_T_profile,
            "metadata": result.metadata,
        }, ensure_ascii=False, indent=2))
        return

    print(f"\n{'='*58}")
    print(f"  1D FDM Heat Conduction — {args.shape.upper()}")
    print(f"{'='*58}")
    print(f"  Shape:       {args.shape} (m={_SHAPE_TO_M[args.shape]})")
    print(f"  Thickness:   {args.thickness*100:.1f} cm (half-{args.shape} dimension)")
    print(f"  T_initial:   {args.T_init}°C → T_surface: {args.T_env}°C")
    print(f"  BC:          {args.bc}")
    print(f"  Target:      center T = {args.target}°C")
    print(f"{'─'*58}")

    meta = result.metadata
    props = meta.get("properties", {})
    print(f"  Properties @ T_mean={props.get('T_mean_C', '?')}°C (Choi-Okos):")
    print(f"    k={props.get('k_W_mK','?')} W/m·K  "
          f"ρ={props.get('rho_kg_m3','?')} kg/m³  "
          f"Cp={props.get('Cp_J_kgK','?')} J/kg·K")
    print(f"    α={props.get('alpha_m2_s','?')} m²/s  "
          f"(dt={meta.get('dt_s',0):.3f}s, Fo={meta.get('stability_Fo','?')})")
    print(f"{'─'*58}")

    if result.time_to_target_s > 0:
        t_min = result.time_to_target_s / 60.0
        print(f"  ✓ Target reached: {result.time_to_target_s:.1f}s = {t_min:.1f} min")
        print(f"    Physical check:  {'✓ reasonable (4-15 min)' if 240 <= result.time_to_target_s <= 900 else '⚠ outside typical range'}")
    else:
        print(f"  ⚠ Target NOT reached within {args.max_time}s")

    # Print temperature history every ~60s
    print(f"\n  Center temperature history:")
    prev = 0.0
    for t, T in result.center_T_history:
        if t - prev >= 60.0 or t < 30:
            print(f"    t={t:6.0f}s ({t/60:4.1f}min) → T_center={T:.1f}°C")
            prev = t

    print(f"{'='*58}")


if __name__ == "__main__":
    main()
