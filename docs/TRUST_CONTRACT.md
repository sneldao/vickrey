# Vickrey trust contract

This is the acceptance baseline for integrity, privacy and recovery work. It
does not upgrade a demo claim into a production guarantee. The deployment
status remains in `STATUS.md`; the privacy tradeoffs remain in `PRIVACY.md`; the
wire formats remain in `ZANCHOR_API.md`.

## Claims and limits

| Claim                 | What establishes it                                                                                                                           | What it does not establish                                                         |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Journal seal intact   | Every entry signature, commitment, `prev` link and ordering verifies under the device public key                                              | Observation accuracy, observer identity, correct clock, absence of deleted history |
| Journal head retained | A separately signed checkpoint covers the complete journal head and entry count                                                               | Protection from a copied historical device state                                   |
| Entry was anchored    | Fresh service-wallet verification matches receipt id, commitment, txid and height, with at least one confirmation and an encrypted-memo proof | Independent chain verification, capture time, whole-journal validity               |
| Disclosure authentic  | The bundled entry recomputes to its commitment and verifies under the bundled device key; receipt bindings agree                              | Sender identity, recipient identity, revocation                                    |
| Observation corrected | An append-only correction references the original commitment and is signed by the same device key                                             | Erasure of the original record or its anchor                                       |

A verified result must name its verification source. A service-wallet memo
check is not an independent proof. A mock network can never produce VERIFIED.
A `shielded` flag without fresh verification is never sufficient.

## Client invariants

1. The journal is the integrity authority. The outbox is a delivery projection,
   not the retained history. Verification covers the entire journal even when
   the outbox is empty.
2. The same Ed25519 key signs observations, journal-head checkpoints and
   corrections. Key loss cannot be repaired by silently generating a new key.
3. Creating a record atomically commits its journal record, outbox entry and
   anchor-time draw. A failed commit leaves all three unchanged.
4. The outbox and journal sync state are updated atomically after delivery.
   A crash cannot remove the only journal copy or lose its retained receipt.
5. The device fails closed if persistent storage is unavailable, corrupt,
   unmigratable or cryptographically invalid. Sealing, sync, backup and restore
   do not continue as though the device were empty.
6. Restoring or migrating never silently overwrites existing records. Recovery
   is explicit, preserves a readable previous state where possible, and tells
   the observer if it cannot.
7. Anchor scheduling draws are durable. Restarting the page cannot reshuffle
   an already drawn time or bypass the production delay and jitter defaults.
8. Backup authenticity is checked before any write. Passphrases and private
   keys never leave the device through an API request.

## Service invariants

1. Public ingestion cannot overwrite a previously submitted payload. Replays
   with the same idempotency key and bytes return the original resource;
   changed bytes under that key are refused.
2. Verification attempts are append-only and bound to the message version they
   checked. A concurrent update or tamper cannot leave a fresh verdict attached
   to stale content.
3. A verifier-held receipt binding is a bearer capability. There is no receipt
   enumeration endpoint, and access logs must not record receipt identifiers.
4. Commitment anchoring is idempotent by commitment and idempotency key. A
   retry after an uncertain RPC outcome must reconcile the chain rather than
   broadcast a second operation blindly.
5. An anchor operation has a durable state before RPC submission and records
   its outcome after it. Expired worker leases permit reconciliation, not an
   assumption that no transaction exists.
6. Mode B requires an exact `0x00 || commitment` memo match in a confirmed
   shielded transaction. Mode A remains verifier-record-only. There is no
   transparent fallback and no mock-network proof.
7. A disclosure audit row is appended only after fresh commitment verification.
   It contains receipt id, UTC time and stated purpose, not observation data.
8. Expensive inference and paid context calls require authentication, request
   limits and quotas. Unauthenticated demo behavior is explicit and bounded.

## Recovery and compatibility

- Schema changes are versioned and additive. Existing localStorage data is
  validated before migration; malformed input is shown, never replaced.
- A schema v2 correction never rewrites a signed v1 observation. It references
  the original commitment and preserves the original payload.
- A checkpoint mismatch blocks sync until the user recovers the missing tail.
  It does not invite the app to invent entries or re-sign the journal.
- Backups made under `/1` remain importable after migration. New backups must
  include checkpoints and corrections once schema v2 ships.
- Demo tamper tools are separate from production authority routes and cannot
  be enabled accidentally in a production configuration.

## Release gates

A release cannot claim the hardened field-record primitive until these pass:

- full client and service test suites in CI;
- browser tests for forged history with an empty outbox, startup corruption,
  storage-write failure, interruption during record creation, and restore;
- signed-head truncation, append-only correction, and old-backup migration
  tests;
- service replay, conflicting idempotency, concurrent-verification,
  crash-before/after-RPC, stale-lease and exact-memo tests;
- accessibility checks for keyboard operation, names, focus, contrast and touch
  targets;
- a backup/restore drill on the actual supported browsers;
- deployment checks that secrets are not in command metadata or access logs.

A missing gate is a known limitation, not an implicit pass.
