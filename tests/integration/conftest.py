"""P1-Tx1: pytest fixtures + Neo4j testcontainers for integration tests.

Provides:
- neo4j_session: live Neo4j 5.x test container (requires docker)
- skill_a_records_clean: 10,462 production records
- mf_value_database: P2-Sa1 yaml database

Usage:
    pytest tests/integration -v
"""
import json
import os
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def skill_a_records_clean():
    """Load 10,462 clean Skill A → MF records."""
    p = ROOT / "output/skill_a/mf_parameter_records_clean.jsonl"
    if not p.exists():
        pytest.skip(f"{p} missing — run P2-Sa1 ETL + P2-Sa2 cleaning first")
    recs = []
    with open(p) as f:
        for line in f:
            recs.append(json.loads(line))
    return recs


@pytest.fixture(scope="session")
def mf_value_database():
    """Load mf_parameter_value_database (P2-Sa1 ETL output)."""
    if yaml is None:
        pytest.skip("PyYAML not installed")
    p = ROOT / "output/skill_a/mf_parameter_value_database_clean.yaml"
    if not p.exists():
        pytest.skip(f"{p} missing — run P2-Sa1 ETL first")
    return yaml.safe_load(open(p))


@pytest.fixture(scope="session")
def neo4j_uri():
    """Live cmind-p1-33-neo4j container URI."""
    return os.environ.get("NEO4J_URI", "bolt://localhost:7687")


@pytest.fixture(scope="session")
def neo4j_password():
    """Container password (typical: cmind_p1_33_proto)."""
    return os.environ.get("NEO4J_PASSWORD", "cmind_p1_33_proto")


@pytest.fixture(scope="session")
def neo4j_session(neo4j_uri, neo4j_password):
    """Provides Neo4j session if container is reachable; otherwise skips."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        pytest.skip("neo4j driver not installed (pip install neo4j)")
    try:
        driver = GraphDatabase.driver(neo4j_uri, auth=("neo4j", neo4j_password))
        driver.verify_connectivity()
    except Exception as exc:
        pytest.skip(f"Neo4j unreachable: {exc}")
    with driver.session() as sess:
        yield sess
    driver.close()


@pytest.fixture(scope="session")
def solver_bounds():
    """Load config/solver_bounds.yaml."""
    if yaml is None:
        pytest.skip("PyYAML not installed")
    p = ROOT / "config/solver_bounds.yaml"
    return yaml.safe_load(open(p))
