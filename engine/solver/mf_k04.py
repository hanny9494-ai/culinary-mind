"""MF-K04 F_Value — integrated thermal lethality.

Formula:
    F = integral(10^((T(t) - T_ref)/z) dt) / 60

References:
    - Thermal process lethality integration.
    - scipy.integrate.quad/simpson for callable and sampled profiles.

Inputs:
    Either T_C + time for a constant process, T_profile callable with
    t_start/t_end, or times_s + temperatures_C arrays. Optional T_ref and z.

Assumptions:
    - input time is seconds
    - output F is minutes at T_ref
"""

from __future__ import annotations

import math
from typing import Any

from scipy import integrate as _integrate

from ._common import Validator, build_result


def _lethality_factor(t_c: float, t_ref: float, z_value: float) -> float:
    return 10.0 ** ((t_c - t_ref) / z_value)


def solve(params: dict) -> dict:
    """Compute equivalent lethality F in minutes."""
    val = Validator()
    assumptions: list[str] = [
        "time basis is seconds",
        "reported F is minutes at T_ref",
    ]

    t_ref = params.get("T_ref", 121.1)
    z_value = params.get("z", 10.0)
    val.require_temperature_celsius("T_ref", t_ref)
    val.require_positive("z", z_value)

    value: float | None = None
    inputs_used: dict[str, Any] = {"T_ref": t_ref, "z": z_value}

    ready = (
        isinstance(t_ref, (int, float)) and not isinstance(t_ref, bool)
        and isinstance(z_value, (int, float)) and not isinstance(z_value, bool)
        and math.isfinite(t_ref) and math.isfinite(z_value) and z_value > 0.0
    )

    if "T_C" in params and ("time" in params or "time_s" in params):
        temp = params.get("T_C")
        time_s = params.get("time", params.get("time_s"))
        inputs_used.update({"T_C": temp, "time": time_s})
        assumptions.append("constant-temperature profile")
        val.require_temperature_celsius("T_C", temp)
        val.require_positive("time", time_s, allow_zero=True)
        if (
            ready
            and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                    for x in (temp, time_s))
            and math.isfinite(temp) and math.isfinite(time_s) and time_s >= 0.0
        ):
            value = _lethality_factor(float(temp), float(t_ref), float(z_value)) * float(time_s) / 60.0

    elif callable(params.get("T_profile")):
        profile = params["T_profile"]
        t_start = params.get("t_start", 0.0)
        t_end = params.get("t_end", params.get("time"))
        inputs_used.update({"T_profile": "<callable>", "t_start": t_start, "t_end": t_end})
        assumptions.append("callable temperature profile integrated with scipy.quad")
        val.require_positive("t_start", t_start, allow_zero=True)
        val.require_positive("t_end", t_end, allow_zero=True)
        if (
            ready
            and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                    for x in (t_start, t_end))
            and math.isfinite(t_start) and math.isfinite(t_end) and t_end >= t_start
        ):
            try:
                integral, _ = _integrate.quad(
                    lambda tt: _lethality_factor(float(profile(tt)), float(t_ref), float(z_value)),
                    float(t_start),
                    float(t_end),
                )
                value = integral / 60.0
            except Exception as exc:
                val.issues.append(f"T_profile integration failed: {exc}")

    elif "times_s" in params and "temperatures_C" in params:
        times = params.get("times_s")
        temps = params.get("temperatures_C")
        inputs_used.update({"times_s": times, "temperatures_C": temps})
        assumptions.append("sampled temperature profile integrated with scipy.simpson")
        if not isinstance(times, (list, tuple)) or not isinstance(temps, (list, tuple)):
            val.issues.append("times_s and temperatures_C must be sequences")
        elif len(times) != len(temps) or len(times) < 2:
            val.issues.append("times_s and temperatures_C must have the same length >= 2")
        else:
            clean_times: list[float] = []
            clean_temps: list[float] = []
            for idx, (time_s, temp) in enumerate(zip(times, temps)):
                val.require_positive(f"times_s[{idx}]", time_s, allow_zero=True)
                val.require_temperature_celsius(f"temperatures_C[{idx}]", temp)
                if (
                    isinstance(time_s, (int, float)) and not isinstance(time_s, bool)
                    and isinstance(temp, (int, float)) and not isinstance(temp, bool)
                    and math.isfinite(time_s) and math.isfinite(temp)
                ):
                    clean_times.append(float(time_s))
                    clean_temps.append(float(temp))
            if len(clean_times) == len(times):
                if any(t2 <= t1 for t1, t2 in zip(clean_times, clean_times[1:])):
                    val.issues.append("times_s must be strictly increasing")
                elif ready:
                    factors = [_lethality_factor(temp, float(t_ref), float(z_value))
                               for temp in clean_temps]
                    value = float(_integrate.simpson(factors, x=clean_times)) / 60.0
    else:
        val.issues.append(
            "provide T_C + time, callable T_profile + t_start/t_end, or times_s + temperatures_C"
        )

    return build_result(
        value=value if value is not None else float("nan"),
        unit="min",
        symbol="F",
        assumptions=assumptions,
        validity=val.result(),
        inputs_used=inputs_used,
    )
