from __future__ import annotations

import json

from scripts.l2a.etl.utils.checkpointing import CheckpointState, atomic_write_json, load_progress, should_skip


def test_checkpoint_atomic_write_and_resume_skip(tmp_path):
    progress_path = tmp_path / "_progress.json"
    state = CheckpointState(processed_atom_ids={"chicken", "pomfret"}, metadata={"last_step": "main_distill"})

    state.save(progress_path)
    loaded = load_progress(progress_path)

    assert should_skip("chicken", loaded)
    assert not should_skip("beef", loaded)
    assert loaded.metadata["last_step"] == "main_distill"
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_json_replaces_existing_file(tmp_path):
    target = tmp_path / "payload.json"
    atomic_write_json(target, {"version": 1})
    atomic_write_json(target, {"version": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 2}
