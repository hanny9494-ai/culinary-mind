from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def sample_atom() -> dict:
    return {
        "canonical_id": "chicken",
        "display_name": {"zh": "鸡", "en": "chicken"},
        "scientific_name": "Gallus gallus domesticus",
        "composition": {"water_pct": 74.0, "protein_pct": 23.0, "fat_pct": 2.0, "carb_pct": 0.0},
    }


@pytest.fixture
def mock_gemini_response() -> str:
    return """```json
{
  "target_node": {
    "canonical_id": "chicken",
    "display_name_zh": "鸡",
    "display_name_en": "chicken",
    "aliases": [],
    "scientific_name": "Gallus gallus domesticus",
    "form_type": "species",
    "value_kind": "representative_average",
    "tree_status": "active",
    "exclusion_reason": null,
    "peak_season_codes": ["year_round"],
    "peak_months": [],
    "seasonality_records": [],
    "composition_water_pct": 74.0,
    "composition_protein_pct": 23.0,
    "composition_fat_pct": 2.0,
    "composition_carb_pct": 0.0,
    "flavor_profile": ["umami"],
    "texture_raw": "firm",
    "texture_cooked": "tender",
    "culinary_methods": ["roasting"],
    "dietary_flags": ["halal", "kosher", "low_carb"],
    "allergens": [],
    "quality_indicators": [],
    "l0_principle_records": [],
    "embedding_text": "chicken; Gallus gallus domesticus; 鸡; mild poultry"
  },
  "edge_candidates": {
    "is_a": [],
    "part_of": [],
    "derived_from": [],
    "substitutes_raw": [],
    "has_culinary_role": []
  },
  "confidence_overall": 0.93,
  "per_field_confidence": {"identity": 0.95},
  "issue_codes": [],
  "evidence_split_candidates": [],
  "needs_human_review": false
}
```"""


@pytest.fixture
def mock_peer_response() -> str:
    return """{
  "agreement": "agree",
  "corrections": {},
  "issues_added": [],
  "issues_removed": [],
  "reason": "Clean output.",
  "final_review_status": "llm_validated"
}"""
