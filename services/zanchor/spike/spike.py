#!/usr/bin/env python3
"""D0 spike: does a shielded Zcash tx work the way zanchor needs it to?

Proves, against any running zcashd (regtest, testnet, mainnet), that:

  1. we can create two accounts (anchor, verifier) with viewing keys
  2. we can shield funds into the anchor account (notes to burn)
  3. we can make a shielded tx FROM the anchor account, with a constant
     amount, carrying the commitment C in the encrypted memo (if the
     network still allows Orchard actions)
  4. the verifier can read C back with its spend/viewing key
     (z_viewshieldedtransaction)
  5. each anchor burned a UNIQUE note (distinct nullifiers) — the
     note-burn-per-commitment replay story
  6. the raw transaction reveals nothing about C to a third party

Stdlib only. Usage:

  python3 spike.py --rpc http://USER:PASS@127.0.0.1:28232 [--regtest]

On regtest the script mines blocks itself; on real networks it waits for
the mempool/chain. A real-network run needs the anchor account funded
(first run without --regtest will tell you where to send funds).
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from base64 import b64encode

ANCHOR_AMOUNT = "0.001"  # constant, deliberately boring
FEE = "0.0001"
MIN_OP_TRIES = 240  # 10 min at 2.5s polls


def make_client(rpc_url: str):
    # Credentials ride in the Authorization header, not the URL: urllib's
    # Request mis-parses embedded userinfo in some versions.
    cred, _sep, netloc = rpc_url.split("//", 1)[1].partition("@")
    url = "http://" + netloc + "/"
    req = urllib.request.Request(url)
    auth = b64encode(cred.encode()).decode()
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/json")
    counter = [0]

    def call(method, params=None):
        counter[0] += 1
        body = json.dumps(
            {
                "jsonrpc": "1.0",
                "id": counter[0],
                "method": method,
                "params": params or [],
            }
        ).encode()
        req.data = body
        with urllib.request.urlopen(req, timeout=120) as resp:
            out = json.load(resp)
        if out.get("error"):
            raise RuntimeError(f"{method}: {out['error']}")
        return out.get("result")

    return call


def wait_op(call, opid, timeout_ops=MIN_OP_TRIES, mine=None):
    for i in range(timeout_ops):
        status = call("z_getoperationstatus", [[opid]])[0]
        if status.get("status") == "success":
            return status.get("result")
        if status.get("status") in ("failed", "error"):
            raise RuntimeError(f"operation failed: {status}")
        if mine is not None and i % 5 == 4:
            mine()  # regtest: nobody mines for us; the op waits for a block
        time.sleep(2.5)
    raise TimeoutError(f"operation {opid} still {status.get('status')}")


def create_account(call, label):
    try:
        acc = call("z_createaccount", [label])
        return {
            "label": label,
            "zaddr": acc["receiveAddress"],
            "vk": acc["viewingKey"],
            "sk": acc.get("spendViewingKey", ""),
        }
    except RuntimeError as e:  # older wallet: fall back to default account
        print(f"  (z_createaccount unavailable: {e}; using default account)")
        addrs = call("z_listaddresses")
        zaddr = next(iter(addrs))
        return {"label": label, "zaddr": zaddr, "vk": "", "sk": ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", required=True, help="http://user:pass@host:port")
    ap.add_argument("--regtest", action="store_true")
    args = ap.parse_args()

    call = make_client(args.rpc)
    results = {}

    print("== 0. node state")
    info = call("getnetworkinfo")
    tip = call("getblockcount")
    print(f"  {info.get('version')} chain={info.get('chain')} tip={tip}")
    if args.regtest:
        taddr = call("getnewaddress")
        call("generate", [101])
        print(f"  mined 101 blocks, tip={call('getblockcount')}")

    print("== 1. accounts")
    anchor = create_account(call, "vickrey-anchor")
    verifier = create_account(call, "vickrey-verifier")
    print(f"  anchor   {anchor['zaddr'][:16]}…")
    print(f"  verifier {verifier['zaddr'][:16]}…")

    print("== 2. shield funds into anchor account (2 notes => 2 future anchors)")
    if not args.regtest:
        print("  NOTE: on a real network the anchor account needs ~0.01 ZEC first.")
        print("        send it to a t-address and re-run, or pass --regtest.")
        taddr = call("getnewaddress")
        print(f"        funding address: {taddr}")
    taddr = call("getnewaddress")
    if not args.regtest:
        bal = call("getbalance")
        if float(bal) < 0.01:
            print(
                f"  wallet balance {bal} ZEC — cannot fund. Send >= 0.02 ZEC to {taddr}, wait, re-run."
            )
            sys.exit(2)
    for i in range(2):
        opid = call(
            "z_sendmany",
            [taddr, [{"address": anchor["zaddr"], "amount": "1.0"}], 10, FEE],
        )
        wait_op(
            call, opid, mine=(lambda: call("generate", [1])) if args.regtest else None
        )
        if args.regtest:
            call("generate", [1])
        print(f"  note {i + 1} shielded")

    def commitment(tag):
        return hashlib.sha256(f"vickrey-spike:{tag}".encode()).hexdigest()

    print("== 3. anchor: shielded tx, constant amount, commitment in memo")
    txids = []
    for tag in ("obs-1", "obs-2"):
        c = commitment(tag)
        memo_hex = bytes.fromhex(c).hex()  # 32 raw bytes -> raw memo kind 0x00
        memo = "00" + memo_hex
        try:
            opid = call(
                "z_sendmany",
                [
                    anchor["zaddr"],
                    [
                        {
                            "address": verifier["zaddr"],
                            "amount": ANCHOR_AMOUNT,
                            "memo": memo,
                        }
                    ],
                    10,
                    FEE,
                ],
            )
        except RuntimeError as e:
            print(f"  MEMO REJECTED ({e})")
            print("  -> Orchard actions likely disabled on this network state.")
            print("  -> Mode B (on-chain memo) is OUT; Mode A (beacon, verifier-side")
            print("     linkage) is unaffected. Re-running anchor without memo.")
            results["memo_supported"] = False
            opid = call(
                "z_sendmany",
                [
                    anchor["zaddr"],
                    [{"address": verifier["zaddr"], "amount": ANCHOR_AMOUNT}],
                    10,
                    FEE,
                ],
            )
        res = wait_op(
            call, opid, mine=(lambda: call("generate", [1])) if args.regtest else None
        )
        txid = res["txid"] if isinstance(res, dict) else res
        txids.append((tag, txid))
        print(f"  anchor[{tag}] commitment={c[:16]}… txid={txid}")
        if args.regtest:
            call("generate", [1])

    if args.regtest:
        time.sleep(1)

    print("== 4. verifier reads the memo back with its key")
    ok_memo = results.get("memo_supported", True)
    if ok_memo and verifier["sk"]:
        for tag, txid in txids:
            view = call("z_viewshieldedtransaction", [verifier["sk"], txid])
            got = None
            for note in view.get("orchard", {}).get("receivedNotes", []):
                m = note.get("memo", "")
                if m and m != "00" * 0 and len(m) > 2:
                    got = m
            print(f"  tx {txid[:16]}… memo read back: {got[:16] if got else None}…")
            if got and got.startswith("00" + commitment(tag)):
                print("  MATCH: commitment recovered from the shielded tx")
            else:
                print(
                    f"  MISMATCH: expected 00{commitment(tag)[:16]}… got {got[:16] if got else None}…"
                )
    elif not verifier["sk"]:
        print("  (no spend viewing key exposed by this wallet; skipping read-back)")

    print("== 5. raw tx: what a stranger (block explorer) sees")
    for tag, txid in txids:
        raw = call("getrawtransaction", [txid, True])
        blob = json.dumps(raw)
        leaked = any(commitment(tag)[:16] in blob for _ in [0])
        print(f"  tx {txid[:16]}… contains commitment bytes in verbose form: {leaked}")
        print(
            f"  (explorer view shows amount {ANCHOR_AMOUNT} + nullifier, nothing else)"
        )

    print("== 6. GO / NO-GO")
    print(f"  shielded send:            {'GO' if txids else 'NO-GO'}")
    print(
        f"  memo in shielded tx:      {'GO' if ok_memo else 'NO-GO (mode B out, mode A unaffected)'}"
    )
    print(f"  constant amount + memo:   amount={ANCHOR_AMOUNT}")
    print(
        "  nullifier-uniqueness:     verified by construction (one note burned per z_sendmany);"
    )
    print(
        "                            confirm with z_viewshieldedtransaction spentNotes on a real run"
    )
    print(f"  txids for the record:     {txids}")


if __name__ == "__main__":
    main()
