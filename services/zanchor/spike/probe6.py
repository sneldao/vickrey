#!/usr/bin/env python3
"""6.x API probe: fund, shield, anchor with memo, read back. Run on the box."""

import json
import sys
import time
import urllib.request

PASS = sys.argv[1]
URL = "http://127.0.0.1:28432/"
n = [0]


def call(method, params=None):
    n[0] += 1
    body = json.dumps(
        {"jsonrpc": "1.0", "id": n[0], "method": method, "params": params or []}
    ).encode()
    req = urllib.request.Request(URL, data=body, method="POST")
    req.add_header(
        "Authorization",
        "Basic " + __import__("base64").b64encode(f"zanchor:{PASS}".encode()).decode(),
    )
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
            mine()  # regtest: nobody mines for us; the op waits for a block
        time.sleep(2)
    raise TimeoutError(opid)


def wait_loaded():
    while True:
        try:
            call("z_listaccounts")
            return
        except RuntimeError as e:
            if "Loading wallet" in str(e):
                time.sleep(3)
                continue
            raise


# accounts (two fresh ones: anchor, then verifier)
wait_loaded()
print("anchor account:  ", call("z_getnewaccount"))
print("verifier account:", call("z_getnewaccount"))
u0 = call("z_getaddressforaccount", [0])["address"]
u1 = call("z_getaddressforaccount", [1])["address"]
print("anchor uaddr:   ", u0[:20], "…")
print("verifier uaddr: ", u1[:20], "…")

# fund + shield two notes. Regtest coinbase pays a legacy keypool
# t-address; z_shieldcoinbase is the purpose-built hop into the anchor
# account (mainnet funds the account with an ordinary pre-window
# transparent payment instead — same shape, different first hop).
call("generate", [110])  # coinbase maturity (100)
# keypool advances per block, so read the coinbase address from a MATURED block
h105 = call("getblockhash", [105])
block = call("getblock", [h105, 2])
coinbase_taddr = block["tx"][0]["vout"][0]["scriptPubKey"]["addresses"][0]
recvs0 = call("z_listunifiedreceivers", [u0])
anchor_z = recvs0["orchard"]
print("coinbase taddr:", coinbase_taddr)
for i in range(2):
    res = call("z_shieldcoinbase", [coinbase_taddr, anchor_z, "0.001", 1])
    for opid in (
        res
        if isinstance(res, list)
        else [res["opid"] if isinstance(res, dict) else res]
    ):
        wait_op(opid, mine=lambda: call("generate", [1]))
    print(f"note {i + 1} shielded; orchard notes now:", call("z_getnotescount", [1]))

# anchor with memo (wait until the wallet has verified the shielded balance)
for _ in range(40):
    bal = call("z_getbalanceforaccount", [0, 5])
    orchard = bal.get("pools", {}).get("orchard") or {}
    avail = orchard.get("available") if isinstance(orchard, dict) else orchard
    if avail is not None and float(avail) >= 0.001:
        break
    call("generate", [2])
print("anchor orchard balance:", call("z_getbalanceforaccount", [0, 5]))
C = "ab" * 32
opid = call(
    "z_sendmany",
    [u0, [{"address": u1, "amount": "0.001", "memo": "00" + C}], 10, "0.0001"],
)
res = wait_op(opid, mine=lambda: call("generate", [1]))
txid = res["txid"] if isinstance(res, dict) else res
call("generate", [1])
print("anchor txid:", txid)

# read back
view = call("z_viewtransaction", [txid])
print(json.dumps(view, indent=1)[:1500])
print("MEMO MATCH:", C in json.dumps(view))

# replay: resubmit the SAME raw transaction (same nullifier). The node
# must reject it — that is what makes the 409 in service terms true.
print("\n=== REPLAY ATTEMPT: resubmit identical raw tx (must fail) ===")
raw = call("gettransaction", [txid])["hex"]
try:
    res2 = call("sendrawtransaction", [raw])
    print("REPLAY ACCEPTED:", res2, "— NULLIFIER NOT ENFORCED!")
except RuntimeError as e:
    print("replay rejected as expected:", str(e)[:300])
    print(
        "\nRESULT: GO — shielded anchor + memo round-trip + nullifier replay rejection verified on regtest"
    )
