from __future__ import annotations

from scripts.l2a.etl import main_distill


def test_main_distill_parses_mock_llm_schema(mock_gemini_response: str):
    parsed = main_distill.extract_json_object(mock_gemini_response)

    assert parsed["target_node"]["canonical_id"] == "chicken"
    assert parsed["target_node"]["form_type"] == "species"
    assert parsed["edge_candidates"]["is_a"] == []
    assert parsed["confidence_overall"] == 0.93
    assert parsed["needs_human_review"] is False


def test_main_distill_renders_prompt_without_formatting_json_braces(sample_atom: dict):
    messages = main_distill.render_prompt(
        "SYSTEM:\nSystem {atom_id}\nUSER:\nAtom {atom_full_json}\nSiblings {sibling_atoms_array}",
        atom_id="chicken",
        atom=sample_atom,
        siblings=[],
    )

    assert messages[0]["role"] == "system"
    assert "System chicken" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert '"canonical_id": "chicken"' in messages[1]["content"]
