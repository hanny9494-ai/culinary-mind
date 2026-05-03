from neo4j import GraphDatabase


URI = "bolt://localhost:7687"
AUTH = ("neo4j", "cmind_p1_33_proto")


def run_scalar(query: str):
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        with driver.session(database="neo4j") as session:
            return session.run(query).single()[0]


def test_seed_node_counts():
    assert run_scalar("MATCH (:CKG_Ingredient {level: 'generic'}) RETURN count(*)") == 10
    assert run_scalar("MATCH (:CKG_Ingredient {level: 'cut'}) RETURN count(*)") == 5
    assert run_scalar("MATCH (:CKG_PHN) RETURN count(*)") == 5
    assert run_scalar("MATCH (:CKG_MF) RETURN count(*)") == 1
    assert run_scalar("MATCH (:CKG_ToolFunction) RETURN count(*)") == 1
    assert run_scalar("MATCH (:CKG_Equipment) RETURN count(*)") == 5
    assert run_scalar("MATCH (:CKG_Domain) RETURN count(*)") == 18


def test_seed_relationships():
    assert run_scalar("MATCH (:CKG_Ingredient)-[:IS_A]->(:CKG_Ingredient) RETURN count(*)") == 5
    assert run_scalar("MATCH (:CKG_PHN)-[:PRIMARY_DOMAIN]->(:CKG_Domain) RETURN count(*)") == 5
    assert run_scalar("MATCH (:CKG_L0_Principle)-[:PRIMARY_DOMAIN]->(:CKG_Domain) RETURN count(*)") >= 30
    assert run_scalar("MATCH (:CKG_MF)-[:IMPLEMENTED_BY]->(:CKG_ToolFunction) RETURN count(*)") == 1
    assert run_scalar("MATCH (:CKG_Equipment)-[:AFFECTS_PHENOMENON]->(:CKG_PHN) RETURN count(*)") == 5
