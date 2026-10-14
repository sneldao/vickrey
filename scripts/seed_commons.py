#!/usr/bin/env python3
"""Seed the Atlas commons with clearly-labelled sample observers.

The commons panel is much stronger with rows in it, but seeding it with real
people's records would be a lie. So this writes anchors under
``flow_id = sample-observer-NN``, which the field client renders with a
"sample observer" badge (``sampleMark`` in ``apps/field/app.js``) and the
explorer can filter on.

Two deliberate choices:

**The signatures are real.** Each sample observer has a real Ed25519 device key,
and every commitment is genuinely signed over a record body and genuinely
re-verified after it is written. Nothing here is a placeholder that merely looks
like a signature -- a MongoDB engineer can pull a document and check it, and the
public key is printed on every run. ``verify_samples`` re-checks the whole
collection on demand.

**The records are honest about being synthetic.** The commitments are computed
over the same body shape ``trust.sealObservation`` uses, so they recompute
correctly, but these are not photographs of anyone's walk. That is what the
``sample-observer`` flow id is for.

This refuses to run without an explicit acknowledgement, so it can never
silently contaminate a real commons:

    python3 scripts/seed_commons.py --uri "$MONGODB_URI" --seed-demo-data
    python3 scripts/seed_commons.py --uri "$MONGODB_URI" --verify
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "services" / "ledger"))

from cryptography.hazmat.primitives import serialization  # noqa: E402

from app.atlas import connect as connect_observations  # noqa: E402
from app.verify import canonical_json  # noqa: E402

KEY_PATH = Path.home() / ".vickrey" / "sample_observer_key.json"

# Three synthetic observers, each with its own walk, so the commons shows more
# than one contributor. Areas are coarse, exactly as a real anchor carries them.
OBSERVERS = [
    {
        "flow": "sample-observer-01",
        "label": "sample observer · Hackney Marshes",
        "area": {"lat": 51.5378, "lon": -0.0218},
        "model": "gemma3:4b",
        "records": [
            ("bird", "Common kingfisher", 0.72, "confirmed", None),
            ("bird", "Grey heron", 0.88, "confirmed", None),
            # a corrected identification, like the field client's own sample walk
            ("bird", "Common blackbird", 0.51, "corrected", "Mallard"),
        ],
    },
    {
        "flow": "sample-observer-02",
        "label": "sample observer · Crystal Palace",
        "area": {"lat": 51.4223, "lon": -0.0706},
        "model": "gemma3:4b",
        "records": [
            ("plant", "Common foxglove", 0.81, "confirmed", None),
            ("tree", "English oak", 0.69, "confirmed", None),
            ("plant", "Silver birch", 0.58, "corrected", "Downy birch"),
        ],
    },
    {
        "flow": "sample-observer-03",
        "label": "sample observer · Epping Forest",
        "area": {"lat": 51.6961, "lon": 0.1086},
        "model": "gemma3:4b",
        "records": [
            ("bird", "European robin", 0.9, "confirmed", None),
            ("bird", "Song thrush", 0.77, "confirmed", None),
            ("plant", "Common ivy", 0.85, "confirmed", None),
        ],
    },
]

TAG = "veles.observation"
SCHEMA = "veles.observation/1"
# Named once so the seeded commitment is reproducible and --verify can rebuild
# the exact body that was signed.
DETAIL = "Sample observer record, seeded for the demo commons."


# ---------------------------------------------------------------- keys


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def load_or_create_key(flow_id: str) -> tuple[Any, str]:
    """A stable sample-observer key, so re-running does not orphan old docs.

    One key per observer: three synthetic contributors sharing a single device
    key would misrepresent how attribution actually works in the commons, where
    each observer's key is what makes their anchors attributable to them.

    Persisted outside the repo: these are demo credentials, not source.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    path = KEY_PATH.parent / f"{flow_id}.json"
    if path.exists():
        private = serialization.load_pem_private_key(path.read_bytes(), password=None)
    else:
        private = Ed25519PrivateKey.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            private.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        path.chmod(0o600)
    public_b64 = b64url(
        private.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private, public_b64


# ------------------------------------------------------------- records


def committed_body(
    *, prev: str | None, observed_at: str, location: dict, model_id: str, payload: dict
) -> dict:
    """The exact shape trust.sealObservation commits to, so a sample
    commitment recomputes under the client's own canonicalisation."""
    return {
        "prev": prev,
        "observed_at": observed_at,
        "location": location,
        "model_id": model_id,
        "payload": payload,
    }


def coarse(area: dict) -> dict:
    return {"lat": round(area["lat"], 2), "lon": round(area["lon"], 2)}


def build_anchors(keys: dict[str, Any]) -> list[dict]:
    """One chained walk per observer, oldest first.

    ``keys`` maps flow id to that observer's Ed25519 private key.
    """
    anchors: list[dict] = []
    base = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)
    for observer in OBSERVERS:
        flow = observer["flow"]
        private = keys[flow]
        public_b64 = b64url(
            private.public_key().public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        prev: str | None = None
        for index, (kind, species, confidence, review, corrected_to) in enumerate(
            observer["records"]
        ):
            observed_at = (
                base + timedelta(hours=3 * index, minutes=17 * index)
            ).isoformat()
            observed_at = observed_at.replace("+00:00", "Z")
            payload: dict[str, Any] = {
                "kind": kind,
                "species": corrected_to or species,
                "confidence": None if review == "corrected" else confidence,
                "detail": DETAIL,
                "review": {
                    "decision": review,
                    "suggested_species": species,
                    "suggested_kind": kind,
                    "model_confidence": confidence,
                },
            }
            location = coarse(observer["area"])
            commitment = hashlib.sha256(
                canonical_json(
                    committed_body(
                        prev=prev,
                        observed_at=observed_at,
                        location=location,
                        model_id=observer["model"],
                        payload=payload,
                    )
                ).encode("utf-8")
            ).hexdigest()
            signature = b64url(private.sign(commitment.encode("utf-8")))

            anchors.append(
                {
                    "block_id": commitment,
                    "tag": TAG,
                    "flow_id": observer["flow"],
                    # The exact body that was committed. Kept only in memory for
                    # the post-write check -- it is never sent to Atlas, and the
                    # commons deliberately does not store the record.
                    "_payload": payload,
                    "message": {
                        "schema": SCHEMA,
                        "observed_at": observed_at,
                        "location": location,
                        "model_id": observer["model"],
                        "commitment": commitment,
                        "signature": signature,
                        "public_key": public_b64,
                        "prev": prev,
                        "summary": {
                            "kind": kind,
                            "species": corrected_to or species,
                            "confidence": None if review == "corrected" else confidence,
                            "review": review,
                        },
                    },
                    "_label": observer["label"],
                }
            )
            prev = commitment
    return anchors


def verify_signature(commitment: str, signature: str, public_b64: str) -> bool:
    """Check the Ed25519 signature over a stored commitment.

    This works on an Atlas document alone, because a commons stores the
    commitment, the signature and the public key together. Recomputing the
    *commitment* is not possible here and never will be: that needs the sealed
    record body, which the commons deliberately does not hold.
    """
    public = serialization.load_der_public_key(b64decode(public_b64))
    try:
        public.verify(b64decode(signature), commitment.encode("utf-8"))
    except Exception:
        return False
    return True


def b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify_seeded(anchor: dict) -> bool:
    """Full check at seed time, while the record body is still in hand.

    Recomputes the commitment *and* verifies the signature, so a sample anchor
    is provably self-consistent rather than merely well-shaped.
    """
    message = anchor["message"]
    body = committed_body(
        prev=message.get("prev"),
        observed_at=message["observed_at"],
        location=message["location"],
        model_id=message["model_id"],
        payload=anchor["_payload"],
    )
    expected = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    if expected != message["commitment"]:
        return False
    return verify_signature(
        message["commitment"], message["signature"], message["public_key"]
    )


# ----------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=os.environ.get("MONGODB_URI"))
    parser.add_argument("--database", default=os.environ.get("MONGODB_DB", "vickrey"))
    parser.add_argument("--seed-demo-data", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    if not args.uri:
        parser.error("no MONGODB_URI: pass --uri or export it")

    # Checked before any connection is opened, so this guardrail cannot be
    # bypassed by --verify and never touches a database it was not told to write.
    if not (args.seed_demo_data or args.verify):
        parser.error(
            "refusing to write without --seed-demo-data\n"
            "  These records are synthetic. They are labelled by a\n"
            "  sample-observer-NN flow id and shown with a 'sample observer'\n"
            "  badge, but confirm that is acceptable in this database first.\n"
            "  (--verify only reads and re-checks signatures.)"
        )

    keys: dict[str, Any] = {}
    print("sample observer device keys (one per observer):")
    for observer in OBSERVERS:
        private, public_b64 = load_or_create_key(observer["flow"])
        keys[observer["flow"]] = private
        print(f"  {observer['flow']}: {public_b64}")
    print(f"  private keys under {KEY_PATH.parent}, never committed\n")

    store = connect_observations(args.uri, database=args.database)
    store.ensure_indexes()

    if args.verify:
        docs = list(store.collection.find({"flow_id": {"$regex": "^sample-observer-"}}))
        bad = [
            d
            for d in docs
            if not verify_signature(
                d.get("commitment", ""), d.get("signature", ""), d.get("public_key", "")
            )
        ]
        print(f"signed correctly: {len(docs) - len(bad)}/{len(docs)} sample anchors")
        for d in bad:
            print(f"  FAILED {d.get('block_id')}")
        print(
            "\n  The commitment itself cannot be recomputed from here: that needs the\n"
            "  sealed record body, which the commons deliberately does not store."
        )
        return 1 if bad else 0

    if not args.seed_demo_data:
        parser.error("unreachable: the write guardrail is checked before connecting")

    anchors = build_anchors(keys)
    for anchor in anchors:
        store.put(
            block_id=anchor["block_id"],
            tag=anchor["tag"],
            flow_id=anchor["flow_id"],
            message=anchor["message"],
        )

    checked = [a for a in anchors if verify_seeded(a)]
    print(f"wrote {len(anchors)} sample anchors across {len(OBSERVERS)} observers")
    print(
        f"  every commitment recomputes and every signature verifies: {len(checked) == len(anchors)}"
    )
    for flow in sorted({a["flow_id"] for a in anchors}):
        count = sum(1 for a in anchors if a["flow_id"] == flow)
        print(f"  {flow}: {count}")
    print(f"\n  db: {args.database}.observations   store: mongodb-atlas")
    print(
        "  Remove them with: db.observations.deleteMany({flow_id: {$regex: '^sample-observer-'}})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
