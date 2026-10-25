#!/usr/bin/env bash
# Fund a (possibly fresh) regtest zcashd: accounts + two shielded notes
# in account 0, via z_shieldcoinbase on a matured coinbase address.
set -euo pipefail
RPASS=$(docker inspect vickrey-zcashd-regtest --format '{{join .Config.Cmd " "}}' | grep -o 'rpcpassword=[^ ]*' | cut -d= -f2)
for w in $(seq 1 90); do
  S=$(curl -s -m 5 -u "zanchor:$RPASS" -X POST -H 'Content-Type: application/json' --data '{"jsonrpc":"1.0","id":0,"method":"z_listaccounts"}' http://127.0.0.1:28432/ | head -c 60)
  case "$S" in *'"result"'*) break;; esac
  sleep 2
done
python3 - "$RPASS" <<'PY'
import base64
import json
import sys
import time
import urllib.error
import urllib.request

rpass = sys.argv[1]


def call(method, params=None):
    req = urllib.request.Request(
        "http://127.0.0.1:28432/",
        data=json.dumps(
            {"jsonrpc": "1.0", "id": 1, "method": method, "params": params or []}
        ).encode(),
        method="POST",
    )
    req.add_header(
        "Authorization", "Basic " + base64.b64encode(f"zanchor:{rpass}".encode()).decode()
    )
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.load(r)
    except urllib.error.HTTPError as exc:
        # The node answers transient busy states with bare HTTP 500s;
        # retry a few times before giving up.
        for _ in range(5):
            time.sleep(5)
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    out = json.load(r)
                break
            except urllib.error.HTTPError:
                continue
        else:
            raise
    if out.get("error"):
        raise RuntimeError(out["error"])
    return out["result"]


for _ in range(2):
    call("z_getnewaccount", [])
call("generate", [110])
h105 = call("getblockhash", [105])
t = call("getblock", [h105, 2])["tx"][0]["vout"][0]["scriptPubKey"]["addresses"][0]
u0 = call("z_getaddressforaccount", [0])["address"]
rec = call("z_listunifiedreceivers", [u0])["orchard"]
for i in range(2):
    opid = call("z_shieldcoinbase", [t, rec, "0.001", 1])["opid"]
    for j in range(90):
        st = call("z_getoperationstatus", [[opid]])[0]["status"]
        if st == "success":
            break
        if st == "failed":
            raise SystemExit(f"op {opid} failed")
        if j % 5 == 4:
            call("generate", [1])
        time.sleep(2)
call("generate", [5])
print("funded:", call("z_getnotescount"))
PY
