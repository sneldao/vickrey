# zanchor API contract (pinned)

The contract between `services/zanchor` (the shielded anchor service — Dev 1
implements it) and the field client / explorer (Dev 2 codes against it). The
shapes below are agreed before the service exists so both sides can be built in
parallel. If an implementation detail has to change, change it **here** first;
this file is the single source of truth for the wire format.

Base URL: `http://localhost:8092` locally (config key `zanchorUrl` in the
field client). All bodies are JSON.

## What the service does

One observation commitment `C` (64-hex sha256) becomes one deliberately
unremarkable **shielded Zcash transaction** — constant amount, one dedicated
note burned so the nullifier is unique per commitment (replay = double-spend
rejected by the node). The service keeps the `C ↔ txid ↔ height` binding as a
receipt. **That binding is verifier-held: it is served only to the holder of a
receipt id, and is never published to the commons' public API.**

## `POST /anchor`

Anchor one commitment. One dedicated note is burned for it.

Request:

```json
{ "commitment": "64-hex sha256 of the canonical sealed entry" }
```

Nothing else is sent. No species, no area, no timestamp, no signature, no
public key — the anchor must not be correlatable even at the service edge. The
device's signature over `C` stays on-device and is presented at selective-
disclosure time.

Response `202`:

```json
{
  "receipt_id": "rec_01J...",
  "commitment": "…64-hex…",
  "status": "queued | broadcast | confirmed",
  "txid": "…hex… or null while queued",
  "height": 2712345 or null until confirmed,
  "anchored_at": "2026-10-27T12:34:56Z or null until confirmed"
}
```

Errors:

| Code | Shape                                       | Meaning                                                                       |
| ---- | ------------------------------------------- | ----------------------------------------------------------------------------- |
| 400  | `{"detail": "…"}`                           | body is not a 64-hex commitment                                               |
| 409  | `{"detail": "commitment already anchored"}` | **Replay rejection.** This commitment already has a receipt; no second anchor |
| 503  | `{"detail": "…"}`                           | node unreachable / no spendable note left                                     |

The `409` is defense in depth: mode A's primary replay protection is the
unique nullifier (replaying means double-spending the burned note, which the
node rejects), and mode B additionally relies on this verifier-side rejection.
State which guarantee comes from where in `docs/PRIVACY.md` — do not claim the
database is the replay protection.

## `GET /receipts/{receipt_id}`

The verifier-held binding. Returns the receipt row, or `404`
(`{"detail": "…"}`) for an unknown id.

```json
{
  "receipt_id": "rec_01J...",
  "commitment": "…64-hex…",
  "status": "queued | broadcast | confirmed",
  "txid": "…hex… or null",
  "height": 2712345 or null,
  "anchored_at": "…ISO 8601… or null"
}
```

There is **no** `GET /receipts` list endpoint on purpose: the service must not
offer an enumeration of what has been anchored.

## `GET /chain/tx/{txid}`

Proof-of-existence anyone may run: "a transaction with this id exists at height
H." It reveals nothing about any commitment.

```json
{
  "txid": "…hex…",
  "exists": true,
  "height": 2712345,
  "confirmations": 12,
  "block_time": "…ISO 8601… or null"
}
```

`404 {"detail": "…"}` when the node does not know the transaction. This
endpoint must never echo a commitment.

## `GET /health`

```json
{ "status": "ok", "node": "ok | down", "mode": "A | B", "notes_available": 3 }
```

`notes_available` is how many dedicated shielded notes remain to burn (mode A).
`mode` is the running mode: A = note-burn beacon, B = commitment in the
encrypted memo (stretch).

## Client-side scheduling (owned by the field client)

The jittered batch schedule is **client-side**: the client never POSTs at the
moment of capture or at "back in range". The service must not add its own
delay logic beyond transaction mechanics; batching policy lives in
`apps/field/schedule.js` and its defaults are documented in
`docs/PRIVACY.md` (lead owns that doc; the numbers come from the config
defaults).

## Status words

The receipt `status` enum is exactly `queued`, `broadcast`, `confirmed`. The
client maps unknown values to its generic status note rather than guessing.
