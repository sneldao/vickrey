#!/usr/bin/env bash
# Local/dev regtest zcashd from the v6.20.0 image. No funding needed:
# regtest mints. Reports the RPC endpoint without printing its credentials.
#
#   ./run_regtest.sh          # uses vickrey-zcashd:v6.20.0
#
# The RPC is bound to 127.0.0.1 on the host; do not publish the port
# anywhere the demo is not watching.
set -euo pipefail
cd "$(dirname "$0")"

IMAGE="${IMAGE:-vickrey-zcashd:v6.20.0}"
NAME="vickrey-zcashd-regtest"
VOLUME="vickrey-regtest-data"
RPC_PORT=28432

# Never delete existing state: a running container or an orphaned volume
# holds the wallet the anchors were funded from. Preserve, do not recreate.
# These guards run before any credential or config file is created.
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "Existing regtest container preserved"
  exit 0
fi
if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo "Existing regtest volume found; use the recovery runbook to attach it. Nothing was deleted." >&2
  exit 1
fi
docker volume create "$VOLUME" >/dev/null

umask 077
PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cat > "$WORK/regtest.conf" <<EOF
regtest=1
rpcbind=0.0.0.0
rpcallowip=0.0.0.0/0
rpcuser=zanchor
rpcpassword=$PASS
rpcport=28432
i-am-aware-zcashd-will-be-replaced-by-zebrad-and-zallet-in-2025=1
EOF
# zcashd 6.x requires a conf file; credentials and network options stay in it.
docker run --rm -v "$VOLUME":/mnt -v "$WORK":/w ubuntu:24.04 \
  sh -c "cp /w/regtest.conf /mnt/zcash.conf && chmod 600 /mnt/zcash.conf"
docker run -d --name "$NAME" \
  -p "127.0.0.1:$RPC_PORT:28432" \
  -v "$VOLUME":/data \
  "$IMAGE" -datadir=/data -confdir=/data \
  -allowdeprecated=getnewaddress \
  -nuparams=5437f330:10

echo "waiting for rpc..."
for i in $(seq 1 60); do
  if curl -s -u "zanchor:$PASS" -X POST -H 'Content-Type: application/json' \
      --data '{"jsonrpc":"2.0","id":1,"method":"getblockcount","params":[]}' \
      "http://127.0.0.1:$RPC_PORT/" | grep -q result; then
    echo "regtest rpc is up at 127.0.0.1:$RPC_PORT (credentials stay in the node configuration)"
    exit 0
  fi
  sleep 2
done
echo "zcashd did not come up" >&2
docker logs --tail 30 "$NAME" >&2
exit 1
