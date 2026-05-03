"""Atomic Mother-Formula solvers.

Each module exposes a single public function:

    solve(params: dict) -> dict

with a uniform return contract documented in `_common.SolveResult`.
First-batch coverage (P1-17): MF-T01, MF-T04, MF-M01, MF-K01, MF-R01.
Subsequent batches will add the remaining 23 MFs from
`config/mother_formulas.yaml`.
"""
