# OpenClaw Residual Files Recurrence — Root Cause Analysis

**Date**: 2026-05-02
**Curator**: repo-curator
**Status**: Files deleted, root cause partially identified, monitoring needed

## Summary

6 OpenClaw residual files (`AGENTS.md`, `HEARTBEAT.md`, `IDENTITY.md`, `SOUL.md`, `TOOLS.md`, `USER.md`) reappeared in repo root on 2026-05-01 22:01, despite being archived to `_archive/openclaw-legacy/` on 2026-04-26 03:18.

## Timeline

- **2026-04-26 03:18**: cc-lead dispatched repo-curator to delete these 6 files, archived to `_archive/openclaw-legacy/`
- **2026-05-01 22:01**: Files recreated in repo root (confirmed by `ls -la` mtime)
- **2026-05-02 00:29**: Files deleted again by repo-curator

## Investigation

### Files Status
- All 6 files recreated with exact same sizes as archived versions
- Permissions: `rw-------` (600) — more restrictive than archive (644)
- mtime: 2026-05-01 22:01 for all 6 files (same timestamp = batch creation)

### Archive Verification
✅ Backup confirmed in `_archive/openclaw-legacy/`:
```
-rw-r--r--@ 1 jeff  staff  7874 Apr 25 11:25 AGENTS.md
-rw-r--r--@ 1 jeff  staff   193 Apr 25 11:25 HEARTBEAT.md
-rw-r--r--@ 1 jeff  staff   636 Apr 25 11:25 IDENTITY.md
-rw-r--r--@ 1 jeff  staff  3119 Apr 25 11:25 MEMORY.md
-rw-r--r--@ 1 jeff  staff  1673 Apr 25 11:25 SOUL.md
-rw-r--r--@ 1 jeff  staff   860 Apr 25 11:25 TOOLS.md
-rw-r--r--@ 1 jeff  staff   477 Apr 25 11:25 USER.md
```

### Active Processes

1. **OpenClaw Gateway** (launchd agent `ai.openclaw.gateway`)
   - PID: 2114
   - Command: `openclaw-gateway`
   - Working dir: `/` (root filesystem)
   - Launchd plist: `~/Library/LaunchAgents/ai.openclaw.gateway.plist`
   - KeepAlive: true
   - Status: Running since 2026-05-01 19:31

2. **OpenClaw Weixin Poll**
   - PID: 2128
   - Command: `node src/cli/openclaw-weixin-poll.mjs`
   - Working dir: `/Users/jeff/Documents/New project/jeffs-wikis`
   - Not related to culinary-mind

3. **OpenClaw Agents**
   - Found agent directories in `~/.openclaw/agents/`:
     - `main`, `skill-a`, `skill-b`, `skill-c`, `skill-d`, `ocr-claw`, `signal-router`
     - **`ops`** (old name for repo-curator, not renamed in OpenClaw yet)
   - No MD files found in OpenClaw agent directories

### Root Cause Hypothesis

**Most likely**: OpenClaw CLI command executed in culinary-mind directory at 22:01 recreated these files as part of agent initialization.

**Evidence**:
- Batch creation (same timestamp for all 6 files)
- File permissions 600 (suggests programmatic creation)
- OpenClaw gateway running continuously
- OpenClaw agents directory structure matches these filenames

**Trigger unknown**:
- No daemon logs found for 22:01 timeframe
- `~/.openclaw/logs/gateway.log` doesn't show file creation
- No cron jobs or scheduled tasks found

### Preventive Actions Needed

1. **Immediate**: Add `.gitignore` entry for these 6 files (they should never be tracked)
2. **Monitor**: Watch for recreation in next 24h to confirm trigger
3. **OpenClaw cleanup**:
   - Remove or unload `ai.openclaw.gateway` launchd agent (if not needed for culinary-mind)
   - Rename `~/.openclaw/agents/ops/` to `repo-curator` for consistency
4. **Long-term**: If OpenClaw is no longer needed for culinary-mind workflow, consider removing it entirely

## Action Taken

✅ Deleted 6 files from repo root
✅ Verified archive backup intact
✅ Created this report

## Next Steps

1. Add to `.gitignore`:
   ```
   # OpenClaw residual files (legacy, should not be in repo)
   /AGENTS.md
   /HEARTBEAT.md
   /IDENTITY.md
   /SOUL.md
   /TOOLS.md
   /USER.md
   ```

2. Monitor repo root for 24h — if files reappear, capture exact trigger

3. Ask cc-lead/Jeff: Is OpenClaw still needed for culinary-mind workflow?
   - If NO → unload launchd agent, remove from PATH
   - If YES → configure working directory to avoid polluting repo root

## Files Deleted

- `/Users/jeff/culinary-mind/AGENTS.md` (7874 bytes)
- `/Users/jeff/culinary-mind/HEARTBEAT.md` (193 bytes)
- `/Users/jeff/culinary-mind/IDENTITY.md` (636 bytes)
- `/Users/jeff/culinary-mind/SOUL.md` (1673 bytes)
- `/Users/jeff/culinary-mind/TOOLS.md` (860 bytes)
- `/Users/jeff/culinary-mind/USER.md` (477 bytes)

**Total**: 11,713 bytes of legacy files removed
