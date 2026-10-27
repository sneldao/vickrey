#!/usr/bin/env python3
"""7.x probe: which RPC reports the spent note's identity (nullifier) for an anchor?

Run on the box, against the same regtest node as probe6.py. This probe does
NOT assert a field name. It sends one anchor, then dumps the candidate RPCs'
output and reports where a nullifier-shaped value (64 hex chars) appears, so
the implementation is written against what the node actually returns.

Usage: python3 probe7.py <rpc-password>
"""

import base64
import json
import re
import sys
import time
import urllib.request

if len(sys.argv) < 2:
    sys.exit("usage: probe7.py <rpc-password>")
PASS = sys.argv[1]
URL = "http://127.0.0.1:28432/"
HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")
n = [0]


def call(method, params=None):
    n[0] += 1
    body = json.dumps(
        {"jsonrpc": "1.0", "id": n[0], "method": method, "params": params or []}
    ).encode()
    req = urllib.request.Request(URL, data=body, method="POST")
    token = base64.b64encode(f"zanchor:{PASS}".encode()).decode()
    req.add_header("Authorization", "Basic " + token)
    req.add_header("Content-Type", "application/json")
    try:
        out = json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        out = json.load(e)
    if out.get("error"):
        raise RuntimeError(f"{method}: {out['error']}")
    return out["result"]


def wait_op(opid, mine=None):
    for i in range(120):
        st = call("z_getoperationstatus", [[opid]])[0]
        if st["status"] == "success":
            return st.get("result")
        if st["status"] in ("failed", "error"):
            raise RuntimeError(st)
        if mine and i % 5 == 4:
            mine()  # regtest: nobody mines for us
        time.sleep(2)
    raise TimeoutError(opid)


def find_hex(label, obj):
    hits = sorted(set(HEX64.findall(json.dumps(obj))))
    print(f"  {label}: {len(hits)} 64-hex value(s)")
    for h in hits[:5]:
        print("     ", h)
    return hits


u0 = call("z_getaddressforaccount", [0])["address"]
u1 = call("z_getaddressforaccount", [1])["address"]
print("anchor balance before:", call("z_getbalanceforaccount", [0, 5]))

C = "cd" * 32
opid = call(
    "z_sendmany",
    [u0, [{"address": u1, "amount": "0.0005", "memo": "00" + C}], 10, "0.0001"],
)
res = wait_op(opid, mine=lambda: call("generate", [1]))
txid = res["txid"] if isinstance(res, dict) else res
call("generate", [1])
print("anchor txid:", txid)

print("\n=== candidate RPCs (look for a nullifier-shaped value) ===")

view = call("z_viewtransaction", [txid])
print("z_viewtransaction keys:", sorted(view.keys()))
print("z_viewtransaction spends:", json.dumps(view.get("spends", []), indent=1)[:800])
find_hex("z_viewtransaction", view)

find_hex("gettransaction", call("gettransaction", [txid]))

raw = call("getrawtransaction", [txid, 1])
find_hex("getrawtransaction (verbose)", raw)
orchard = raw.get("orchard") or {}
print("getrawtransaction.orchard keys:", sorted(orchard.keys()))
actions = orchard.get("actions") or []
if actions:
    print("first orchard action keys:", sorted(actions[0].keys()))
    print("first action has 'nullifier':", "nullifier" in actions[0])

for method, params in (
    ("z_listunspent", [0, 9999999, False]),
    ("z_listnotes", [0, 9999999]),
):
    try:
        find_hex(method, call(method, params))
    except RuntimeError as e:
        print(f"  {method}: not available here ({str(e)[:120]})")

print(
    "\nNEXT: if a nullifier appears under a stable field name in a verbose RPC, "
    "record that field name in docs/PRIVACY.md and implement against it. "
    "If none does, the spent-note binding must come from the wallet's own note "
    "record and this design needs revisiting before any code is written."
)
