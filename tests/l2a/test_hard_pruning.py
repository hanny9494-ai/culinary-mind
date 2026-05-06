from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.l2a.etl.hard_pruning import hard_prune


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("atom_id", "reason"),
    [
        ("100_grand_bar", "brand"),
        ("babyfood_meat_chicken_junior", "babyfood"),
        ("paste", "abstract"),
        ("proline", "chemical"),
        ("green_mussel", "data_incomplete"),
        ("17th_century", "noise"),
    ],
)
def test_hard_pruning_excludes_six_pollution_classes(atom_id: str, reason: str):
    atom = json.loads((ROOT / "output" / "l2a" / "atoms_r2" / f"{atom_id}.json").read_text(encoding="utf-8"))

    decision = hard_prune(atom)

    assert decision.tree_status == "excluded"
    assert decision.exclusion_reason == reason


def test_hard_pruning_keeps_clean_atom(sample_atom: dict):
    decision = hard_prune(sample_atom)

    assert decision.tree_status == "active"
    assert decision.exclusion_reason is None
