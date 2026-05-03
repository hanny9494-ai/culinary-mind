from neo4j import GraphDatabase


URI = "bolt://localhost:7687"
AUTH = ("neo4j", "cmind_p1_33_proto")

EXPECTED_LABELS = {
    "CKG_L0_Principle",
    "CKG_PHN",
    "CKG_MF",
    "CKG_Ingredient",
    "CKG_Recipe",
    "CKG_Step",
    "CKG_FT",
    "CKG_L6_Term",
    "CKG_Domain",
    "CKG_ToolFunction",
    "CKG_Equipment",
}

EXPECTED_UNIQUE = {
    ("CKG_L0_Principle", ("id",)),
    ("CKG_PHN", ("phn_id",)),
    ("CKG_MF", ("mf_id",)),
    ("CKG_Ingredient", ("id",)),
    ("CKG_Recipe", ("id",)),
    ("CKG_Step", ("step_id",)),
    ("CKG_FT", ("ft_id",)),
    ("CKG_L6_Term", ("term_id",)),
    ("CKG_Domain", ("name",)),
    ("CKG_ToolFunction", ("tool_id",)),
    ("CKG_Equipment", ("equipment_id",)),
}

EXPECTED_VECTOR_INDEXES = {
    "ckg_l0_embedding_index": "CKG_L0_Principle",
    "ckg_phn_embedding_index": "CKG_PHN",
    "ckg_ft_embedding_index": "CKG_FT",
    "ckg_l6_embedding_index": "CKG_L6_Term",
}


def session():
    driver = GraphDatabase.driver(URI, auth=AUTH)
    driver.verify_connectivity()
    return driver


def test_schema_constraints_and_vector_indexes():
    with session() as driver:
        with driver.session(database="neo4j") as db:
            constraints = [
                dict(row)
                for row in db.run(
                    """
                    SHOW CONSTRAINTS
                    YIELD name, type, labelsOrTypes, properties
                    RETURN name, type, labelsOrTypes, properties
                    """
                )
            ]
            unique = {
                (row["labelsOrTypes"][0], tuple(row["properties"]))
                for row in constraints
                if row["type"] in {"UNIQUENESS", "NODE_UNIQUE"}
            }
            labels_from_constraints = {label for label, _ in unique}

            indexes = [
                dict(row)
                for row in db.run(
                    """
                    SHOW INDEXES
                    YIELD name, type, labelsOrTypes, properties
                    RETURN name, type, labelsOrTypes, properties
                    """
                )
            ]
            vector_indexes = {row["name"]: row for row in indexes if row["type"] == "VECTOR"}
            labels_from_indexes = {
                row["labelsOrTypes"][0]
                for row in indexes
                if row["labelsOrTypes"] and row["labelsOrTypes"][0].startswith("CKG_")
            }

    assert EXPECTED_LABELS <= labels_from_constraints | labels_from_indexes
    assert EXPECTED_UNIQUE <= unique
    assert set(EXPECTED_VECTOR_INDEXES) <= set(vector_indexes)
    for name, label in EXPECTED_VECTOR_INDEXES.items():
        assert vector_indexes[name]["labelsOrTypes"] == [label]
        assert vector_indexes[name]["properties"] == ["embedding"]


def test_vector_index_dimensions_and_similarity():
    with session() as driver:
        with driver.session(database="neo4j") as db:
            rows = [
                dict(row)
                for row in db.run(
                    """
                    SHOW INDEXES
                    YIELD name, type, options
                    WHERE type = 'VECTOR'
                    RETURN name, options
                    """
                )
            ]

    vector_by_name = {row["name"]: row for row in rows}
    for name in EXPECTED_VECTOR_INDEXES:
        options = vector_by_name[name]["options"]
        config = options.get("indexConfig", {})
        assert config.get("vector.dimensions") == 4096
        assert str(config.get("vector.similarity_function")).lower() == "cosine"
