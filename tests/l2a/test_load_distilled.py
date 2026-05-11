from __future__ import annotations

import json

from scripts.l2a.etl import _load_distilled


def test_load_all_distilled_repairs_codex_and_counts_current_sources():
    records = _load_distilled.load_all_distilled()

    assert len(records) == 21423
    ids = {record["atom_id"] for record in records}
    assert "poppyseed_cake" in ids
    assert "snickers_almond" in ids
    poppyseed = next(record for record in records if record["atom_id"] == "poppyseed_cake")
    assert "edge_candidates" in poppyseed


def test_missing_gemini_atom_id_falls_back_to_file_stem(tmp_path, monkeypatch):
    gemini_path = tmp_path / "gemini.json"
    codex_dir = tmp_path / "codex"
    codex_dir.mkdir()
    gemini_path.write_text(
        json.dumps({"results": [{"atom_id": "", "file": "output/l2a/atoms_r2/_progress.json"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(_load_distilled, "GEMINI_PARTIAL", gemini_path)
    monkeypatch.setattr(_load_distilled, "CODEX_DIR", codex_dir)

    records = _load_distilled.load_all_distilled()

    assert records == [{"atom_id": "_progress", "file": "output/l2a/atoms_r2/_progress.json", "_source": "gemini"}]
