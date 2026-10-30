#!/usr/bin/env bash
# Shielded-anchor walk: one command, one anchor, one receipt, one explorer link.
#
#   ./scripts/demo_zcash.sh                  # mock zanchor + local explorer
#   ./scripts/demo_zcash.sh --zanchor URL    # the same walk against a real one
#   ./scripts/demo_zcash.sh --transparent    # the fallback: TRANSPARENT, not SHIELDED
#
# It does not just drive the service — it checks it against
# docs/ZANCHOR_API.md and exits non-zero on a breach. That is deliberate: the
# same script that shows the demo is the acceptance test for services/zanchor,
# so there is one definition of "the contract works" and it is executable.
#
# What it proves, in order: the service is up and says what it is; a commitment
# is accepted and a receipt comes back carrying mode + shielded; a replay is
# rejected with 409; a malformed body is rejected with 400; the receipt settles
# and proofs of existence resolve; the public endpoints reveal nothing about an
# observation; there is no way to list receipts.
#
# It never touches a real chain in mock mode, and it says so on every line that
# could be mistaken for one.

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
ZANCHOR="${ZANCHOR_URL:-}"
EXPLORER="${EXPLORER_URL:-}"
KEEP=0
MOCK=0
MOCK_ARGS=()
TMP=$(mktemp -d)
PIDS=()

cleanup() {
  if [[ "${KEEP}" == "1" ]]; then
    echo "kept running; logs in ${TMP}" >&2
    return
  fi
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
  for _ in $(seq 1 100); do
    if curl -sf "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  echo "${name} did not answer at ${url}" >&2
  for log in "${TMP}"/*.log; do
    echo "----- ${log} -----" >&2
    cat "${log}" >&2 || true
  done
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --zanchor)
      ZANCHOR="${2:?--zanchor needs a URL}"
      shift 2
      ;;
    --explorer)
      EXPLORER="${2:?--explorer needs a URL}"
      shift 2
      ;;
    --transparent)
      MOCK_ARGS+=(--transparent)
      shift
      ;;
    --mode)
      MOCK_ARGS+=(--mode "${2:?--mode needs A or B}")
      shift 2
      ;;
    --keep)
      KEEP=1
      shift
      ;;
    -h | --help)
      sed -n '2,13p' "$0"
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -n "${ZANCHOR}" && ${#MOCK_ARGS[@]} -gt 0 ]]; then
  echo "--mode/--transparent configure the mock; they mean nothing with --zanchor" >&2
  exit 2
fi

if [[ -z "${ZANCHOR}" ]]; then
  MOCK=1
  PORT=$(free_port)
  ZANCHOR="http://127.0.0.1:${PORT}"
  python3 "${ROOT}/scripts/mock_zanchor.py" --port "${PORT}" \
    ${MOCK_ARGS[@]+"${MOCK_ARGS[@]}"} >"${TMP}/zanchor.log" 2>&1 &
  PIDS+=("$!")
  wait_for "${ZANCHOR}/health" "mock zanchor"
  echo "MOCK ZANCHOR — no chain, no shielded pool, no transaction." >&2
  echo "The receipt below is a hash and a counter, not a Zcash tx." >&2
  echo >&2
fi

if [[ -z "${EXPLORER}" ]]; then
  PORT=$(free_port)
  EXPLORER="http://127.0.0.1:${PORT}/explorer"
  # Serve the apps root so the explorer's ../field/*.js imports resolve.
  python3 -m http.server "${PORT}" --bind 127.0.0.1 \
    --directory "${ROOT}/apps" >"${TMP}/explorer.log" 2>&1 &
  PIDS+=("$!")
  wait_for "${EXPLORER}/index.html" "explorer"
fi

OUT="${TMP}/walk.json"
ZANCHOR_URL="${ZANCHOR}" ZANCHOR_TIMEOUT="${ZANCHOR_TIMEOUT:-240}" \
  DEMO_OUT="${OUT}" python3 - <<'PY'
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ["ZANCHOR_URL"].rstrip("/")
TIMEOUT = float(os.environ.get("ZANCHOR_TIMEOUT", "240"))
OUT = os.environ["DEMO_OUT"]
LEAK_WORDS = (
    "species",
    "location",
    "lat",
    "lon",
    "observer",
    "summary",
    "observed_at",
    "payload",
)
failures = []
warnings = []


def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, (json.loads(raw) if raw else {})
        except json.JSONDecodeError:
            return exc.code, {"detail": raw}
    except urllib.error.URLError as exc:
        print(f"FAIL  cannot reach {BASE}: {exc}", file=sys.stderr)
        sys.exit(1)


def check(ok, message):
    print(("  PASS  " if ok else "  FAIL  ") + message, flush=True)
    if not ok:
        failures.append(message)
    return ok


def warn(message):
    warnings.append(message)
    print("  WARN  " + message, flush=True)


print(f"zanchor  {BASE}")
print()

# 1. The service says what it is.
status, health = call("GET", "/health")
check(status == 200, "GET /health answers 200")
check(
    health.get("mode") in ("A", "B"),
    f"health.mode is A or B (got {health.get('mode')!r})",
)
check(
    isinstance(health.get("shielded"), bool),
    "health.shielded says whether the pipeline shields",
)
check(
    isinstance(health.get("notes_available"), int),
    "health.notes_available counts burnable notes",
)
print(
    f"  note  mode {health.get('mode')} · shielded {health.get('shielded')} · "
    f"notes {health.get('notes_available')}"
)
if health.get("notes_available") == 0:
    warn("no notes left: the next anchor is expected to answer 503")

# 2. One commitment in, one receipt out.
commitment = secrets.token_hex(32)
status, receipt = call("POST", "/anchor", {"commitment": commitment})
check(status == 202, f"POST /anchor answers 202 (got {status})")
for field in ("receipt_id", "commitment", "status", "txid", "height", "anchored_at"):
    check(field in receipt, f"receipt carries {field}")
check(receipt.get("commitment") == commitment, "receipt echoes the commitment")
check(
    receipt.get("status") in ("queued", "broadcast", "confirmed"),
    f"receipt.status is queued|broadcast|confirmed (got {receipt.get('status')!r})",
)
check(
    receipt.get("mode") in ("A", "B"),
    f"receipt.mode is A or B (got {receipt.get('mode')!r})",
)
check(
    isinstance(receipt.get("shielded"), bool),
    "receipt.shielded is a boolean, not an assumption",
)

receipt_id = receipt.get("receipt_id")
if not receipt_id:
    print("\nNo receipt id: the rest of the walk cannot run.", file=sys.stderr)
    sys.exit(1)

# 3. The contract's edges.
status, replay = call("POST", "/anchor", {"commitment": commitment})
check(status == 409, f"a replayed commitment is refused with 409 (got {status})")
check(bool(replay.get("detail")), "the 409 names the reason in detail")

status, bad = call("POST", "/anchor", {"commitment": "not-a-commitment"})
check(status == 400, f"a malformed commitment is refused with 400 (got {status})")

status, _ = call("GET", "/receipts/rec_does_not_exist")
check(status == 404, f"an unknown receipt is 404 (got {status})")

status, _ = call("GET", "/receipts")
check(
    status in (404, 405),
    f"there is no receipt list endpoint (got {status})",
)

# 4. Wait for the transaction, printing every state it passes through.
seen = []
deadline = time.time() + TIMEOUT
settled = None
while time.time() < deadline:
    status, current = call("GET", "/receipts/" + str(receipt_id))
    if status != 200:
        break
    if current.get("status") not in seen:
        seen.append(current.get("status"))
        print(f"  note  receipt is {current.get('status')}", flush=True)
    if current.get("status") == "confirmed":
        settled = current
        break
    time.sleep(1.0)

check(settled is not None, f"the receipt reaches confirmed within {int(TIMEOUT)}s")
settled = settled or {}

# 5. What anyone can check, and what it must not say.
txid = settled.get("txid")
height = settled.get("height")
if check(bool(txid), "the confirmed receipt has a txid"):
    status, chain = call("GET", "/chain/tx/" + str(txid))
    check(status == 200, f"GET /chain/tx/{{txid}} answers 200 (got {status})")
    check(chain.get("exists") is True, "the transaction exists on the node")
    check(
        chain.get("height") == height,
        f"the node and the receipt agree on the height ({height})",
    )
    check(
        isinstance(chain.get("confirmations"), int) and chain.get("confirmations") >= 1,
        "the check reports at least one confirmation",
    )
    wire = json.dumps(chain)
    check(
        commitment not in wire,
        "the public chain check does not echo the commitment",
    )
    for word in LEAK_WORDS:
        if word in wire:
            check(False, f"the public chain check leaked {word!r}")
            break
    else:
        check(True, "the public chain check says nothing about an observation")

    status, _ = call("GET", "/chain/tx/" + "0" * 64)
    check(status == 404, f"an unknown txid is 404 (got {status})")

wire = json.dumps(settled)
for word in LEAK_WORDS:
    if word in wire:
        check(False, f"the receipt leaked {word!r}")
        break
else:
    check(True, "the receipt carries the binding and no observation")

if settled.get("mode") != health.get("mode") or settled.get("shielded") != health.get(
    "shielded"
):
    warn("the receipt disagrees with /health about mode or shielding")
else:
    check(True, "receipt and /health agree about mode and shielding")

with open(OUT, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "receipt_id": receipt_id,
            "txid": settled.get("txid"),
            "height": settled.get("height"),
            "shielded": settled.get("shielded"),
            "mode": settled.get("mode"),
            "states": seen,
            "health": health,
        },
        handle,
    )

print()
if warnings:
    for message in warnings:
        print("WARN  " + message)
if failures:
    print(f"{len(failures)} contract failure(s):")
    for message in failures:
        print("  - " + message)
    sys.exit(1)
print("The wire contract holds. docs/ZANCHOR_API.md")
PY

link=$(python3 - "${OUT}" "${EXPLORER}" "${ZANCHOR}" <<'PY'
import json
import sys
from urllib.parse import quote

with open(sys.argv[1], encoding="utf-8") as handle:
    walk = json.load(handle)
url = (
    sys.argv[2].rstrip("/")
    + "/index.html?receipt="
    + quote(str(walk["receipt_id"]))
    + "&zanchor="
    + quote(sys.argv[3].rstrip("/"))
)
if walk.get("txid"):
    url += "#" + quote(str(walk["txid"]))
print(url)
PY
)

cat <<EOF

Open the receipt in the explorer:

  ${link}

The panel is the claim, so read it: the stamp says what the service reported
($(python3 -c "import json,sys;w=json.load(open(sys.argv[1]));print(('SHIELDED' if w['shielded'] else 'TRANSPARENT') + ' · mode ' + str(w['mode']))" "${OUT}")).
EOF

if [[ "${MOCK}" == "1" ]]; then
  cat <<EOF

This run used the mock: no Zcash node, no shielded pool, no transaction.
Run it against the real service when it exists, and the same checks apply:

  ./scripts/demo_zcash.sh --zanchor https://<zanchor-host>
EOF
fi
