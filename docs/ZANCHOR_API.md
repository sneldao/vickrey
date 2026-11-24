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

Required header:

```http
Idempotency-Key: client-generated-key-001
Authorization: Bearer <token>
```

The key is 8-128 letters, digits, dots, underscores, colons or hyphens.
`Authorization` is required only in production.

Nothing else is sent. No observation metadata is sent — no species, no area,
no timestamp, no signature, no public key; the service can still correlate IP
addresses, arrival times and commitments. The device's signature over `C`
stays on-device and is presented at selective-disclosure time.

Response `202` (example: a queued anchor). The usual path is
`submitting → queued → broadcast → confirmed`; `submitting` is normally
transient. `txid` appears at `broadcast`, `height` and `anchored_at` at
`confirmed`, and `error` is present for `failed` or `reconciling`. Before an
opid exists, `shielded` is `null`: no transaction has been submitted, so the
service makes no shielded/transparent claim.

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

| Code | Shape                                  | Meaning                                                                                      |
| ---- | -------------------------------------- | -------------------------------------------------------------------------------------------- |
| 400  | `{"detail": "…"}`                      | invalid JSON/commitment or missing/malformed `Idempotency-Key`                               |
| 401  | `{"detail": "unauthorized"}`           | production bearer token missing or wrong (`WWW-Authenticate: Bearer`)                        |
| 409  | `{"detail": "…"}`                      | idempotency key reused with different raw bytes, or commitment already has an active receipt |
| 413  | `{"detail": "request body too large"}` | body exceeds `ZANCHOR_MAX_BODY_BYTES` (default 16,384 bytes), including chunked bodies       |
| 429  | `{"detail": "anchor quota exceeded"}`  | shared SQLite fixed-window anchor quota exhausted                                            |
| 503  | `{"detail": "…"}`                      | node unreachable, wrong expected network, or another anchor is in flight                     |

Nullifiers prevent spending the same note twice at consensus; they say
nothing about commitments. Per-commitment deduplication is the service's
`409`, enforced by a SQLite uniqueness constraint and a serialized reservation
in both modes. The one-at-a-time guard covers `submitting`, `reconciling`,
`queued`, and `broadcast` receipts.

### Idempotency, retries, and uncertain outcomes

The service hashes the **exact request body bytes** with SHA-256 and stores an
immutable `(Idempotency-Key, request_sha256, receipt_id)` record atomically
with the initial `submitting` receipt, before any wallet submission.

- Same key and same bytes returns the current state of the same receipt and
  never submits a second operation. A replay is checked before node polling
  and does not consume quota.
- Same key with any changed bytes is `409`, even if the JSON meaning is
  unchanged. A different key for an already active commitment is also `409`.
- A definite node refusal or failed node operation becomes `failed`; the
  receipt id and event history are retained. Retry that commitment with a
  **new** idempotency key. The retry reuses the failed receipt id and appends
  history. Replaying the old key still returns that same receipt and does not
  resubmit.
- A transport error, bare HTTP 5xx, malformed operation result, or process
  crash after submission may have created a node operation. The receipt becomes
  `reconciling` (an expired `submitting` lease is moved there on recovery).
  The worker queries only the known opid with `z_getoperationstatus`; it never
  calls `z_sendmany` for a reconciling receipt.
- If the crash occurred before the opid could be persisted, automatic recovery
  cannot identify the operation. The receipt remains `reconciling` and blocks
  new anchors until an operator reconciles the node/wallet out of band. The
  service does not guess, fabricate an opid, or blindly resend. `reconciling`
  is not proof of either success or failure.

Worker leases and their expiry are durable SQLite fields. Conditional lease
claims prevent multiple service processes from advancing the same operation;
the submitter identity separately allows a late RPC result to persist its opid
without authorizing a resend.
The service is fail-closed: a refused shielded send leaves a durable `failed`
receipt with nothing downgraded — there is no transparent fallback.

`ZANCHOR_ENV` selects the deployment environment (`demo` or `production`);
it is separate from `ZANCHOR_MODE`, which still selects the transaction
mechanism (`A` or `B`). Demo is the default and is rate-limited. Production
requires `ZANCHOR_API_TOKEN` and bearer authentication on both POST endpoints.

## `GET /receipts/{receipt_id}`

The verifier-held binding. Returns the receipt row, or `404`
(`{"detail": "…"}`) for an unknown id. Internal opids, worker ids, lease
expiry, idempotency keys, and request hashes are not exposed. Poll this
endpoint for `reconciling`; do not retry with a new key expecting a new chain
operation.

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
  transparent fallback: a refused send leaves a `failed` receipt, so
  `shielded: false` exists in the contract only for receipts written before the
  fallback was removed. A submission with no opid yet reports `null`.

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
  "network": "regtest",
  "env": "demo",
  "auth_required": false,
  "body_limit_bytes": 16384,
  "quotas": {
    "window_seconds": 60,
    "anchor": 10,
    "disclosure": 30
  }
}
```

`notes_available` is how many dedicated shielded notes remain in the wallet
(reported in both modes).
`mode` is the running mode: A = note-burn beacon (legacy), B = commitment in the
encrypted memo (default; an invalid `ZANCHOR_MODE` fails startup). `network`
is the node's own `getblockchaininfo` answer, normalised (`main`, `testnet`,
`regtest`, or `unknown`). `shielded` says whether the running pipeline produces
shielded transactions; the receipt is still the authority per anchor.

`env` is `demo` or `production`. `auth_required` is true only in production.
`body_limit_bytes` and `quotas` are the active limits, not token material; no
API token or RPC credential is returned. Quotas are service-wide fixed windows
shared through SQLite, so they cover all workers/processes using the database.

Configuration:

| Variable                       | Default | Meaning                                                                                        |
| ------------------------------ | ------- | ---------------------------------------------------------------------------------------------- |
| `ZANCHOR_ENV`                  | `demo`  | `demo` or `production`; invalid values fail startup                                            |
| `ZANCHOR_API_TOKEN`            | unset   | required in production; bearer token for anchor and disclosure POSTs; ignored for auth in demo |
| `ZANCHOR_MODE`                 | `B`     | transaction mechanism, `A` or `B` (not an environment setting)                                 |
| `ZANCHOR_MAX_BODY_BYTES`       | `16384` | maximum JSON body bytes, including streamed/chunked requests                                   |
| `ZANCHOR_QUOTA_WINDOW_SECONDS` | `60`    | fixed quota window                                                                             |
| `ZANCHOR_ANCHOR_QUOTA`         | `10`    | anchor reservations per window; idempotent replays excluded                                    |
| `ZANCHOR_DISCLOSURE_QUOTA`     | `30`    | disclosure POST attempts per window, including rejected verification attempts                  |
| `ZANCHOR_LEASE_SECONDS`        | `300`   | submission/reconciliation worker lease duration                                                |

Production refuses to start without a non-whitespace `ZANCHOR_API_TOKEN`.
Demo also enforces body limits and quotas; it is not an unbounded bypass.
Changing environment or mode requires a process restart, not a per-request
switch.

## `GET /receipts/{receipt_id}/verify`

Fresh node read every call — no cached verdict. Capability: the receipt id
itself; production bearer auth is not required here. `404` for an unknown id,
`503` when the node is unreachable or absent. A pending receipt may be advanced
through the leased worker path first. Reconciliation only queries a known
opid; this endpoint never submits or resends an operation. A `reconciling`
receipt without an opid cannot produce a verification proof automatically.

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

Body `{"purpose": "1–200 chars"}`. Production requires the same bearer token
as `POST /anchor` (`401` otherwise). The body limit and disclosure fixed-window
quota apply (`413` and `429` respectively). Runs the same fresh verification,
refuses with `409` unless `commitment_verified` is true, `503` when the node is
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

## Durable storage guarantees

SQLite migration is additive: existing receipt rows and audit rows are kept.
New operation columns, immutable idempotency records, fixed-window quota
counters, and append-only `anchor_events` are added without rewriting old
receipts. Events contain only receipt/worker/opid identifiers, event type, and
time; they never contain credentials, raw memos, commitments, or observation
payloads. SQLite triggers reject updates and deletes on `anchor_events`,
`disclosure_audit`, and `idempotency`. None of these internal tables has an
HTTP enumeration endpoint.

## Client-side scheduling (owned by the field client)

The jittered batch schedule is **client-side**: the client never POSTs at the
moment of capture or at "back in range". The service must not add its own
delay logic beyond transaction mechanics; batching policy lives in
`apps/field/schedule.js` and its defaults are documented in
`docs/PRIVACY.md` (lead owns that doc; the numbers come from the config
defaults).

## Status words

The receipt `status` enum is exactly `submitting`, `reconciling`, `queued`,
`broadcast`, `confirmed`, `failed`.

- `submitting`: a durable receipt and worker lease exist; the wallet submission
  is in progress or its lease expired before the outcome was recorded.
- `reconciling`: the outcome is uncertain. Only the known opid may be queried;
  no new operation is created. Without an opid, operator reconciliation is
  required and the receipt remains blocked.
- `queued`: the node accepted the submission and returned an opid, which is
  durable but not public. The operation has not yet reported success.
- `broadcast`: node operation success supplied a txid; chain confirmation is
  still pending.
- `confirmed`: the txid has at least one confirmation at the recorded height.
- `failed`: a definite refusal or terminal node operation failure. Nothing is
  blindly retried. A new idempotency key may retry the same commitment and
  reuses this receipt id/history.

While any receipt is `submitting`, `reconciling`, `queued`, or `broadcast`, the
service accepts no different anchor (`503`) — the wallet's shielded view lags
the chain by a few blocks, and a concurrent anchor could select the same note,
which the node would reject as a duplicate nullifier. The client maps unknown
values to its generic status note rather than guessing, and must not present
`reconciling` as confirmed or failed.
