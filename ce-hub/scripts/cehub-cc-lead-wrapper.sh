#!/usr/bin/env bash
# Wrap cc-lead so ce-hub can quarantine stale inbox before Claude starts and
# record an explicit end hook when the pane exits.
set -euo pipefail

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-mind}"
CE_HUB_API_URL="${CE_HUB_API_URL:-http://localhost:${CE_HUB_PORT:-8750}}"

if [ "${1:-}" = "--" ]; then
  shift
fi

if [ "$#" -eq 0 ]; then
  set -- claude --model opus --dangerously-skip-permissions --agent cc-lead
fi

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])'
}

post_json() {
  local path="$1"
  local payload="$2"
  curl -fsS --noproxy localhost,127.0.0.1 \
    -H "Content-Type: application/json" \
    -d "$payload" \
    "$CE_HUB_API_URL$path" 2>/dev/null || true
}

reason="wrapper_start"
payload=$(printf '{"pid":%d,"wrapper_pid":%d,"reason":"%s"}' "$$" "$$" "$reason")
start_response="$(post_json "/api/cc-lead/session/start" "$payload")"
SESSION_ID="$(
  printf '%s' "$start_response" | node -e '
    let s = "";
    process.stdin.on("data", d => s += d);
    process.stdin.on("end", () => {
      try { process.stdout.write(JSON.parse(s).session_id || ""); } catch {}
    });
  '
)"

export CE_HUB_CWD
export CE_HUB_SESSION_ID="$SESSION_ID"

"$@" &
child_pid=$!

exit_code=0
wait "$child_pid" || exit_code=$?

end_reason="graceful"
if [ "$exit_code" -ne 0 ]; then
  end_reason="crashed"
fi

escaped_session="$(printf '%s' "$SESSION_ID" | json_escape)"
post_json "/api/cc-lead/session/end" \
  "$(printf '{"session_id":"%s","reason":"%s","exit_code":%d}' "$escaped_session" "$end_reason" "$exit_code")" >/dev/null

exit "$exit_code"
