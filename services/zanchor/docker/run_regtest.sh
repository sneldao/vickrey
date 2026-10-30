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

# Never delete existing state: a running container or an orphaned volume
# holds the wallet the anchors were funded from. Preserve, do not recreate.
# These guards run before any credential or config file is created.
if docker ps -a --format '{{.Names}}' | grep -qx vickrey-zcashd-regtest; then
  echo "Existing regtest container preserved"
  exit 0
fi
if docker volume inspect vickrey-regtest-data >/dev/null 2>&1; then
  echo "Existing regtest volume found; use the recovery runbook to attach it. Nothing was deleted." >&2
  exit 1
fi
docker volume create vickrey-regtest-data >/dev/null

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
# zcashd 6.x refuses to start without a conf file present (it may be
# empty); the real options ride on the command line below.
docker run --rm -v vickrey-regtest-data:/mnt -v "$WORK":/w ubuntu:24.04 \
  sh -c "cp /w/regtest.conf /mnt/zcash.conf && chmod 600 /mnt/zcash.conf"
docker run -d --name vickrey-zcashd-regtest \
  -p 127.0.0.1:28432:28432 \
  -v vickrey-regtest-data:/data \
  "$IMAGE" -datadir=/data -confdir=/data -regtest -rpcbind=0.0.0.0 -rpcallowip=0.0.0.0/0 \
  -rpcuser=zanchor -rpcpassword="$PASS" -rpcport=28432 \
  -allowdeprecated=getnewaddress \
  -nuparams=5437f330:10 \
  -i-am-aware-zcashd-will-be-replaced-by-zebrad-and-zallet-in-2025=1

echo "waiting for rpc..."
for i in $(seq 1 60); do
  if curl -s -u "zanchor:$PASS" -X POST -H 'Content-Type: application/json' \
      --data '{"jsonrpc":"1.0","id":1,"method":"getblockcount","params":[]}' \
      http://127.0.0.1:28432/ | grep -q result; then
    echo "regtest rpc is up at 127.0.0.1:28432 (credentials stay in the node configuration)"
    exit 0
  fi
  sleep 2
done
echo "zcashd did not come up" >&2
docker logs --tail 30 vickrey-zcashd-regtest >&2
exit 1
