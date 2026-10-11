#!/usr/bin/env bash
# Field loop demo: mock Hornet + evidence ledger + anchor relay + field client.
#
#   client (browser)  ->  anchor relay  ->  mock Hornet
#                            \->  ledger  ->  mock Hornet (independent GET)
#
# Open the printed field URL, seal an observation (sample ID works with no
# model running), verify the chain, edit the last entry, and sync it.
#
# Points at a local MongoDB Atlas cluster if MONGODB_URI is exported; without
# it, the commons search reports "no observation store configured" and the rest
# of the loop still works.
#
# Usage: ./scripts/demo_field.sh
#        Ctrl-C stops everything.

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VENV="${ROOT}/services/ledger/.venv"
TMP=$(mktemp -d)
PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    [[ -n "${pid}" ]] && kill "${pid}" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  rm -rf "${TMP}"
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
  for _ in $(seq 1 60); do
    if curl -sf "${url}" >/dev/null; then
      return 0
    fi
    sleep 0.2
  done
  echo "${name} did not become healthy at ${url}" >&2
  for log in "${TMP}"/*.log; do
    echo "----- ${log} -----" >&2
    cat "${log}" >&2 || true
  done
  exit 1
}

if [[ ! -x "${VENV}/bin/uvicorn" ]]; then
  python3 -m venv "${VENV}"
  "${VENV}/bin/pip" install -r "${ROOT}/services/ledger/requirements.txt"
fi

HORNET_PORT=$(free_port)
LEDGER_PORT=$(free_port)
RELAY_PORT=$(free_port)
FIELD_PORT=$(free_port)

HORNET="http://127.0.0.1:${HORNET_PORT}"
LEDGER="http://127.0.0.1:${LEDGER_PORT}"
RELAY="http://127.0.0.1:${RELAY_PORT}"

python3 "${ROOT}/scripts/mock_hornet.py" --port "${HORNET_PORT}" \
  >"${TMP}/hornet.log" 2>&1 &
PIDS+=("$!")

DATABASE_PATH="${TMP}/ledger.db" \
  HORNET_URL="${HORNET}" \
  MONGODB_URI="${MONGODB_URI:-}" \
  LEDGER_CORS_ORIGINS="*" \
  "${VENV}/bin/uvicorn" app.main:app \
  --app-dir "${ROOT}/services/ledger" \
  --host 127.0.0.1 \
  --port "${LEDGER_PORT}" \
  >"${TMP}/ledger.log" 2>&1 &
PIDS+=("$!")

wait_for "${LEDGER}/health" "ledger"

python3 "${ROOT}/scripts/anchor_relay.py" \
  --port "${RELAY_PORT}" --hornet "${HORNET}" --ledger "${LEDGER}" \
  >"${TMP}/relay.log" 2>&1 &
PIDS+=("$!")

wait_for "${RELAY}/health" "anchor relay"

python3 -m http.server "${FIELD_PORT}" --bind 127.0.0.1 \
  --directory "${ROOT}/apps/field" >"${TMP}/field.log" 2>&1 &
PIDS+=("$!")

wait_for "http://127.0.0.1:${FIELD_PORT}/index.html" "field client"

cat <<EOF

Vickrey field loop is up.

  field client   http://127.0.0.1:${FIELD_PORT}/index.html?ledger=${RELAY}&commons=${LEDGER}
  anchor relay   ${RELAY}          (stand-in for the Messages API)
  ledger         ${LEDGER}/docs    (CORS: * )
  mock Hornet    ${HORNET}

Open the field client URL above: it already points at the relay for anchoring
and at the ledger for the commons. Ask for a suggestion (a labelled sample
works with no model running), confirm or correct it to seal, edit the queued
copy and watch sync refuse it, put the sealed copy back, then sync.

With MONGODB_URI unset the "Similar sightings" panel reports that no
observation store is configured; export it to exercise Atlas Vector Search.

Ctrl-C stops everything. Logs: ${TMP}
EOF

wait
