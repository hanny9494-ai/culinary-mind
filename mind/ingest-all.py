#!/usr/bin/env python3
"""ingest-all.py — Batch ingest all source documents into the wiki.

Usage:
  ingest-all.py              — ingest all sources in priority order
  ingest-all.py --dry-run    — show plan without writing
"""

import os
import sys
import glob

MIND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_REPORTS = os.path.join(MIND_DIR, "raw", "reports")

# Import ingest function
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib.machinery import SourceFileLoader
ingest_mod = SourceFileLoader("ingest_source", os.path.join(os.path.dirname(__file__), "ingest-source.py")).load_module()


def get_priority_sources():
    """Return source files in priority order."""
    sources = []

    # Priority 1: Core project docs
    for name in ["CLAUDE.md", "STATUS.md"]:
        path = os.path.join(RAW_REPORTS, name)
        if os.path.exists(path):
            sources.append(path)

    # Priority 2: Design docs
    design_docs = [
        "l2a_atom_schema_v2.md",
        "l2b_stepb_prompt_design.md",
        "e2e_inference_design.md",
        "api_routing.md",
        "system_architecture_evaluation.md",
        "pipeline_scripts.md",
    ]
    for name in design_docs:
        path = os.path.join(RAW_REPORTS, name)
        if os.path.exists(path):
            sources.append(path)

    # Priority 3: Research docs
    for f in sorted(glob.glob(os.path.join(RAW_REPORTS, "research_*.md"))):
        sources.append(f)

    # Priority 4: ce-hub docs
    for name in ["cehub_handover.md", "ONBOARD.md"]:
        path = os.path.join(RAW_REPORTS, name)
        if os.path.exists(path):
            sources.append(path)

    return sources


def main():
    dry_run = "--dry-run" in sys.argv
    sources = get_priority_sources()

    print(f"[ingest-all] Found {len(sources)} source files")
    for i, src in enumerate(sources):
        print(f"  {i+1}. {os.path.basename(src)}")

    print()
    for i, src in enumerate(sources):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(sources)}] {os.path.basename(src)}")
        print(f"{'='*60}")
        ingest_mod.ingest_source(src, dry_run)


if __name__ == "__main__":
    main()
