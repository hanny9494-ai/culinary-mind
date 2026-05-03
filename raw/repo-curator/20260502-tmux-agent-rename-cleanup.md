# [TmuxManager] Unknown Agent "ops" — Cleanup Report

**Date**: 2026-05-02
**Curator**: repo-curator
**Status**: Identified, report filed, code fix requires PR

## Summary

Legacy "ops" agent name found in 2 categories:
1. **Production code** (ce-hub/scripts/tui-layout.sh) — requires PR fix
2. **Runtime archives** (.ce-hub/inbox/, .ce-hub/state/, .ce-hub/raw/) — gitignored, harmless residue

"ops" was renamed to "repo-curator" in D62 (2026-04-24), but not all references were updated.

## Findings

### Category 1: Production Code (Requires Fix)

**File**: `ce-hub/scripts/tui-layout.sh`
- Line 10: Comment shows layout `[cc-lead][coder][research][arch][pipeline][reviewer][ops][datacol][wiki]`
- Line 35: WINDOWS array includes `"ops"`

**Impact**: 
- TUI layout creates "ops" window instead of "repo-curator" window
- Agent process won't start in that window (no `.claude/agents/ops.md` exists)
- Users must manually spawn repo-curator in the ops window

**Fix Required**:
```diff
- "ops"
+ "repo-curator"
```

Must be done via PR (ce-hub code change).

### Category 2: Runtime Archives (Harmless)

**Files** (all gitignored):
- `.ce-hub/inbox/cc-lead/result_ops_*.json` (3 old result files from 2026-04-10)
- `.ce-hub/state/attention.json` — `"ops": false` entry
- `.ce-hub/raw/results.jsonl` — 3 old result records from April
- `.ce-hub/raw/dispatches.jsonl` — 2 old dispatch records from April

**Impact**: None. These are historical archives. File-watcher no longer creates "ops" references.

**Action**: No cleanup needed. Will age out naturally with log rotation.

### Category 3: SQLite Database

**Check**: `sqlite3 ~/.ce-hub/ce-hub.db "SELECT * FROM agent_sessions WHERE agent_name='ops';"`
**Result**: Empty (no records)
**Status**: ✅ Clean

### Category 4: OpenClaw Agents

**Location**: `~/.openclaw/agents/ops/` (directory exists)
**Status**: OpenClaw still uses "ops" name, not synchronized with culinary-mind repo-curator rename
**Action**: Out of scope for culinary-mind repo (OpenClaw is separate system)

## Root Cause

D62 (2026-04-24) renamed ops → repo-curator in:
- `.claude/agents/repo-curator.md` created
- `docs/code-map.yaml` updated
- `docs/merge-policy.yaml` updated

But **missed**:
- `ce-hub/scripts/tui-layout.sh` WINDOWS array
- Comment in tui-layout.sh line 10

## Recommended Fix

### Immediate (This Session)
- ❌ Cannot fix directly (production code, must go through PR)
- ✅ Report filed (this document)
- ✅ No SQLite cleanup needed (already clean)

### Next Session (coder)
Create PR to fix `ce-hub/scripts/tui-layout.sh`:
1. Line 35: `"ops"` → `"repo-curator"`
2. Line 10 comment: `[ops]` → `[repo-curator]`
3. Test: `tui-layout.sh --reset` should create "repo-curator" window, not "ops"

### Optional (Low Priority)
If OpenClaw is still used for culinary-mind:
- Rename `~/.openclaw/agents/ops/` → `~/.openclaw/agents/repo-curator/`
- Update OpenClaw routing config (if exists)

## Impact Assessment

**Current Impact**: Low
- TUI users see "ops" window label but can manually spawn repo-curator
- No functional breakage (daemon, file-watcher, dispatch routing all work)
- Historical archives are harmless

**After Fix**: Cosmetic improvement
- TUI layout matches current agent naming
- Documentation consistency
- No user confusion

## Verification Commands

```bash
# Search all "ops" references in production code
grep -r "\"ops\"" ce-hub/src/ ce-hub/scripts/ | grep -v node_modules

# Check SQLite
sqlite3 ~/.ce-hub/ce-hub.db "SELECT * FROM agent_sessions WHERE agent_name='ops';"

# Check OpenClaw
ls -la ~/.openclaw/agents/ops/ 2>/dev/null
```

## Next Steps

1. ✅ Report complete
2. ⏳ Dispatch coder to create PR fixing tui-layout.sh
3. ⏳ After PR merge, verify TUI layout with `tui-layout.sh --reset`
4. ⏳ Optional: Discuss OpenClaw agent rename with Jeff
