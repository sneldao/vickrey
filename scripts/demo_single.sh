#!/usr/bin/env bash
# Single-process field loop: the deployment shape.
#
#   field client (browser)  ->  ledger  ->  embedded block store
#                              |             (same process, separate store)
#                              \-> Atlas commons (when MONGODB_URI is set)
#
# One container, no anchor relay, no separate Hornet: HORNET_EMBEDDED=1 makes the
# ledger hold the tagged-data block itself before reading it back. This is the
# configuration Fly runs. The three-process demo in demo_field.sh is the more
# faithful one -- there the ledger genuinely only ever GETs the block from a
# separate process -- so use that when the point is process separation.
#
# Usage: ./scripts/demo_single.sh
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
LEDGER="http://127.0.0.1:${LEDGER_PORT}"

# HORNET_EMBEDDED is the whole point: no second process, no relay.
HORNET_EMBEDDED=1 \
DATABASE_PATH="${TMP}/ledger.db" \
MONGODB_URI="${MONGODB_URI:-}" \
LEDGER_CORS_ORIGINS="*" \
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

Vickrey single-process field loop is up (embedded anchoring).

  field client   http://127.0.0.1:${FIELD_PORT}/index.html?ledger=${LEDGER}&commons=${LEDGER}
  ledger         ${LEDGER}/docs    (CORS: * )

The client posts straight to the ledger: no relay, no separate Hornet. The
block store is in-process, so run exactly one instance -- a restart drops
registered blocks and strands their records at PENDING.

Load the sample walk, edit the queued copy and watch sync refuse it, then
restore and sync to VERIFIED.

  health         $LEDGER/health

Atlas: $([ -n "${MONGODB_URI:-}" ] && echo "configured (commons search is live)" || echo "not configured (commons panel stays hidden)")

Ctrl-C stops everything. Logs: $TMP
EOF

wait
