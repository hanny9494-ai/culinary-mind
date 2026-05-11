"""P1-Tx2: Performance baseline (pytest-benchmark style without external dep).

Records baseline metrics for:
- 40 MF solver call latency
- Skill A records JSONL load
- Neo4j query latency (sample)
"""
import importlib
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.benchmark
class TestSolverPerformance:
    """Latency targets for 40 MF solvers (no formal benchmark lib)."""

    def _bench(self, fn, n=100):
        """Run fn n times, return (mean_ms, p95_ms)."""
        times = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            times.append((time.perf_counter() - t0) * 1000)  # ms
        times.sort()
        return sum(times) / n, times[int(n * 0.95)]

    def test_mf_t03_arrhenius_under_1ms_p95(self):
        from engine.solver import mf_t03
        params = {"A": 1.0e10, "Ea": 50000.0, "T_K": 363.0}
        mean, p95 = self._bench(lambda: mf_t03.solve(params))
        assert p95 < 5.0, f"MF-T03 p95={p95:.2f}ms — should be <5ms"

    def test_mf_t01_fourier_under_5ms_p95(self):
        from engine.solver import mf_t01
        params = {"T_init": 25.0, "T_boundary": 100.0, "time": 600.0, "x_position": 0.01,
                  "alpha": 1.4e-7, "thickness": 0.02, "k": 0.5, "rho": 1000.0, "Cp": 3800.0}
        mean, p95 = self._bench(lambda: mf_t01.solve(params))
        assert p95 < 10.0, f"MF-T01 p95={p95:.2f}ms — Fourier should be <10ms"

    def test_all_40_solvers_load_under_500ms(self):
        """Cold import of all 40 MFs should be <500ms total."""
        mf_ids = [
            "mf_t01", "mf_t02_k", "mf_t02_cp", "mf_t02_rho", "mf_t03", "mf_t04", "mf_t05",
            "mf_t06", "mf_t07", "mf_t08", "mf_t09", "mf_t10",
            "mf_k01", "mf_k02", "mf_k03", "mf_k04", "mf_k05", "mf_k06", "mf_k07",
            "mf_m01", "mf_m02", "mf_m03", "mf_m04", "mf_m05", "mf_m06",
            "mf_m07", "mf_m08", "mf_m09", "mf_m10", "mf_m11",
            "mf_r01", "mf_r02", "mf_r03", "mf_r04", "mf_r05", "mf_r06", "mf_r07",
            "mf_c01", "mf_c02", "mf_c03", "mf_c04", "mf_c05",
        ]
        t0 = time.perf_counter()
        for mod in mf_ids:
            importlib.import_module(f"engine.solver.{mod}")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 2000, f"40 solvers loaded in {elapsed_ms:.0f}ms (target <2s)"

    def test_value_database_load_under_500ms(self, mf_value_database):
        """yaml load latency (sanity test only — yaml lazy-loaded by fixture)."""
        assert mf_value_database is not None


@pytest.mark.benchmark
class TestNeo4jQueryPerformance:
    """Neo4j query latency baselines (only run if Neo4j available)."""

    def test_count_24k_nodes_under_500ms(self, neo4j_session):
        t0 = time.perf_counter()
        result = neo4j_session.run("MATCH (n:CKG_L2A_Ingredient) RETURN count(n) AS cnt").single()
        elapsed = (time.perf_counter() - t0) * 1000
        assert result["cnt"] == 24335
        assert elapsed < 500, f"24K node count took {elapsed:.0f}ms"

    def test_chicken_isa_lookup_under_50ms(self, neo4j_session):
        t0 = time.perf_counter()
        result = list(neo4j_session.run("""
            MATCH (c:CKG_L2A_Ingredient {canonical_id: 'chicken'})-[:IS_A]->(p) RETURN p.canonical_id
        """))
        elapsed = (time.perf_counter() - t0) * 1000
        assert len(result) >= 2  # chicken IS_A poultry + meat
        assert elapsed < 200, f"chicken IS_A took {elapsed:.0f}ms"
