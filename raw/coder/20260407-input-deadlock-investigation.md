# Input Box Click Deadlock — Investigation Report

**Date**: 2026-04-07  
**Reporter**: Jeff (via cc-lead dispatch)  
**Symptom**: After clicking another pane or position, clicking back on cc-lead conversation input box causes it to become unresponsive. Must Ctrl+C to recover.

---

## 1. Investigation

### 1.1 Current tmux mouse options

```
mouse on
focus-events off
```

### 1.2 Root MouseDown1Pane binding (before fix)

```
bind-key -T root MouseDown1Pane  select-pane -t = \; send-keys -M
```

### 1.3 Root cause identified: `send-keys -M` forwards click to application

`send-keys -M` means: "send mouse event as terminal escape sequence to the application running in this pane."

Flow when user clicks BACK on agent pane (pane 1) from dashboard pane (pane 0):
1. tmux: `select-pane -t=` → pane 1 becomes active ✓
2. tmux: `send-keys -M` → the MouseDown1 event is forwarded to Claude Code's TUI as a mouse escape sequence

Claude Code's TUI receives a click event at whatever screen coordinates the user clicked. If those coordinates map to:
- The output/scroll area → Claude Code enters text-selection or copy mode
- The input field border → unexpected UI state
- Any UI element → potential lock of input focus

Result: Claude Code's internal state machine enters a sub-state where the input field is not focused, but tmux already handed over control. The user sees the cursor but keystrokes go nowhere (or Claude Code's TUI is processing a mouse sequence that stalled).

### 1.4 Why this is the right diagnosis

Evidence:
- The default tmux binding DOES include `send-keys -M` (we can see it in `tmux list-keys`)
- The symptom is specific to "clicking back" — i.e., cross-pane clicks that switch pane selection THEN forward the click
- After Ctrl+C (which sends SIGINT to foreground process) it recovers — meaning Claude Code's input handler was blocked, not dead

### 1.5 Why `focus-events off` is secondary

Focus events being off means Claude Code doesn't get notified when it loses/regains focus. This could also contribute (Claude Code can't reset internal state on focus regain), but it's not the primary cause here. Enabling focus-events could help as a secondary fix.

---

## 2. Fix Applied

Changed `mouse-bindings.sh`:

```bash
# BEFORE (causes deadlock):
bind-key -T root MouseDown1Pane select-pane -t = \; send-keys -M

# AFTER (safe pane switch, no forwarded click):
bind-key -T root MouseDown1Pane select-pane -t=
```

Why this is safe:
- Claude Code's TUI is keyboard-driven; it doesn't rely on mouse clicks to focus the input
- The input field stays focused after `select-pane` without the forwarded click
- Scroll still works via the separate WheelUpPane/WheelDownPane bindings
- `mouse_any_flag` apps (which request mouse events) still get scroll via the WheelUp binding's `send-keys -M` conditional

Secondary fix: copy-mode click bindings still `clear-selection` to clean up copy state.

---

## 3. Verification

After fix, expected behavior:
- Click dashboard pane (pane 0) → view dashboard, no input to agent
- Click agent pane (pane 1) → cursor enters agent TUI, input field immediately active, no Ctrl+C needed
- Drag-select in agent pane → enters copy-mode, drag selects text
- Scroll in agent pane → scrolls history (WheelUpPane binding unchanged)
