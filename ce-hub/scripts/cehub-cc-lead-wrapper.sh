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

if [ "${CE_HUB_D68_SESSIONS:-0}" != "1" ]; then
  export CE_HUB_CWD
  export CE_HUB_SESSION_ID=""
  exec "$@"
fi

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])'
}

post_json_once() {
  local path="$1"
  local payload="$2"
  curl -fsS --noproxy localhost,127.0.0.1 \
    -H "Content-Type: application/json" \
    -d "$payload" \
    "$CE_HUB_API_URL$path"
}

post_json_with_start_retry() {
  local path="$1"
  local payload="$2"
  local max_attempts=3
  local attempt=1
  local delays=(5 15 45)
  local response

  while [ "$attempt" -le "$max_attempts" ]; do
    if response="$(post_json_once "$path" "$payload" 2>&1)"; then
      printf '%s' "$response"
      return 0
    fi

    echo "[cc-lead-wrapper] start signal attempt $attempt/$max_attempts failed: $response" >&2
    if [ "$attempt" -lt "$max_attempts" ]; then
      sleep "${delays[$((attempt - 1))]}"
    fi
    attempt=$((attempt + 1))
  done

  return 1
}

reason="wrapper_start"
payload=$(printf '{"pid":%d,"wrapper_pid":%d,"reason":"%s"}' "$$" "$$" "$reason")
if ! start_response="$(post_json_with_start_retry "/api/cc-lead/session/start" "$payload")"; then
  echo "[cc-lead-wrapper] aborting: failed to register cc-lead session start after 3 attempts" >&2
  exit 1
fi
SESSION_ID="$(
  printf '%s' "$start_response" | node -e '
    let s = "";
    process.stdin.on("data", d => s += d);
    process.stdin.on("end", () => {
      try { process.stdout.write(JSON.parse(s).session_id || ""); } catch {}
    });
  '
)"

if [ -z "$SESSION_ID" ]; then
  echo "[cc-lead-wrapper] aborting: session start response did not include session_id" >&2
  exit 1
fi

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
end_payload="$(printf '{"session_id":"%s","reason":"%s","exit_code":%d}' "$escaped_session" "$end_reason" "$exit_code")"
if ! end_response="$(post_json_once "/api/cc-lead/session/end" "$end_payload" 2>&1)"; then
  echo "[cc-lead-wrapper] failed to post session end for $SESSION_ID: $end_response" >&2
fi

exit "$exit_code"
