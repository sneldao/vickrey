#!/usr/bin/env bash
# Local/dev regtest zcashd from the v6.20.0 image. No funding needed:
# regtest mints. Prints the RPC URL for spike.py / run_local.sh.
#
#   ./run_regtest.sh          # uses vickrey-zcashd:v6.20.0
#
# The RPC is bound to 127.0.0.1 on the host; do not publish the port
# anywhere the demo is not watching.
set -euo pipefail
cd "$(dirname "$0")"

IMAGE="${IMAGE:-vickrey-zcashd:v6.20.0}"
PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
WORK="$(mktemp -d)"
cat > "$WORK/regtest.conf" <<EOF
regtest=1
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
rpcuser=zanchor
rpcpassword=$PASS
rpcport=28432
EOF

docker rm -f vickrey-zcashd-regtest 2>/dev/null || true
docker volume rm vickrey-regtest-data 2>/dev/null || true
docker volume create vickrey-regtest-data >/dev/null
docker run -d --name vickrey-zcashd-regtest \
  -p 127.0.0.1:28432:28432 \
  -v vickrey-regtest-data:/data \
  "$IMAGE" -datadir=/data -confdir=/data -regtest -rpcbind=127.0.0.1 -rpcallowip=127.0.0.1 \
  -rpcuser=zanchor -rpcpassword="$PASS" -rpcport=28432

echo "waiting for rpc..."
for i in $(seq 1 60); do
  if curl -s -u "zanchor:$PASS" -X POST -H 'Content-Type: application/json' \
      --data '{"jsonrpc":"1.0","id":1,"method":"getblockcount","params":[]}' \
      http://127.0.0.1:28432/ | grep -q result; then
    echo "RPC_URL=http://zanchor:$PASS@127.0.0.1:28432"
    echo "conf kept at: $WORK/regtest.conf"
    exit 0
  fi
  sleep 2
done
echo "zcashd did not come up" >&2
docker logs --tail 30 vickrey-zcashd-regtest >&2
exit 1
