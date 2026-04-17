# Textual Dashboard Report

## Scope

Replaced the watch-driven shell dashboard path with a Python Textual application under `src/dashboard/`. The new app pulls daemon health from `http://localhost:8750`, scans local project state under `~/culinary-mind`, and exposes restart controls that only send `/clear` into tmux agent panes.

## What Changed

- Added a data layer in `src/dashboard/data.py` with proxy-disabled API access, filesystem scans, daemon watchdog restart logic, and tmux restart-clear helpers.
- Added three focused widgets:
  - `pipeline_tree.py` for the three-tier pipeline tree with expandable detail nodes
  - `memory_panel.py` for raw output recency, wiki recency, and `.ce-hub/memory` timestamps
  - `agent_panel.py` for agent status rows and restart buttons
- Added `src/dashboard/app.py` as the Textual entrypoint with a compact fixed layout sized for the tmux dashboard pane.
- Updated `ce-hub/scripts/tui-layout.sh` so pane 0 runs the Textual dashboard instead of the shell dashboard, and `cc-lead` gets `--global`.
- Added `requirements.txt` with `textual`.

## Notes

- `CE_HUB_CWD` now defaults to `~/culinary-mind`, not `~/culinary-engine`.
- All HTTP access clears proxy environment variables and uses direct requests.
- The daemon package currently exposes `npm run daemon`, not `npm run daemon:start`, so the watchdog uses the repo’s actual script.
