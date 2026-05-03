#!/usr/bin/env bash
set -euo pipefail

CE_HUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WRAPPER="$CE_HUB_DIR/scripts/cehub-cc-lead-wrapper.sh"
TUI_LAYOUT="$CE_HUB_DIR/scripts/tui-layout.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

bash -n "$WRAPPER"
bash -n "$TUI_LAYOUT"

mkdir -p "$TMP_DIR/bin" "$TMP_DIR/work"

cat > "$TMP_DIR/bin/curl" <<'CURL'
#!/usr/bin/env bash
printf 'curl\n' >> "$TEST_CALLS"
exit 7
CURL
chmod +x "$TMP_DIR/bin/curl"

cat > "$TMP_DIR/bin/sleep" <<'SLEEP'
#!/usr/bin/env bash
printf 'sleep %s\n' "$*" >> "$TEST_SLEEPS"
exit 0
SLEEP
chmod +x "$TMP_DIR/bin/sleep"

cat > "$TMP_DIR/bin/claude" <<'CLAUDE'
#!/usr/bin/env bash
printf 'claude launched\n' >> "$TEST_CLAUDE"
exit 0
CLAUDE
chmod +x "$TMP_DIR/bin/claude"

export PATH="$TMP_DIR/bin:$PATH"
export TEST_CALLS="$TMP_DIR/calls.log"
export TEST_SLEEPS="$TMP_DIR/sleeps.log"
export TEST_CLAUDE="$TMP_DIR/claude.log"
export CE_HUB_CWD="$TMP_DIR/work"
export CE_HUB_API_URL="http://127.0.0.1:1"
export CE_HUB_D68_SESSIONS=1

set +e
"$WRAPPER" -- claude --version 2> "$TMP_DIR/wrapper.err"
status=$?
set -e

if [ "$status" -ne 1 ]; then
  echo "expected wrapper to exit 1 after start signal failures, got $status" >&2
  exit 1
fi

curl_count="$(wc -l < "$TEST_CALLS" | tr -d ' ')"
if [ "$curl_count" != "3" ]; then
  echo "expected 3 start signal attempts, got $curl_count" >&2
  exit 1
fi

if [ -f "$TEST_CLAUDE" ]; then
  echo "wrapper launched claude after failed session registration" >&2
  exit 1
fi

grep -q 'start signal attempt 3/3 failed' "$TMP_DIR/wrapper.err"
grep -q 'aborting: failed to register cc-lead session start after 3 attempts' "$TMP_DIR/wrapper.err"

grep -Fq '[ "$agent" = "cc-lead" ] && [ "${CE_HUB_D68_SESSIONS:-0}" = "1" ]' "$TUI_LAYOUT"
wrapper_line="$(grep -n 'cehub-cc-lead-wrapper.sh -- claude' "$TUI_LAYOUT" | head -1 | cut -d: -f1)"
start_line=$((wrapper_line > 3 ? wrapper_line - 3 : 1))
if ! sed -n "${start_line},${wrapper_line}p" "$TUI_LAYOUT" | grep -Fq 'CE_HUB_D68_SESSIONS'; then
  echo "tui-layout.sh wrapper command is not guarded by CE_HUB_D68_SESSIONS" >&2
  exit 1
fi

echo "shell tests passed"
