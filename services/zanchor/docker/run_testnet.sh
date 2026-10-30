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

PASS="$(docker inspect "$NAME" --format '{{join .Config.Cmd " "}}' 2>/dev/null | grep -o 'rpcpassword=[^ ]*' | cut -d= -f2 || true)"
if [ "${1:-}" = "status" ]; then
  [ -n "$PASS" ] || { echo "not running"; exit 1; }
  curl -s -m 5 -u "zanchor:$PASS" -X POST -H 'Content-Type: application/json' \
    --data '{"jsonrpc":"1.0","id":1,"method":"getblockcount"}' "http://127.0.0.1:$RPC_PORT/"
  exit 0
fi

[ -n "$PASS" ] && { echo "already running: $NAME (RPC 127.0.0.1:$RPC_PORT)"; exit 0; }
PASS="$(openssl rand -hex 24)"

umask 077
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cat > "$WORK/testnet.conf" <<'EOF'
# zcashd 6.x requires a conf file to exist; options ride on the command line.
EOF

docker volume inspect "$VOLUME" >/dev/null 2>&1 || docker volume create "$VOLUME" >/dev/null
docker run --rm -v "$VOLUME":/mnt -v "$WORK":/w ubuntu:24.04 \
  sh -c "cp /w/testnet.conf /mnt/zcash.conf && chmod 600 /mnt/zcash.conf"
docker run -d --name "$NAME" \
  -p 127.0.0.1:$RPC_PORT:28532 \
  -v "$VOLUME":/data \
  "$IMAGE" -datadir=/data -confdir=/data -testnet -rpcbind=0.0.0.0 -rpcallowip=0.0.0.0/0 \
  -rpcuser=zanchor -rpcpassword="$PASS" -rpcport=28532 \
  -allowdeprecated=getnewaddress \
  -i-am-aware-zcashd-will-be-replaced-by-zebrad-and-zallet-in-2025=1

echo "testnet node running as $NAME; RPC 127.0.0.1:$RPC_PORT user=zanchor"
echo "credentials stay in the node configuration"
