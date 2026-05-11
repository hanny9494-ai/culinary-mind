"""Checkpoint helpers with atomic tmp + os.replace writes."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class CheckpointState:
    processed_atom_ids: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "processed_atom_ids": sorted(self.processed_atom_ids),
            "processed_count": len(self.processed_atom_ids),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **self.metadata,
        }

    def save(self, path: Path) -> None:
        atomic_write_json(path, self.to_json())


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        tmp_name = handle.name
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_name, path)


def load_progress(path: Path) -> CheckpointState:
    if not path.exists():
        return CheckpointState()
    data = json.loads(path.read_text(encoding="utf-8"))
    processed = set(data.get("processed_atom_ids") or [])
    metadata = {key: value for key, value in data.items() if key not in {"processed_atom_ids"}}
    return CheckpointState(processed_atom_ids=processed, metadata=metadata)


def should_skip(atom_id: str, state: CheckpointState) -> bool:
    return atom_id in state.processed_atom_ids
