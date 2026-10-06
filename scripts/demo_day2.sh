#!/usr/bin/env bash
# Day 2 verify + tamper demo.
#
# Starts a mock Hornet and the evidence ledger, ingests one application
# event, shows VERIFIED, then overwrites only the stored application
# payload. The Hornet block stays original, so reverify reports
# PAYLOAD_MISMATCH and content_match=false.
#
# A live Day 1 node replaces the mock: run the ledger with HORNET_URL
# pointed at it and POST /ingest yourself (or apply the Messages API patch).
# The curls below are the same either way.
#
# Usage: ./scripts/demo_day2.sh

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VENV="$ROOT/services/ledger/.venv"
TMP=$(mktemp -d)
LEDGER_PID=""
HORNET_PID=""

cleanup() {
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

if [[ ! -x "${VENV}/bin/uvicorn" ]]; then
  python3 -m venv "${VENV}"
  "${VENV}/bin/pip" install -r "${ROOT}/services/ledger/requirements.txt"
fi

HORNET_PORT=$(free_port)
LEDGER_PORT=$(free_port)
HORNET="http://127.0.0.1:${HORNET_PORT}"
LEDGER="http://127.0.0.1:${LEDGER_PORT}"
BLOCK_ID="0xda720001"
TAG="veles.evidence.temperature"
MESSAGE='{"flow_id":"flow-demo-1","sensor":"edge-box-a","temperature":21.5,"unit":"C"}'

python3 "${ROOT}/scripts/mock_hornet.py" --port "${HORNET_PORT}" >"${TMP}/hornet.log" 2>&1 &
HORNET_PID=$!

DATABASE_PATH="${TMP}/ledger.db" \
  HORNET_URL="${HORNET}" \
  "${VENV}/bin/uvicorn" app.main:app \
  --app-dir "${ROOT}/services/ledger" \
  --host 127.0.0.1 \
  --port "${LEDGER_PORT}" \
  >"${TMP}/ledger.log" 2>&1 &
LEDGER_PID=$!

ready=0
for _ in $(seq 1 50); do
  if curl -sf "${LEDGER}/health" >/dev/null; then
    ready=1
    break
  fi
  sleep 0.2
done
if [[ "${ready}" -ne 1 ]]; then
  fail "ledger did not become healthy"
fi

echo "1. Register the block on Hornet (mock stand-in for a Messages API upload)"
echo "   curl -sS -X POST ${HORNET}/_control -H 'content-type: application/json' -d '{blockId, tag, message}'"
curl -sS -X POST "${HORNET}/_control" \
  -H 'content-type: application/json' \
  -d "{\"blockId\":\"${BLOCK_ID}\",\"tag\":\"${TAG}\",\"message\":${MESSAGE},\"isSolid\":true,\"referencedByMilestoneIndex\":12}" \
  -o "${TMP}/register.json"
echo "   $(cat "${TMP}/register.json")"

echo "2. Ingest the application copy. The ledger GETs the block and metadata on its own."
echo "   curl -sS -X POST ${LEDGER}/ingest -H 'content-type: application/json' -d '{blockId, tag, message, hornetStatus}'"
curl -sS -X POST "${LEDGER}/ingest" \
  -H 'content-type: application/json' \
  -d "{\"blockId\":\"${BLOCK_ID}\",\"tag\":\"${TAG}\",\"message\":${MESSAGE},\"hornetStatus\":201}" \
  -o "${TMP}/ingest.json"
python3 - "${TMP}/ingest.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
print(json.dumps({k: doc[k] for k in ("block_id", "status", "solid", "content_match", "milestone_index", "flow_id")}, indent=2))
if doc["status"] != "VERIFIED" or doc["content_match"] is not True or doc["solid"] is not True:
    raise SystemExit(f"expected VERIFIED, got {doc['status']} ({doc.get('detail')})")
if doc["payload_json"]["temperature"] != 21.5 or doc["ledger_payload_json"]["temperature"] != 21.5:
    raise SystemExit("temperatures diverged before tamper")
PY

echo "3. Re-read Hornet without changing the application copy."
echo "   curl -sS -X POST ${LEDGER}/messages/${BLOCK_ID}/reverify"
curl -sS -X POST "${LEDGER}/messages/${BLOCK_ID}/reverify" -o "${TMP}/reverify.json"
python3 - "${TMP}/reverify.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
print(doc["status"], "content_match="+str(doc["content_match"]).lower())
if doc["status"] != "VERIFIED":
    raise SystemExit("reverify changed a matching row")
PY

echo "4. Query by flow and status."
echo "   curl -sS '${LEDGER}/messages?flowId=flow-demo-1&status=VERIFIED'"
curl -sS "${LEDGER}/messages?flowId=flow-demo-1&status=VERIFIED" -o "${TMP}/list.json"
python3 - "${TMP}/list.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
print(f"total={doc['total']}")
if doc["total"] != 1:
    raise SystemExit("filter missed the verified row")
PY

echo "5. DEMO tamper: overwrite the application temperature. Hornet is not written."
echo "   curl -sS -X POST ${LEDGER}/messages/${BLOCK_ID}/tamper -H 'content-type: application/json' -d '{\"temperature\":999.9}'"
curl -sS -X POST "${LEDGER}/messages/${BLOCK_ID}/tamper" \
  -H 'content-type: application/json' \
  -d '{"temperature":999.9}' \
  -o "${TMP}/tamper.json"
python3 - "${TMP}/tamper.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
msg = doc["message"]
print(json.dumps({
    "status": msg["status"],
    "content_match": msg["content_match"],
    "solid": msg["solid"],
    "app_temperature": msg["payload_json"]["temperature"],
    "ledger_temperature": msg["ledger_payload_json"]["temperature"],
}, indent=2))
if not doc["demo_only"]:
    raise SystemExit("tamper response missing demo_only")
if msg["status"] != "PAYLOAD_MISMATCH" or msg["content_match"] is not False:
    raise SystemExit(f"expected PAYLOAD_MISMATCH, got {msg['status']} ({msg.get('detail')})")
if msg["solid"] is not True or msg["milestone_index"] != 12:
    raise SystemExit("solidity flags changed during tamper")
if msg["payload_json"]["temperature"] != 999.9:
    raise SystemExit("application copy was not mutated")
if msg["ledger_payload_json"]["temperature"] != 21.5:
    raise SystemExit("ledger payload changed; tamper must not touch Hornet")
if doc["previous_payload_json"]["temperature"] != 21.5:
    raise SystemExit("previous application payload was not returned")
PY

echo "6. The mismatch survives a fresh Hornet read."
echo "   curl -sS -X POST ${LEDGER}/messages/${BLOCK_ID}/reverify"
curl -sS -X POST "${LEDGER}/messages/${BLOCK_ID}/reverify" -o "${TMP}/reverify2.json"
python3 - "${TMP}/reverify2.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
print(doc["status"], "content_match="+str(doc["content_match"]).lower())
if doc["status"] != "PAYLOAD_MISMATCH" or doc["content_match"] is not False:
    raise SystemExit("reverify cleared the mismatch")
if doc["ledger_payload_json"]["temperature"] != 21.5:
    raise SystemExit("ledger payload changed on reverify")
PY

echo
echo "Day 2 demo ok: VERIFIED, then tamper -> PAYLOAD_MISMATCH with the original ledger payload."
echo "Ledger was ${LEDGER} (stopped on exit). Hornet mock was ${HORNET}."
