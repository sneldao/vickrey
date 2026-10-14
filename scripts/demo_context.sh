#!/usr/bin/env bash
# Field loop with web context: the full showcase shape.
#
#   field client (browser)  ->  ledger  ->  embedded block store
#                              |         -> fake Tavily (context route)
#                              \-> Atlas commons (when MONGODB_URI is set)
#
# Everything scripts/demo_single.sh runs, plus a stand-in for Tavily so the
# "recent reports" lookup works with no API key and no credits. Point
# TAVILY_API_KEY at a real key and drop TAVILY_ENDPOINT to use the live API.
#
# Usage: ./scripts/demo_context.sh
#        Ctrl-C stops everything.

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VENV="${ROOT}/services/ledger/.venv"
TMP=$(mktemp -d)
PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT INT TERM

free_port() {
  python3 - <<'PY'
import socket
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
}

wait_for() {
  local url="$1" name="$2"
  for _ in $(seq 1 80); do
    if curl -sf "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  echo "$name did not become healthy at $url" >&2
  for log in "$TMP"/*.log; do
    [ -e "$log" ] || continue
    echo "----- $log -----" >&2
    cat "$log" >&2 || true
  done
  exit 1
}

if [[ ! -x "${VENV}/bin/uvicorn" ]]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" -q install -r "$ROOT/services/ledger/requirements.txt"
fi

LEDGER_PORT=$(free_port)
FIELD_PORT=$(free_port)
TAVILY_PORT=$(free_port)
LEDGER="http://127.0.0.1:${LEDGER_PORT}"
FAKE_TAVILY="http://127.0.0.1:${TAVILY_PORT}/search"

python3 "${ROOT}/scripts/fake_tavily.py" --port "${TAVILY_PORT}" \
  >"$TMP/tavily.log" 2>&1 &
PIDS+=($!)

wait_for "http://127.0.0.1:${TAVILY_PORT}/health" "fake tavily"

HORNET_EMBEDDED=1 \
DATABASE_PATH="${TMP}/ledger.db" \
MONGODB_URI="${MONGODB_URI:-}" \
LEDGER_CORS_ORIGINS="*" \
TAVILY_API_KEY="${TAVILY_API_KEY:-tvly-LOCAL-DEMO-NOT-A-REAL-KEY}" \
TAVILY_ENDPOINT="${TAVILY_ENDPOINT:-$FAKE_TAVILY}" \
  "$VENV/bin/uvicorn" app.main:app \
  --app-dir "$ROOT/services/ledger" \
  --host 127.0.0.1 \
  --port "$LEDGER_PORT" \
  >"$TMP/ledger.log" 2>&1 &
PIDS+=($!)

wait_for "$LEDGER/health" "ledger"

python3 -m http.server "$FIELD_PORT" --bind 127.0.0.1 \
  --directory "$ROOT/apps/field" >"$TMP/field.log" 2>&1 &
PIDS+=($!)

wait_for "http://127.0.0.1:${FIELD_PORT}/index.html" "field client"

cat <<EOF

Vickrey field loop with web context is up.

  field client   http://127.0.0.1:${FIELD_PORT}/index.html?ledger=${LEDGER}&commons=${LEDGER}&place=Hackney%2C%20London
  ledger         ${LEDGER}/docs    (CORS: * )

The &place= parameter gives the context lookup a name to search with instead of
a coordinate -- the search never sees a latitude.

Try: load the sample walk, sync it to VERIFIED, then press "Recent reports of
this species" on any anchored record. The answer is shown beside the record and
is never written into it.

  tavily         $([ "${TAVILY_API_KEY:-tvly-LOCAL-DEMO-NOT-A-REAL-KEY}" = "tvly-LOCAL-DEMO-NOT-A-REAL-KEY" ] && echo "fake (local, no credits)" || echo "live API")
  health         $LEDGER/health

Ctrl-C stops everything. Logs: $TMP
EOF

wait
