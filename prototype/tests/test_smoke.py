import subprocess
import sys
from pathlib import Path

from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parents[2]
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "cmind_p1_33_proto")


def test_smoke_output_contains_reasoning_path():
    result = subprocess.run(
        [sys.executable, "prototype/smoke_test.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout.lower()
    assert "chicken" in output
    assert "maillard" in output
    assert "mf_t01" in output
    assert "推理" in result.stdout or "Inference" in result.stdout


def test_vector_indexes_online():
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        with driver.session(database="neo4j") as session:
            count = session.run(
                """
                SHOW INDEXES
                YIELD type, state
                WHERE type = 'VECTOR' AND state = 'ONLINE'
                RETURN count(*) AS online_count
                """
            ).single()["online_count"]
    assert count >= 4
