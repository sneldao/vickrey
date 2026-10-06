#!/usr/bin/env bash
# Panic button: restore the seeded demo state on the live Vultr ledger.
#
# If someone hits /tamper or /ingest before the pitch, this puts the three
# demo rows back:
#
#   0x6d90d792…5313f5  VERIFIED          incident.critical  temp 82.0 (the live-tamper row)
#   0x39c16427…2afe49  VERIFIED          incident.demo      temp 21.5
#   0x7b8062f1…3ecb657 PAYLOAD_MISMATCH  incident.critical  app temp 92.0 vs Hornet 82.0
#
# Re-ingesting the original application copy makes the row VERIFIED again
# (verify re-reads the real Hornet block). The mismatch row is restored by
# ingesting the Hornet copy and then re-applying the same tamper.
#
# Usage: ./scripts/restore_demo.sh [LEDGER_URL]
#   LEDGER_URL defaults to http://45.76.242.245:8088

set -euo pipefail

LEDGER="${1:-http://45.76.242.245:8088}"

post() {
  curl -sS --fail -m 10 -X POST "$1" \
    -H 'content-type: application/json' -d "$2"
}

ingest() { # block_id tag message
  post "${LEDGER}/ingest" \
    "{\"blockId\":\"$1\",\"tag\":\"$2\",\"message\":$3,\"hornetStatus\":201}" \
    | python3 -c 'import json,sys; m=json.load(sys.stdin); print(m["block_id"][:14], "->", m["status"])'
}

echo "restoring ${LEDGER} ..."

# Row 1: the pitch alarm. Live demo tampers this one.
ingest 0x6d90d792c95bf69f280462931b74231dcfc1be1410e16d6faa5faf2aff5313f5 \
  incident.critical \
  '{"flowId":"line-7","kind":"alarm","sensorId":"temp-12","temperature":82.0,"detail":"threshold exceeded"}'

# Row 2: baseline VERIFIED reading.
ingest 0x39c1642748aae82d3163c361799c3e728edb9f467c81912c2623e769772afe49 \
  incident.demo \
  '{"flowId":"line-7","kind":"ok","temperature":21.5,"detail":"baseline"}'

# Row 3: the standing mismatch exhibit. Restore Hornet copy, then re-tamper.
ingest 0x7b8062f1d6530340f5cc47eeb3f86da5f3e569e635445d8d7585e20376ecb657 \
  incident.critical \
  '{"flowId":"line-7","kind":"alarm","sensorId":"temp-12","temperature":82.0,"detail":"threshold exceeded"}'

post "${LEDGER}/messages/0x7b8062f1d6530340f5cc47eeb3f86da5f3e569e635445d8d7585e20376ecb657/tamper" \
  '{"temperature":92.0}' \
  | python3 -c 'import json,sys; m=json.load(sys.stdin)["message"]; print(m["block_id"][:14], "->", m["status"])'

echo
echo "final state:"
curl -sS -m 10 "${LEDGER}/messages?limit=50" \
  | python3 -c 'import json,sys; [print(" ", m["status"], m["block_id"][:18], m["flow_id"], m["tag"]) for m in json.load(sys.stdin)["messages"]]'
