#!/usr/bin/env bash
# One-shot zcashd testnet (test-4z) node in Docker — the demo chain.
#
# Why testnet and not mainnet: same code, same shielded pool, same fee rules,
# real verifiable transactions (explorer.zectest.co), and a chain that
# syncs in hours instead of days. The service and the spike are node-
# agnostic — only the RPC URL changes.
#
# Usage:  ./run_testnet.sh            # start (idempotent)
#         ./run_testnet.sh status     # RPC health
#         ./run_testnet.sh down       # stop (data kept)
set -euo pipefail

IMAGE="${ZANCHOR_ZCASHD_IMAGE:-vickrey-zcashd:v6.20.0}"
NAME="vickrey-zcashd-testnet"
VOLUME="vickrey-testnet-data"
RPC_PORT="${ZANCHOR_RPC_PORT:-28532}"

if [ "${1:-}" = "down" ]; then docker rm -f "$NAME" >/dev/null; echo "stopped ($NAME); volume $VOLUME kept"; exit 0; fi

if ! docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  PASS="$(openssl rand -hex 24)"
  umask 077
  WORK="$(mktemp -d)"
  trap 'rm -rf "$WORK"' EXIT
  cat > "$WORK/testnet.conf" <<EOF
testnet=1
rpcbind=0.0.0.0
rpcallowip=0.0.0.0/0
rpcuser=zanchor
rpcpassword=$PASS
rpcport=28532
allowdeprecated=getnewaddress
i-am-aware-zcashd-will-be-replaced-by-zebrad-and-zallet-in-2025=1
EOF

  docker volume inspect "$VOLUME" >/dev/null 2>&1 || docker volume create "$VOLUME" >/dev/null
  docker run --rm -v "$VOLUME":/mnt -v "$WORK":/w ubuntu:24.04 \
    sh -c "cp /w/testnet.conf /mnt/zcash.conf && chmod 600 /mnt/zcash.conf"
  docker run -d --name "$NAME" \
    -p "127.0.0.1:$RPC_PORT:28532" \
    -v "$VOLUME":/data \
    "$IMAGE" -datadir=/data -confdir=/data
fi

PASS="$(docker run --rm --entrypoint awk -v "$VOLUME":/data:ro "$IMAGE" \
  -F= '$1 == "rpcpassword" { print $2; exit }' /data/zcash.conf)"
if [ -z "$PASS" ]; then
  echo "node configuration has no rpcpassword; use the recovery runbook" >&2
  exit 1
fi
if [ "${1:-}" = "status" ]; then
  curl -s -m 5 -u "zanchor:$PASS" -X POST -H 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","id":1,"method":"getblockcount","params":[]}' "http://127.0.0.1:$RPC_PORT/"
  exit 0
fi

echo "testnet node running as $NAME; RPC 127.0.0.1:$RPC_PORT user=zanchor"
echo "credentials stay in the node configuration, not Docker command metadata"
