# Input Box Click Deadlock & Copy-Mode Leak — Investigation Report

**Date**: 2026-04-07  
**Reporter**: Jeff (via cc-lead dispatch)  
**Symptoms**:
1. After clicking another pane, clicking back on cc-lead conversation input box → becomes unresponsive, must Ctrl+C to recover
2. While typing, screen shows yellow prompt `(jump forward: ___)` — tmux copy-mode vi jump command triggered by the letter 'f'

Both are the same root cause: **tmux mouse events auto-entering copy-mode** and leaking the vi-mode key handler into the Claude Code pane.

---

## 1. Investigation

### 1.1 Current tmux mouse options

```
mouse on
focus-events off
```

### 1.2 Symptom 1: Click deadlock

**Binding (before fix)**:
```
bind-key -T root MouseDown1Pane  select-pane -t = \; send-keys -M
```

`send-keys -M` forwards the mouse click event as a VT escape sequence to Claude Code's TUI. When the click lands on the output area, Claude Code enters text-selection state → keyboard input is routed through the TUI selection handler → input box unresponsive.

**Fix 1 applied**: Removed `send-keys -M`:
```bash
bind-key -T root MouseDown1Pane select-pane -t=
```

### 1.3 Symptom 2: "jump forward" prompt while typing / copy-mode leak

**Binding (before fix)**:
```
bind-key -T root WheelUpPane  if-shell "#{||:#{alternate_on},#{pane_in_mode},#{mouse_any_flag}}" { send-keys -M } { copy-mode -e }
bind-key -T root WheelDownPane send-keys -M
```

Flow (scroll wheel up in agent pane):
1. `alternate_on=0` (Claude Code's TUI may not use alternate screen in some states)
2. `pane_in_mode=0`, `mouse_any_flag=0` → condition is FALSE
3. tmux runs `copy-mode -e` → pane enters copy-mode
4. User doesn't notice the status change `[copy-mode]`
5. User types `f` → copy-mode vi binding for jump-forward fires
6. Yellow prompt appears: `(jump forward: ___)`
7. Any input now goes to copy-mode vi commands, not Claude Code

**Root cause**: `copy-mode -e` enters copy-mode and passes scroll-up to copy buffer. The `alternate_on` check is unreliable — Claude Code's main pane may or may not be in alternate screen depending on its state.

**Fix 2 applied**: Rebind WheelUpPane/Down to always pass to application (never auto-enter copy-mode):
```bash
bind-key -T root WheelUpPane   send-keys -M
bind-key -T root WheelDownPane send-keys -M
```

Why this is safe:
- Claude Code's TUI receives the VT mouse scroll events and handles them internally (scrolling its output view)
- The dashboard pane (`watch -n5`) silently ignores unhandled mouse events — no degradation
- Drag-select still works via `MouseDrag1Pane copy-mode -M` (unchanged)
- User can still enter copy-mode manually via `prefix + [` for read-only browsing

---

## 2. Summary of Fixes

| Fix | Binding | Before | After |
|-----|---------|--------|-------|
| Click deadlock | `MouseDown1Pane` | `select-pane -t= \; send-keys -M` | `select-pane -t=` |
| Scroll→copy-mode | `WheelUpPane` | conditional `copy-mode -e` | `send-keys -M` |
| Scroll passthrough | `WheelDownPane` | conditional `send-keys -M` | `send-keys -M` |

---

## 3. Preserved Functionality

| Feature | Status |
|---------|--------|
| Drag to select + copy to clipboard | ✅ (via `MouseDragEnd1Pane copy-pipe "pbcopy"`) |
| Double-click word select + copy | ✅ (unchanged) |
| Status bar window click nav | ✅ (unchanged) |
| Keyboard copy-mode `prefix + [` | ✅ (unchanged, manual entry) |
| Click pane to switch focus | ✅ (fixed, no click forwarding) |
| Right-click context menu | ✅ (unchanged) |

---

## 4. Verification Checklist

- [ ] Scroll up in agent pane → pane does NOT show `[copy-mode]` in status bar
- [ ] Type `f` in Claude Code input field → types 'f', no yellow jump-forward prompt
- [ ] Click dashboard pane → click back on agent pane → input field immediately responsive
- [ ] Drag across text in any pane → selects text → releases → copied to clipboard
- [ ] Prefix + `[` in any pane → enters copy-mode → `q` exits
