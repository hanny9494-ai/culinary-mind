"""MF-M05 Henry_Law_Aroma — gas-liquid partition by Henry's law.

Formula:
    c_aq = H · p_gas

References:
    - Henry-law solubility form; supplied constants are required because
      general aroma Henry constants are not exposed by CoolProp.

Inputs:
    H, p_gas [Pa] for solubility form Hcp [mol/(m³ Pa)].
    Optional H_form='pressure' uses c_aq = p_gas/H for Hpc [Pa m³/mol].
    Optional H_form='dimensionless' uses c_aq = H · c_gas.

Assumptions:
    - dilute solution
    - supplied H matches substance, solvent, temperature, and unit convention
"""

from __future__ import annotations

import math
from typing import Any

from ._common import Validator, build_result


_R_GAS = 8.31446261815324


def solve(params: dict) -> dict:
    """Compute dissolved concentration from Henry's law."""
    val = Validator()
    assumptions: list[str] = [
        "dilute solution Henry-law regime",
        "Henry constant supplied by caller",
    ]

    h_const = params.get("H")
    p_gas = params.get("p_gas", params.get("p"))
    c_gas = params.get("c_gas")
    h_form = params.get("H_form", "solubility")
    t_c = params.get("T_C", params.get("T_c", 25.0))
    substance = params.get("substance", "aroma")

    if not isinstance(h_form, str):
        val.issues.append("H_form must be a string")
        h_form = "solubility"
    h_form_normalized = h_form.lower()

    val.require_positive("H", h_const)
    val.require_temperature_celsius("T_C", t_c)
    if p_gas is not None:
        val.require_positive("p_gas", p_gas, allow_zero=True)
    if c_gas is not None:
        val.require_positive("c_gas", c_gas, allow_zero=True)

    value: float | None = None
    if (
        isinstance(h_const, (int, float)) and not isinstance(h_const, bool)
        and math.isfinite(h_const) and h_const > 0.0
    ):
        if h_form_normalized in ("solubility", "hcp", "c_over_p"):
            if p_gas is None:
                val.issues.append("p_gas is required for solubility-form Henry law")
            elif isinstance(p_gas, (int, float)) and not isinstance(p_gas, bool) \
                    and math.isfinite(p_gas) and p_gas >= 0.0:
                value = float(h_const) * float(p_gas)
                assumptions.append("H interpreted as Hcp in mol/(m³ Pa)")

        elif h_form_normalized in ("pressure", "hpc", "p_over_c"):
            if p_gas is None:
                val.issues.append("p_gas is required for pressure-form Henry law")
            elif isinstance(p_gas, (int, float)) and not isinstance(p_gas, bool) \
                    and math.isfinite(p_gas) and p_gas >= 0.0:
                value = float(p_gas) / float(h_const)
                assumptions.append("H interpreted as Hpc in Pa·m³/mol")

        elif h_form_normalized in ("dimensionless", "hcc"):
            gas_conc = c_gas
            if gas_conc is None and p_gas is not None:
                if isinstance(t_c, (int, float)) and not isinstance(t_c, bool) \
                        and math.isfinite(t_c) and t_c > -273.15 \
                        and isinstance(p_gas, (int, float)) and not isinstance(p_gas, bool) \
                        and math.isfinite(p_gas) and p_gas >= 0.0:
                    gas_conc = float(p_gas) / (_R_GAS * (float(t_c) + 273.15))
                    assumptions.append("c_gas estimated from ideal gas law")
            if gas_conc is None:
                val.issues.append("c_gas or p_gas + T_C is required for dimensionless Henry law")
            elif isinstance(gas_conc, (int, float)) and not isinstance(gas_conc, bool) \
                    and math.isfinite(gas_conc) and gas_conc >= 0.0:
                value = float(h_const) * float(gas_conc)
                assumptions.append("H interpreted as dimensionless concentration ratio")
        else:
            val.issues.append("H_form must be solubility, pressure, or dimensionless")

        if value == 0.0:
            assumptions.append("zero gas concentration/pressure → c_aq = 0")

    return build_result(
        value=value if value is not None else float("nan"),
        unit="mol/m³",
        symbol="c_aq",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used={
            "substance": substance, "H": h_const, "p_gas": p_gas,
            "c_gas": c_gas, "H_form": h_form, "T_C": t_c,
        },
    )
