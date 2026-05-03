"""MF-R01 Power_Law — Ostwald-de Waele non-Newtonian rheology.

Equation:
    τ = K · γ̇^n

Behaviour by `n`:
    n < 1   pseudoplastic / shear-thinning  (most foods)
    n = 1   Newtonian                        (τ = K · γ̇, K = µ)
    n > 1   dilatant / shear-thickening

Inputs (per `config/mother_formulas.yaml` → MF-R01):
    Runtime variables: gamma_dot        s⁻¹  shear rate
    One-of-inputs:     [K, n]           K Pa·sⁿ, n dimensionless

Applicable range from yaml: n ∈ [0, 2].
"""

from __future__ import annotations

from typing import Any

from ._common import Validator, build_result


def solve(params: dict) -> dict:
    val = Validator()
    assumptions = ["isothermal", "steady simple-shear flow"]

    gamma_dot = params.get("gamma_dot")
    k         = params.get("K")
    n         = params.get("n")

    val.require_positive("gamma_dot", gamma_dot, allow_zero=True)
    val.require_positive("K", k)
    val.require_finite("n", n)
    if isinstance(n, (int, float)):
        val.require_in_range("n", n, 0.0, 2.0,
                             hint="MF-R01 applicable_range")

    tau: float | None = None
    if all(isinstance(x, (int, float)) for x in (gamma_dot, k, n)) and gamma_dot >= 0 and k > 0:
        if gamma_dot == 0:
            tau = 0.0
            assumptions.append("γ̇ = 0 → τ = 0 (no shear)")
        else:
            tau = float(k) * (float(gamma_dot) ** float(n))
            if n < 1:
                assumptions.append(f"n={n} < 1 → pseudoplastic (shear-thinning)")
            elif abs(n - 1.0) < 1e-9:
                assumptions.append(f"n=1 → Newtonian (K = dynamic viscosity)")
            else:
                assumptions.append(f"n={n} > 1 → dilatant (shear-thickening)")

    return build_result(
        value=tau if tau is not None else float("nan"),
        unit="Pa",
        symbol="tau",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={"gamma_dot": gamma_dot, "K": k, "n": n},
    )
