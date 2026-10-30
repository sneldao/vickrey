# zanchor API reference

The wire contract of `services/zanchor` (the shielded anchor service) as
implemented. This file is the reference for the field client and explorer;
when the service changes, this file changes with it.

Base URL: the same-origin `/api` path by default (the deployment proxies it
to the service); `http://localhost:8092` applies only when `zanchorUrl` is
explicitly configured to a direct port. All bodies are JSON.

## What the service does

One observation commitment `C` (64-hex sha256) becomes one deliberately
unremarkable **shielded Zcash transaction** — constant amount, with the
commitment carried in the transaction's encrypted memo by default (mode B;
mode A, the legacy path, is a dedicated note burn). The service keeps the
`C ↔ txid ↔ height` binding as a receipt. **That binding is verifier-held:
it is served only to whoever presents the receipt id — a bearer capability —
and is never published to the commons' public API.** There is no
per-commitment uniqueness at consensus: deduplication is the service's `409`,
not the nullifier set. The service still sees the caller's IP and the
commitment's arrival time; the schedule is what keeps arrival away from
capture.

## `POST /anchor`

Anchor one commitment. One dedicated note is burned for it.

Request:

```json
{
  "commitment": "9f2b7c1d4e5a6b8c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c"
}
```

Nothing else is sent. No observation metadata is sent — no species, no area,
no timestamp, no signature, no public key; the service can still correlate IP
addresses, arrival times and commitments. The device's signature over `C`
stays on-device and is presented at selective-disclosure time.

Response `202` (example: a queued anchor; `status` walks
`queued → broadcast → confirmed` or `failed`. `txid` appears at `broadcast`,
`height` and `anchored_at` at `confirmed`, and `error` is present only on
`failed`):

```json
{
  "receipt_id": "rec_01J7X2M4K9P0Q3R5S8T",
  "commitment": "9f2b7c1d4e5a6b8c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c",
  "status": "queued",
  "mode": "B",
  "shielded": true,
  "txid": null,
  "height": null,
  "anchored_at": null
}
```

Errors:

| Code | Shape                                       | Meaning                                                                                              |
| ---- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| 400  | `{"detail": "…"}`                           | body is not a 64-hex commitment                                                                      |
| 409  | `{"detail": "commitment already anchored"}` | **Replay rejection.** This commitment already has a receipt; no second anchor                        |
| 503  | `{"detail": "…"}`                           | node unreachable / no spendable note left / anchor in flight (one at a time; retry once it confirms) |

Nullifiers prevent spending the same note twice at consensus; they say
nothing about commitments. Per-commitment deduplication is **this `409`**,
enforced by the service's receipt database under one lock, in both modes.
The service is fail-closed: a refused shielded send is a 503 with nothing
downgraded — there is no transparent fallback.

## `GET /receipts/{receipt_id}`

The verifier-held binding. Returns the receipt row, or `404`
(`{"detail": "…"}`) for an unknown id.

```json
{
  "receipt_id": "rec_01J7X2M4K9P0Q3R5S8T",
  "commitment": "9f2b7c1d4e5a6b8c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c",
  "status": "confirmed",
  "mode": "B",
  "shielded": true,
  "txid": "b41d3e9a8f6c2b7d5e4a9c8f0b1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0",
  "height": 2712345,
  "anchored_at": "2026-10-30T12:34:56Z"
}
```

There is **no** `GET /receipts` list endpoint on purpose: the service must not
offer an enumeration of what has been anchored.

## `mode` and `shielded` — say what the transaction actually is

These two fields exist so the clients never have to guess, and they are **not
redundant**.

- `mode` is the mechanism the service ran: `A` = note-burn beacon (legacy),
  `B` = commitment in the encrypted memo (the default).
- `shielded` is the empirical property of the transaction that actually went to
  the node: `true` if it spends and receives in the shielded pool. There is no
  transparent fallback: a refused send is a 503, so `shielded: false` exists in
  the contract only for receipts written before the fallback was removed.

The clients derive their labels from `shielded`, never from `mode` or from
their own hopes:

- `shielded: true` → the field client chips `SHIELDED · <status>` and the
  explorer stamps `SHIELDED · <verdict>` — where the verdict comes from the
  receipt's chain check **and** a fresh `/verify` answer, never from the flag
  alone. `shielded` never by itself produces a VERIFIED stamp.
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
  "txid": "b41d3e9a8f6c2b7d5e4a9c8f0b1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0",
  "exists": true,
  "height": 2712345,
  "confirmations": 12,
  "block_time": "2026-10-30T12:31:09Z"
}
```

`404 {"detail": "…"}` when the node does not know the transaction. This
endpoint must never echo a commitment.

## `GET /health`

```json
{
  "status": "ok",
  "node": "ok",
  "mode": "B",
  "shielded": true,
  "notes_available": 3,
  "network": "regtest"
}
```

`notes_available` is how many dedicated shielded notes remain in the wallet
(reported in both modes).
`mode` is the running mode: A = note-burn beacon (legacy), B = commitment in the
encrypted memo (default; an invalid `ZANCHOR_MODE` fails startup). `network`
is the node's own `getblockchaininfo` answer, normalised (`main`, `testnet`,
`regtest`, or `unknown`). `shielded` says whether the running pipeline produces
shielded transactions; the receipt is still the authority per anchor.

## `GET /receipts/{receipt_id}/verify`

Fresh node read every call — no cached verdict. Capability: the receipt id
itself. `404` for an unknown id, `503` when the node is unreachable or absent.
A pending receipt is advanced through the worker path first.

```json
{
  "receipt_id": "rec_01J7X2M4K9P0Q3R5S8T",
  "commitment": "9f2b7c1d4e5a6b8c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c",
  "txid": "b41d3e9a8f6c2b7d5e4a9c8f0b1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0",
  "height": 2712345,
  "confirmations": 12,
  "network": "regtest",
  "transaction_verified": true,
  "commitment_verified": true,
  "binding": "encrypted_memo",
  "verification_source": "service_wallet",
  "reason": "commitment_in_encrypted_memo"
}
```

`txid` may already be non-null once the receipt is `broadcast`; verification
reads `height` and `confirmations` after the receipt is confirmed.
`network` is one of `main`, `testnet`, `regtest`, or `unknown`;
`binding` is `verifier_record` for mode A. A client-side `VERIFIED` verdict
requires every binding field to match the receipt — receipt id, txid,
commitment, height — plus `confirmations ≥ 1`, `verification_source
"service_wallet"`, `binding "encrypted_memo"`, a known `network`, and both
booleans. Any service answering `"network": "mock"` (the local mock does)
can never produce a proof — it exercises the UI only.

- `transaction_verified`: the receipt's txid exists at the node with at least
  one confirmation, at exactly the height the receipt stored when it confirmed,
  and the receipt is `confirmed`. Mempool, missing height, reorg, wrong id or
  wrong height never pass (`reason` says which).
- `commitment_verified`: all of the above, plus mode B plus a shielded
  transaction whose `z_viewtransaction` output memo decodes to exactly
  `0x00 || commitment` (strict match; no substring search). Mode A is always
  `false` with `reason: "verifier_record_only"` — a confirmed transaction
  whose binding rests on the service's records, not on a memo proof.
- `network` comes from the real `getblockchaininfo`; `unknown` fails the proof.
- No private memo contents, viewing keys, or wallet data are returned.
- The memo is read using the service wallet — a service-held verification,
  not independent verification. Clients must say so.

## `POST /receipts/{receipt_id}/disclosure`

Body `{"purpose": "1–200 chars"}`. Runs the same fresh verification, refuses
with `409` unless `commitment_verified` is true, `503` when the node is
unavailable, `404` for an unknown id. On success it appends one line to the
append-only `disclosure_audit` table (receipt id, time, purpose — no read
endpoint) and returns:

```json
{
  "schema": "vickrey.receipt-disclosure/1",
  "receipt": {
    "receipt_id": "rec_01J7X2M4K9P0Q3R5S8T",
    "commitment": "9f2b7c1d4e5a6b8c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c",
    "status": "confirmed",
    "mode": "B",
    "shielded": true,
    "txid": "b41d3e9a8f6c2b7d5e4a9c8f0b1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0",
    "height": 2712345,
    "anchored_at": "2026-10-30T12:34:56Z"
  },
  "verification": {
    "receipt_id": "rec_01J7X2M4K9P0Q3R5S8T",
    "commitment": "9f2b7c1d4e5a6b8c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c",
    "txid": "b41d3e9a8f6c2b7d5e4a9c8f0b1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0",
    "height": 2712345,
    "confirmations": 12,
    "network": "regtest",
    "transaction_verified": true,
    "commitment_verified": true,
    "binding": "encrypted_memo",
    "verification_source": "service_wallet",
    "reason": "commitment_in_encrypted_memo"
  }
}
```

The record's contents never touch this service: the field client assembles
the shareable bundle (sealed entry + device public key + this response)
locally and downloads it.

## Client-side scheduling (owned by the field client)

The jittered batch schedule is **client-side**: the client never POSTs at the
moment of capture or at "back in range". The service must not add its own
delay logic beyond transaction mechanics; batching policy lives in
`apps/field/schedule.js` and its defaults are documented in
`docs/PRIVACY.md` (lead owns that doc; the numbers come from the config
defaults).

## Status words

The receipt `status` enum is exactly `queued`, `broadcast`, `confirmed`,
`failed`. A `failed` receipt anchored nothing (the node rejected its note
selection); re-submitting the same commitment is allowed and replaces it.
While a receipt is `queued` or `broadcast`, the service accepts no further
anchors (`503`) — the wallet's shielded view lags the chain by a few
blocks, and a concurrent anchor could select the same note, which the node
would reject as a duplicate nullifier. The client maps unknown values to
its generic status note rather than guessing.
