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
  "mode": "A | B",
  "shielded": true,
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

Replay protection depends on what the node will actually do, so state it by
case in `docs/PRIVACY.md` — do not claim the database is the replay protection.
With shielded spends available, mode A's primary protection is the unique
nullifier: replaying means double-spending the burned note, and the node
rejects it. When the node refuses shielded spends (see `shielded` below), there
is no nullifier to burn, and **this `409` is the only replay protection left** —
say so plainly rather than letting the nullifier claim stand.

## `GET /receipts/{receipt_id}`

The verifier-held binding. Returns the receipt row, or `404`
(`{"detail": "…"}`) for an unknown id.

```json
{
  "receipt_id": "rec_01J...",
  "commitment": "…64-hex…",
  "status": "queued | broadcast | confirmed",
  "mode": "A | B",
  "shielded": true,
  "txid": "…hex… or null",
  "height": 2712345 or null,
  "anchored_at": "…ISO 8601… or null"
}
```

There is **no** `GET /receipts` list endpoint on purpose: the service must not
offer an enumeration of what has been anchored.

## `mode` and `shielded` — say what the transaction actually is

These two fields exist so the clients never have to guess, and they are **not
redundant**.

- `mode` is the mechanism the service ran: `A` = note-burn beacon, `B` =
  commitment in the encrypted memo.
- `shielded` is the empirical property of the transaction that actually went to
  the node: `true` if it spends and receives in the shielded pool, `false` if
  the service fell back to a **transparent constant-amount beacon** because the
  node refused shielded spends (Orchard actions are disabled in some releases —
  see `ECATHON.md`).

A `mode: "A"` receipt with `shielded: false` is a correct, contract-legal
answer, and it is the honest one when the fallback fires. The clients derive
their labels from `shielded`, never from `mode` or from their own hopes:

- `shielded: true` → the field client chips `SHIELDED · <status>`, the explorer
  stamps `SHIELDED · VERIFIED` and its reveal checklist reads "nothing on the
  chain to check".
- `shielded: false` → `TRANSPARENT · <status>`; the explorer's checklist shows
  what a transparent transaction really exposes (amount, addresses, block time)
  and says what it still does not: species, area, observer, purpose.
- absent / null → the clients claim nothing: the badge is the plain status.

Printing `SHIELDED` over a transparent transaction is a false claim about the
one thing this project is judged on. `scripts/demo_zcash.sh` fails a service
that omits either field.

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
{
  "status": "ok",
  "node": "ok | down",
  "mode": "A | B",
  "shielded": true,
  "notes_available": 3
}
```

`notes_available` is how many dedicated shielded notes remain to burn (mode A).
`mode` is the running mode: A = note-burn beacon, B = commitment in the
encrypted memo (stretch). `shielded` says whether the running pipeline produces
shielded transactions or has fallen back to transparent; the receipt is still
the authority per anchor, because the answer can change with a node upgrade.

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
