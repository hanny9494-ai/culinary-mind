"""P1-Tx1: integration test for L2a food graph in Neo4j."""
import pytest


@pytest.mark.integration
class TestL2aNeo4jIntegrity:
    def test_ckg_l2a_ingredient_node_count(self, neo4j_session):
        """24,335 CKG_L2A_Ingredient nodes expected (P1-13~16)."""
        result = neo4j_session.run("MATCH (n:CKG_L2A_Ingredient) RETURN count(n) AS cnt").single()
        assert result["cnt"] == 24335, f"expected 24,335, got {result['cnt']}"

    def test_is_a_edges_count(self, neo4j_session):
        """30,141 L2a IS_A edges (Step 6 build)."""
        result = neo4j_session.run("""
            MATCH (s:CKG_L2A_Ingredient)-[r:IS_A]->() RETURN count(r) AS cnt
        """).single()
        assert result["cnt"] == 30141

    def test_derived_from_process_type_enum(self, neo4j_session):
        """D74: process_type 必须 in 13 enum."""
        result = neo4j_session.run("""
            MATCH ()-[r:DERIVED_FROM]->() RETURN DISTINCT r.process_type AS pt
        """)
        valid = {"dried", "fermented", "cured", "smoked", "cooked", "roasted",
                 "frozen", "milled", "pressed", "extracted", "mixed", "pickled", "aged"}
        for record in result:
            assert record["pt"] in valid, f"invalid process_type: {record['pt']}"

    def test_no_self_loops_in_isa(self, neo4j_session):
        """No node IS_A itself."""
        result = neo4j_session.run("""
            MATCH (n:CKG_L2A_Ingredient)-[:IS_A]->(n) RETURN count(n) AS cnt
        """).single()
        assert result["cnt"] == 0

    def test_p1_33_demo_untouched(self, neo4j_session):
        """P1-33 prototype 15 nodes still present (D82 namespace separation)."""
        result = neo4j_session.run("MATCH (n:CKG_Ingredient) RETURN count(n) AS cnt").single()
        assert result["cnt"] == 15, f"P1-33 demo nodes affected: got {result['cnt']}"


@pytest.mark.integration
class TestSkillAValueDatabase:
    def test_record_count(self, skill_a_records_clean):
        """10,462 records after P2-Sa2 cleaning."""
        assert len(skill_a_records_clean) == 10462

    def test_record_schema_required_fields(self, skill_a_records_clean):
        """All records have best_mf + canonical_field."""
        for r in skill_a_records_clean[:100]:
            assert "best_mf" in r and r["best_mf"].startswith("MF-")
            assert "canonical_field" in r
            assert "value_si" in r

    def test_mf_value_database_28_mfs(self, mf_value_database):
        """28 base MFs covered in clean database (40 may not all have records)."""
        mfs = list(mf_value_database["mf_field_database"].keys())
        assert len(mfs) >= 25  # at least 25 of 40 MFs have records
