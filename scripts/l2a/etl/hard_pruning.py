"""Step 2 hard pruning rules for L2a atoms.

Day 1 includes the six pollution classes from architect 045:
brand, babyfood, abstract, chemical, data_incomplete, and noise/time_period.
The rule bodies are intentionally conservative and will be widened on Day 2.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


for _proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_proxy_var, None)


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.l2a.etl.utils.checkpointing import CheckpointState, atomic_write_json, load_progress


ABSTRACT_TERMS_SET = {
    "acid",
    "base",
    "batter",
    "blend",
    "extract",
    "flavoring",
    "food",
    "ingredient",
    "liquid",
    "meal",
    "mix",
    "paste",
    "powder",
    "sauce",
    "seasoning",
    "solid",
    "stock",
    "substance",
}

HARD_PRUNING_RULES = {
    "brand": "canonical_id starts with a digit or contains brand-like _bar/_grand markers",
    "babyfood": "canonical_id starts with babyfood_",
    "abstract": "canonical_id is an abstract category word, not an ingredient identity",
    "chemical": "scientific_name and composition indicate a chemical compound or monomer",
    "data_incomplete": "display names are missing or empty",
    "noise": "non-ingredient category such as time_period",
}


@dataclass(frozen=True)
class HardPruneDecision:
    tree_status: str
    exclusion_reason: str | None
    rule: str | None = None


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def hard_prune(atom: dict[str, Any]) -> HardPruneDecision:
    cid = str(atom.get("canonical_id") or "").strip()
    sci = str(atom.get("scientific_name") or "")
    display_name = atom.get("display_name") or {}

    if atom.get("category") == "time_period":
        return HardPruneDecision("excluded", "noise", "noise")

    if re.match(r"^\d", cid) or "_bar" in cid or "_grand" in cid:
        return HardPruneDecision("excluded", "brand", "brand")

    if cid.startswith("babyfood_"):
        return HardPruneDecision("excluded", "babyfood", "babyfood")

    if cid in ABSTRACT_TERMS_SET:
        return HardPruneDecision("excluded", "abstract", "abstract")

    chem_indicators = ("acid", "amine", "oside", "monomer", "-yl", "-ic")
    if sci and any(ind in sci.lower() for ind in chem_indicators):
        comp = atom.get("composition") or {}
        if _num(comp.get("protein_pct")) > 95 or _num(comp.get("water_pct"), 50.0) < 1:
            return HardPruneDecision("excluded", "chemical", "chemical")

    if not display_name.get("zh") and not display_name.get("en"):
        return HardPruneDecision("excluded", "data_incomplete", "data_incomplete")

    return HardPruneDecision("active", None, None)


def run_hard_pruning(
    *,
    atom_dir: Path,
    output_path: Path,
    limit_atoms: int | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path = output_path.parent / "_progress.json"
    state = load_progress(progress_path) if resume else CheckpointState()
    results: list[dict[str, Any]] = []

    for path in sorted(atom_dir.glob("*.json"))[:limit_atoms]:
        atom = json.loads(path.read_text(encoding="utf-8"))
        atom_id = atom.get("canonical_id") or path.stem
        if atom_id in state.processed_atom_ids:
            continue
        decision = hard_prune(atom)
        results.append(
            {
                "atom_id": atom_id,
                "file": str(path),
                "tree_status": decision.tree_status,
                "exclusion_reason": decision.exclusion_reason,
                "rule": decision.rule,
            }
        )
        state.processed_atom_ids.add(atom_id)
        if len(state.processed_atom_ids) % 100 == 0:
            state.metadata["last_step"] = "hard_pruning"
            state.save(progress_path)

    atomic_write_json(output_path, {"results": results})
    state.metadata["last_step"] = "hard_pruning"
    state.save(progress_path)
    return {"step": 2, "count": len(results), "output": str(output_path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run L2a hard pruning")
    parser.add_argument("--atom-dir", type=Path, default=ROOT / "output" / "l2a" / "atoms_r2")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "l2a" / "etl" / "distilled" / "hard_pruned.json")
    parser.add_argument("--limit-atoms", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_hard_pruning(
        atom_dir=args.atom_dir,
        output_path=args.output,
        limit_atoms=args.limit_atoms,
        resume=args.resume,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
