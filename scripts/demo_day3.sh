#!/usr/bin/env bash
# Day 3 explorer demo.
#
# Starts a mock Hornet, the evidence ledger, and the static explorer.
# Seeds one VERIFIED incident.critical alarm (the pitch block) plus a few
# neighboring states so the filters and flow groups have something to show.
# Leave this running, open the printed URL, and use "Tamper application copy".
# The Hornet block stays original. Ctrl-C stops the three processes.
#
# Usage: ./scripts/demo_day3.sh
# Ports: LEDGER_PORT (8088), EXPLORER_PORT (8090). HORNET_PORT is chosen free.

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VENV="$ROOT/services/ledger/.venv"
TMP=$(mktemp -d)
LEDGER_PID=""
HORNET_PID=""
EXPLORER_PID=""
LEDGER_PORT="${LEDGER_PORT:-8088}"
EXPLORER_PORT="${EXPLORER_PORT:-8090}"

cleanup() {
  if [[ -n "${EXPLORER_PID}" ]]; then
    kill "${EXPLORER_PID}" 2>/dev/null || true
  fi
  if [[ -n "${LEDGER_PID}" ]]; then
    kill "${LEDGER_PID}" 2>/dev/null || true
  fi
  if [[ -n "${HORNET_PID}" ]]; then
    kill "${HORNET_PID}" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
  rm -rf "${TMP}"
}
trap cleanup EXIT

fail() {
  echo "demo failed: $*" >&2
  echo "----- ledger log -----" >&2
  cat "${TMP}/ledger.log" >&2 || true
  echo "----- hornet log -----" >&2
  cat "${TMP}/hornet.log" >&2 || true
  echo "----- explorer log -----" >&2
  cat "${TMP}/explorer.log" >&2 || true
  exit 1
}

free_port() {
  python3 - <<'PY'
import socket
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
}

port_free() {
  python3 - "$1" <<'PY'
import socket, sys
sock = socket.socket()
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
}

if [[ ! -x "${VENV}/bin/uvicorn" ]]; then
  python3 -m venv "${VENV}"
  "${VENV}/bin/pip" install -r "${ROOT}/services/ledger/requirements.txt"
fi

if ! port_free "${LEDGER_PORT}"; then
  fail "port ${LEDGER_PORT} is in use. Stop the other ledger or set LEDGER_PORT."
fi
if ! port_free "${EXPLORER_PORT}"; then
  fail "port ${EXPLORER_PORT} is in use. Stop the other server or set EXPLORER_PORT."
fi

HORNET_PORT=$(free_port)
HORNET="http://127.0.0.1:${HORNET_PORT}"
LEDGER="http://127.0.0.1:${LEDGER_PORT}"
EXPLORER="http://127.0.0.1:${EXPLORER_PORT}"
KILLER="0xda720001"

python3 "${ROOT}/scripts/mock_hornet.py" --port "${HORNET_PORT}" >"${TMP}/hornet.log" 2>&1 &
HORNET_PID=$!

DATABASE_PATH="${TMP}/ledger.db" \
  HORNET_URL="${HORNET}" \
  LEDGER_CORS_ORIGINS="*" \
  "${VENV}/bin/uvicorn" app.main:app \
  --app-dir "${ROOT}/services/ledger" \
  --host 127.0.0.1 \
  --port "${LEDGER_PORT}" \
  >"${TMP}/ledger.log" 2>&1 &
LEDGER_PID=$!

python3 -m http.server "${EXPLORER_PORT}" --bind 127.0.0.1 --directory "${ROOT}/apps/explorer" \
  >"${TMP}/explorer.log" 2>&1 &
EXPLORER_PID=$!

ready=0
for _ in $(seq 1 50); do
  if curl -sf "${LEDGER}/health" >/dev/null && curl -sf "${EXPLORER}/" >/dev/null; then
    ready=1
    break
  fi
  sleep 0.2
done
if [[ "${ready}" -ne 1 ]]; then
  fail "ledger or explorer did not become ready"
fi

python3 - "${HORNET}" "${LEDGER}" "${KILLER}" <<'PY'
import json, sys, urllib.request

hornet, ledger, killer = sys.argv[1:]

def post(url, body):
    data = json.dumps(body).encode()
    request = urllib.request.Request(
        url, data=data, headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)

def incident(block_id, tag, message, *, solid=True, milestone=40, register=True):
    if register:
        control = {
            "blockId": block_id,
            "tag": tag,
            "message": message,
            "isSolid": solid,
        }
        if milestone is not None:
            control["referencedByMilestoneIndex"] = milestone
        else:
            control["referencedByMilestoneIndex"] = None
        post(hornet + "/_control", control)
    stored_tag = message.pop("_stored_tag", tag)
    hornet_tag = message.pop("_hornet_tag", None)
    if hornet_tag is not None:
        # Re-register so the block tag differs from the application tag.
        post(hornet + "/_control", {
            "blockId": block_id,
            "tag": hornet_tag,
            "message": message,
            "isSolid": solid,
            "referencedByMilestoneIndex": milestone,
        })
    return post(ledger + "/ingest", {
        "blockId": block_id,
        "tag": stored_tag,
        "message": message,
        "hornetStatus": 201,
    })

watch = incident(
    "0xda720010",
    "incident.watch",
    {"flowId": "line-7", "kind": "status", "sensorId": "temp-12", "detail": "steady", "temperature": 20.1},
    milestone=41,
)
alarm = incident(
    killer,
    "incident.critical",
    {"flowId": "line-7", "kind": "alarm", "sensorId": "temp-12", "detail": "threshold exceeded", "temperature": 21.5},
    milestone=42,
)
plant = incident(
    "0xda720004",
    "plant.reading",
    {"flowId": "line-2", "kind": "reading", "sensorId": "ph-1", "detail": "steady", "temperature": 18.0},
    milestone=41,
)
pending = incident(
    "0xda720003",
    "incident.pending",
    {"flowId": "line-3", "kind": "alarm", "detail": "awaiting block"},
    register=False,
)
late = incident(
    "0xda720002",
    "incident.late",
    {"flowId": "line-4", "kind": "status", "sensorId": "temp-12", "detail": "not solid yet", "temperature": 19.0},
    solid=False,
    milestone=None,
)
mismatch = {
    "flowId": "line-9",
    "kind": "status",
    "detail": "tag rewritten in the application row",
    "temperature": 22.0,
    "_stored_tag": "incident.demo",
    "_hornet_tag": "shift.note",
}
tag_miss = incident("0xda720009", "shift.note", mismatch, milestone=43)

expected = {
    watch["block_id"]: "VERIFIED",
    alarm["block_id"]: "VERIFIED",
    plant["block_id"]: "VERIFIED",
    pending["block_id"]: "PENDING",
    late["block_id"]: "NOT_SOLID",
    tag_miss["block_id"]: "PAYLOAD_MISMATCH",
}
print("seeded:")
for row in (watch, alarm, plant, pending, late, tag_miss):
    print(f"  {row['block_id']}  {row['status']}")
    if expected[row["block_id"]] != row["status"]:
        raise SystemExit(
            f"{row['block_id']} expected {expected[row['block_id']]}, "
            f"got {row['status']} ({row.get('detail')})"
        )
if alarm["payload_json"]["temperature"] != 21.5 or alarm["ledger_payload_json"]["temperature"] != 21.5:
    raise SystemExit("killer temperatures diverged before tamper")
if tag_miss["ledger_tag"] != "shift.note" or tag_miss["content_match"] is not False:
    raise SystemExit("tag-only mismatch was not stored")
PY

echo
echo "Explorer  ${EXPLORER}/?hornet=${HORNET}#${KILLER}"
echo "Ledger    ${LEDGER}"
echo "Block     ${KILLER} is VERIFIED (incident.critical, flow line-7, kind alarm)."
echo
echo "In the explorer: Tamper application copy."
echo "The stamp becomes PAYLOAD MISMATCH. 999.9 sits beside the Hornet value 21.5."
echo "Open on Hornet dashboard uses the stock INX route /explorer/block/<id>."
echo "Hornet block JSON in this stand-in opens the mock, not a live node."
echo
echo "Ctrl-C stops the mock Hornet, the ledger, and the explorer."

wait
