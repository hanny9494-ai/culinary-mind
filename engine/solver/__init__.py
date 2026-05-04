"""Atomic Mother-Formula solvers.

Each module exposes a single public function:

    solve(params: dict) -> dict

with a uniform return contract documented in `_common.py`.
P1-17 coverage: all 28 configured MF solvers.
"""

from __future__ import annotations

from . import (
    mf_c01,
    mf_c02,
    mf_c03,
    mf_c04,
    mf_c05,
    mf_k01,
    mf_k02,
    mf_k03,
    mf_k04,
    mf_k05,
    mf_m01,
    mf_m02,
    mf_m03,
    mf_m04,
    mf_m05,
    mf_m06,
    mf_r01,
    mf_r02,
    mf_r03,
    mf_r04,
    mf_r05,
    mf_r06,
    mf_r07,
    mf_t01,
    mf_t02,
    mf_t03,
    mf_t04,
    mf_t05,
)

__all__ = [
    "mf_c01",
    "mf_c02",
    "mf_c03",
    "mf_c04",
    "mf_c05",
    "mf_k01",
    "mf_k02",
    "mf_k03",
    "mf_k04",
    "mf_k05",
    "mf_m01",
    "mf_m02",
    "mf_m03",
    "mf_m04",
    "mf_m05",
    "mf_m06",
    "mf_r01",
    "mf_r02",
    "mf_r03",
    "mf_r04",
    "mf_r05",
    "mf_r06",
    "mf_r07",
    "mf_t01",
    "mf_t02",
    "mf_t03",
    "mf_t04",
    "mf_t05",
]
