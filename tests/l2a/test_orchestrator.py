from __future__ import annotations

import asyncio

from scripts.l2a import p1_13_16_etl


def test_orchestrator_resolves_all_steps():
    assert p1_13_16_etl.resolve_steps("all") == [1, 2, 3, 4, 5, 6, 7]
    assert p1_13_16_etl.resolve_steps("3") == [3]


def test_orchestrator_step_route_dry_run():
    parser = p1_13_16_etl.build_parser()
    args = parser.parse_args(["--step", "3", "--limit-atoms", "20", "--dry-run"])

    result = asyncio.run(p1_13_16_etl.run_step(3, args))

    assert result == {"step": 3, "dry_run": True, "limit_atoms": 20}
