# Submission — ECATHON (Wildcard track)

_Draft, 2026-10-25. This is the text the judges read. Every claim in it
points at something in the repo that runs; `docs/STATUS.md` is the honest
table, and this document is not allowed to outrun it._

## The pitch

Vickrey seals what you saw — a signed, hash-chained observation — and
anchors only a commitment, never the record. The public ledger version
still told the world _who_ sealed _what_, roughly _where_, and _when_:
the anchor was a message in a public tangle, readable by anyone.

This submission moves the anchor into Zcash's shielded pool. Each
observation is anchored by an unremarkable shielded transaction — a
constant-amount note burn whose nullifier makes replay a
double-spend that the node itself rejects — with batched, jittered
timing (30-minute floor, 20-minute uniform draw) so the block the
transaction lands in leaks as little as the chain can bear. The verifier
holds the commitment-to-transaction binding and serves it only to the
holder of a receipt id, one anchor at a time; there is no list endpoint,
so a recipient cannot enumerate the rest. (A disclosure _package_ endpoint,
which would hand a recipient the device's signature alongside the receipt,
and export of the viewing key are designed rather than built —
`docs/DISCLOSURE_DESIGN.md`.) Anyone can still run the one check that is
meaningful: "this transaction id exists at this height." The public chain
now proves _when_ a seal was made, without ever revealing _what_ was seen,
_where_, or _by whom_.

## What the chain shows, and what it can't show

One anchor, on a v6.20.0 chain (regtest in the demo; the service is
node-agnostic):

- A transaction: 0.001 ZEC, constant, one note spent, one note created.
- Its height, its block time, its fee.
- Nothing else. No memo in mode A (the commitment does not ride the
  chain at all — it stays with the verifier), no address pattern that
  identifies the program (dedicated anchor and verifier accounts,
  per-role keys, documented in `docs/PRIVACY.md`), no payload.

`docs/PRIVACY.md` names every leak that _does_ survive — including the
timing window the chain unavoidably stamps — and what was done about
each. The submission's privacy claim is the threat model, not the
absence of one.

Replay is not a service promise; it is a consensus rule. The D0 run
(`services/zanchor/spike/probe6.py`) resubmitted an anchored
transaction's own raw bytes and the node rejected it:
`bad-txns-orchard-duplicate-nullifier`.

## Run the demo

Everything below runs from this repo, no secrets needed:

1. **The full walk against a live node.** `scripts/demo_zcash.sh`
   against a running `services/zanchor` (a `zcashd` from
   `services/zanchor/docker/`, funded via
   `docker/fund_regtest.sh` on regtest) performs 33 contract checks and
   exits non-zero on any breach. All 33 pass against the live node.
2. **The real client, not the test.** `apps/field` with
   `?anchor=shielded&zanchor=<service>`: seal a sample walk, sync, and
   the outbox receipts confirm with real txids; the explorer
   (`apps/explorer?receipt=…`) shows the `SHIELDED · VERIFIED` panel
   after its proof-of-existence check. The tamper beat runs in the same
   mode: edit a queued copy and the seal cracks, sync refuses to send
   the edited entry, and putting the sealed copy back re-forms the seal.
   A tampered observation also has no anchor: its commitment is a
   different 32 bytes, and no receipt exists for it.
3. **Mock-only, anywhere, any machine.** `scripts/demo_zcash.sh` with
   no arguments spins up a contract-exact mock and the same checks; it
   says plainly that no chain was involved.

The demo chain is regtest: a private chain we mine, chosen because
zcashd 6.x's testnet sync thread does not start against the current
Zebra-dominated testnet (documented, reproducible, and why it matters is
in `docs/STATUS.md`). The code, the fee schedule (ZIP 317), and the
consensus behaviour verified in D0 are identical to mainnet; only the
blocks are ours.

## What is real, what is a stretch, what is a mock

| Thing                              | State                                                                                                                                               |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Shielded anchor (mode A)           | Built, verified end to end on a live node                                                                                                           |
| Replay protection                  | Node-enforced (nullifier); service 409 as defense in depth                                                                                          |
| Jittered anchor scheduling         | Built, 10 tests; 30 min floor / 20 min uniform                                                                                                      |
| Verifier receipts, no enumeration  | Built and pinned: `GET /receipts/{id}`, 404 for an unknown id, and `GET /receipts` is 404 — two contract tests plus the live `demo_zcash.sh` checks |
| Selective disclosure, viewing key  | Design only — `GET /receipts/{id}/disclosure` and `z_exportviewingkey` are not built (`docs/DISCLOSURE_DESIGN.md`)                                  |
| Memo mode (commitment in the memo) | Wired (`ZANCHOR_MODE=B`), verified on a live node: raw chain data shows ciphertext only, verifier decrypts the commitment                           |
| Field rewards (shielded payout)    | Design only — stretch, not claimed in the demo                                                                                                      |
| Mainnet node                       | Not running: testnet sync is stuck on zcashd 6.x (see above); the service is node-agnostic and the one-line change is in the docs                   |

## Originality (the rule and the receipt)

"All code written during the build window. Libraries are fine; existing
products are not." First commit in this repository: `ced42d0`,
2026-10-06 17:09 +0100, inside the Sep 28 – Oct 28 window. The first
weeks are milestone 1 (a public-ledger seal app, filed Oct 11); this
submission is the Zcash layer built on top, and the README says so in
plain terms: _milestone 1 proved the seal; ECATHON shields the anchor._

## Where things are

| Path                            | What it is                                                            |
| ------------------------------- | --------------------------------------------------------------------- |
| `services/zanchor/`             | The anchor service (FastAPI) + contract + tests                       |
| `services/zanchor/docker/`      | zcashd v6.20.0 source-build image, regtest/testnet launchers, funding |
| `services/zanchor/spike/`       | D0 GO/NO-GO probe with the replay-rejection evidence                  |
| `apps/field/`, `apps/explorer/` | The two clients; shielded mode + the VERIFIED panel                   |
| `docs/ZANCHOR_API.md`           | The pinned wire contract (both sides built against it)                |
| `docs/PRIVACY.md`               | The threat model: timing, replay, disclosure, keys, residuals         |
| `docs/STATUS.md`                | The one honest table                                                  |
| `scripts/demo_zcash.sh`         | The demo: mock by default, `--zanchor` for the live node              |
