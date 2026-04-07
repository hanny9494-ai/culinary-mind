# TUI PR#3 Fix Verification Report

**Date**: 2026-04-07  
**Branch**: tui/rebuild-dashboard-window-nav  
**Author**: coder  

---

## Fixes Applied

### Fix 1 — task_id UUID bug (P0) ✅

**Files**: `ce-hub/src/state-store.ts`, `ce-hub/src/types.ts`, `ce-hub/src/file-watcher.ts`

**Problem**: `createTask` always generated a new `uuidv4()` ignoring `input.id`. Dispatch files had IDs like `dispatch_1775543269754` but DB stored random UUIDs → `getTask(taskId)` always returned null → result handler silently failed → task stuck at `pending` forever.

**Fix**:
```typescript
// state-store.ts line 57
id: input.id || uuidv4()   // honors input.id when provided

// types.ts CreateTaskInput
id?: string;               // new optional field

// file-watcher.ts handleDispatch
this.store.createTask({
  id: taskId,              // pass dispatch filename ID
  title: ..., from_agent: ..., to_agent: ..., ...
});
```

**Verification path**: After daemon restart, send dispatch `{id:'test-xyz'}` → `sqlite3 .ce-hub/ce-hub.db "SELECT id,status FROM tasks WHERE id='test-xyz'"` → should return `test-xyz|pending`, then after result file → `test-xyz|done`.

---

### Fix 2 — Pending tasks cleanup script (P0) ✅

**File**: `ce-hub/scripts/fix-pending-tasks.py`

**Problem**: 32 stuck pending tasks in DB (all using random UUID IDs that never matched any result file).

**Script features**:
- Matches result files by `task_id` field → marks matching DB tasks done/failed
- `--expire-hours N` → marks tasks older than N hours as `dead_letter`
- `--dry-run` → preview without writing
- `-v` → verbose showing all task IDs

**Run**:
```bash
# Dry run first
python3 ce-hub/scripts/fix-pending-tasks.py --expire-hours 24 --dry-run -v

# Apply
python3 ce-hub/scripts/fix-pending-tasks.py --expire-hours 24
```

**Applied on 2026-04-07**: 8 tasks expired (>24h), 24 left as pending (no result + <24h or permanently unmatched pre-fix tasks).

---

### Fix 3 — tui-layout.sh idempotency (P0) ✅

**File**: `ce-hub/scripts/tui-layout.sh`

**Problem**: Reviewer blocker — unconditionally `kill-window` on all 9 windows, destroying any existing session.

**Fix**: Idempotent by default:
```bash
# Check: window exists AND has 2 panes → skip
if window_exists "$agent" && [ "$(window_pane_count "$agent")" -eq 2 ] && [ "$force" != "true" ]; then
    echo "  [skip] $agent (already set up)"
    return 0
fi
```

New flags:
- `--force` → rebuild all windows even if correct structure present
- `--reset` → kill session entirely, full rebuild
- `--statusbar-only` → just reapply statusbar + mouse, no window changes

**Verification**: Run `tui-layout.sh` twice — second run shows `[skip]` for all 9 windows, no session disruption.

---

### Fix 4 — Attention state reading in nav bar (P0) ✅

**Files**: `ce-hub/scripts/statusbar.sh`, `ce-hub/scripts/window-label.sh`

**Problem**: Reviewer blocker 2 — `attention.json` was written by file-watcher but never read by statusbar. `monitor-activity on` caused all 9 windows to constantly show activity flag (false positives from any output).

**Fix**:
- `statusbar.sh`: disabled `monitor-activity off`; changed format strings to call `window-label.sh <name> active|inactive`
- `window-label.sh`: reads `attention.json` per call; picks color based on attention state
  - active → orange (`bg=colour214`)
  - attention=true → red (`bg=colour196`)
  - normal inactive → grey (`bg=colour237`)
- Status interval reduced to 3s for faster attention response
- `after-select-window` hook calls `clear-attention.sh` to reset flag when user enters window

**Color scheme**:
```
active window   → #[bg=colour214,fg=colour234,bold]  (orange)
attention=true  → #[bg=colour196,fg=colour231,bold]  (red)
inactive        → #[bg=colour237,fg=colour245]       (grey)
```

**Verification**: 
1. Create/send dispatch to `coder` agent
2. Check `cat .ce-hub/state/attention.json` → `"coder": true`
3. Nav bar should show coder window in red within 3s
4. Click into coder window → `after-select-window` hook fires → `"coder": false`
5. Nav bar returns to grey within 3s

---

### Fix 5 — E2E verification (P1) ✅ (design)

**Status**: Daemon restart + live E2E test requires active tmux session. Steps to run manually:

```bash
# 1. Restart daemon
launchctl kickstart -k gui/$(id -u)/com.cehub.daemon

# 2. Send test dispatch
cat > /tmp/test-dispatch.json << 'EOF'
{"from":"cc-lead","to":"ops","id":"test-e2e-001","task":"Reply pong — test dispatch","priority":1}
EOF
cp /tmp/test-dispatch.json ~/culinary-mind/.ce-hub/dispatch/test-e2e-001.json

# 3. Verify DB
sqlite3 ~/culinary-mind/.ce-hub/ce-hub.db "SELECT id,status FROM tasks WHERE id='test-e2e-001'"
# Expected: test-e2e-001|pending

# 4. Write fake result
cat > ~/culinary-mind/.ce-hub/results/result_ops_test.json << 'EOF'
{"from":"ops","task_id":"test-e2e-001","status":"done","summary":"pong","output_files":[]}
EOF

# 5. Verify DB updated
sqlite3 ~/culinary-mind/.ce-hub/ce-hub.db "SELECT id,status FROM tasks WHERE id='test-e2e-001'"
# Expected: test-e2e-001|done
```

---

### Fix 6 — Input box click deadlock (P0) ✅

**File**: `ce-hub/scripts/mouse-bindings.sh`  
**Investigation**: `raw/coder/20260407-input-deadlock-investigation.md`

**Root cause**: Default tmux binding `bind-key -T root MouseDown1Pane select-pane -t = \; send-keys -M` forwards the mouse click event to the application. When switching FROM dashboard pane (0) BACK to agent pane (1), the click is forwarded to Claude Code's TUI as a mouse escape sequence. Claude Code interprets this as a click on its output area, entering a text-selection state that blocks keyboard input.

**Fix**:
```bash
# BEFORE (causes deadlock):
bind-key -T root MouseDown1Pane select-pane -t = \; send-keys -M

# AFTER (safe):
bind-key -T root MouseDown1Pane select-pane -t=
```

Removed `send-keys -M` — pane click only switches focus, doesn't forward mouse event to app. Scroll/copy-mode still work via their own bindings.

**Verification**: Click dashboard pane → click back on agent pane → type immediately → input works without Ctrl+C.

---

### Fix 7 — Multi-agent E2E test plan (P1) 📋

Full 9-step E2E test to run after daemon is live:

1. Dispatch to researcher: `{"from":"cc-lead","to":"researcher","id":"e2e-researcher-001","task":"Reply pong"}`
2. Verify `attention.json` → `"researcher": true`
3. Researcher writes result to `.ce-hub/results/result_researcher_e2e.json` with `task_id: "e2e-researcher-001"`
4. Verify cc-lead inbox has `result_researcher_*.json`
5. Verify cc-lead pane receives nudge message
6. Verify DB: `SELECT status FROM tasks WHERE id='e2e-researcher-001'` → `done`
7. Click researcher window → `attention.json` → `"researcher": false` → nav bar turns grey
8. Repeat for ops + wiki-curator
9. Send 3 concurrent dispatches → verify 3 windows flash red simultaneously, each clears independently

This test is manually run as the final acceptance criterion.

---

## Files Changed

| File | Change |
|------|--------|
| `ce-hub/src/state-store.ts` | `id: input.id \|\| uuidv4()` |
| `ce-hub/src/types.ts` | Added `id?: string` to `CreateTaskInput` |
| `ce-hub/src/file-watcher.ts` | Pass `id: taskId` to `createTask` |
| `ce-hub/scripts/fix-pending-tasks.py` | New cleanup script |
| `ce-hub/scripts/tui-layout.sh` | Idempotent setup + `--force`/`--statusbar-only` flags |
| `ce-hub/scripts/statusbar.sh` | `monitor-activity off`; call window-label with active/inactive state |
| `ce-hub/scripts/window-label.sh` | Read `attention.json`; emit color-coded format string |
| `ce-hub/scripts/mouse-bindings.sh` | Remove `send-keys -M` from pane click (input deadlock fix) |
| `raw/coder/20260407-input-deadlock-investigation.md` | Investigation report |
| `raw/coder/20260407-tui-pr3-fix-verification.md` | This report |

---

## Next Steps

1. CC Lead to restart daemon: `launchctl kickstart -k gui/$(id -u)/com.cehub.daemon`
2. Run `tui-layout.sh --statusbar-only` to apply new mouse + statusbar bindings
3. Run E2E test steps (Fix 7 checklist)
4. Dispatch code-reviewer for final APPROVE
