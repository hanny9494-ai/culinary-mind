from __future__ import annotations

from scripts.l2a.etl.peer_review import needs_peer_review, parse_peer_review_response


def test_peer_review_parses_mock_schema(mock_peer_response: str):
    parsed = parse_peer_review_response(mock_peer_response)

    assert parsed["agreement"] == "agree"
    assert parsed["final_review_status"] == "llm_validated"


def test_peer_review_trigger_thresholds():
    assert needs_peer_review({"confidence_overall": 0.84})
    assert needs_peer_review({"confidence_overall": 0.95, "issue_codes": ["zh_sci_mismatch"]})
    assert needs_peer_review({"confidence_overall": 0.95, "needs_human_review": True})
    assert not needs_peer_review({"confidence_overall": 0.95, "issue_codes": []})
