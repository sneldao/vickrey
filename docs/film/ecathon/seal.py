"""Seal this film's script.

Hashes narration.json (SHA-256), anchors the hash as a commitment through
zanchor (POST /anchor {commitment}), waits for the receipt to confirm, and
writes SEAL.json. Anyone can re-check the hash with:

    shasum -a 256 docs/film/ecathon/narration.json

Usage: python3 seal.py [--zanchor http://127.0.0.1:8801]
The service in SEAL.json is labelled honestly: a mock is a hash and a counter,
not a Zcash transaction.
"""

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--zanchor", default="http://127.0.0.1:8801")
args = ap.parse_args()
Z = args.zanchor.rstrip("/")


def call(method, path, body=None):
    req = urllib.request.Request(
        Z + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


digest = hashlib.sha256(open("narration.json", "rb").read()).hexdigest()
_, health = call("GET", "/health")
status, receipt = call("POST", "/anchor", {"commitment": digest})
if status == 409:
    raise SystemExit(
        "this commitment is already anchored on that service (replay refused)"
    )
assert status == 202, (status, receipt)
for _ in range(120):
    status, receipt = call("GET", "/receipts/" + receipt["receipt_id"])
    if receipt.get("status") == "confirmed":
        break
    time.sleep(1)
else:
    raise SystemExit("receipt did not confirm: %r" % receipt)

out = {
    "sealed": "docs/film/ecathon/narration.json",
    "sha256": digest,
    "zanchor": Z,
    "service_health": health,
    "receipt": receipt,
    "is_mock": "mock" in str(receipt.get("receipt_id", "")).lower(),
}
json.dump(out, open("SEAL.json", "w"), indent=2)
print(json.dumps(out, indent=2))
