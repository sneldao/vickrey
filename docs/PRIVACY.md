# Privacy and threat model

The honest leak list. This document exists so the project cannot claim more
secrecy than it has: every row names what leaks, what was done about it, and
what is still true afterwards.

**Ownership.** The timing section is complete and matches
`apps/field/schedule.js` and `apps/field/config.js`. The sections marked
**open** need the lead: they depend on how the verifier is operated, not on
client code, and the numbers in them are policy decisions.

**What is built.** The client half (schedule, commitment-only wire body,
receipt-aware explorer) and `services/zanchor` (the service that makes the
transaction) are built and contract-tested, and the chain-level claims below
are backed by the D0 run on zcashd v6.20.0 (regtest): a constant-amount
shielded anchor with a memo was mined and read back, and a resubmitted
copy of the same transaction was rejected by the node. `STATUS.md` is the
authority on what actually runs.

## What a shielded anchor puts on the chain (mode A, target)

One observation commitment becomes one deliberately unremarkable shielded
transaction: constant amount, no memo, one dedicated note burned per
commitment. A block explorer shows a transaction at a height and nothing that
relates it to a species, an area, an observer, or a purpose.

`mode` and `shielded` are separate on purpose (`docs/ZANCHOR_API.md`). Mode A
is _supposed_ to be shielded; if the node refuses shielded spends, the service
falls back to a **transparent** constant-amount beacon and must report
`shielded: false`. The clients then stop saying "shielded" and say what is
true instead. Pretending otherwise would be the one failure this project could
not recover from.

## Timing (complete)

A shielded transaction appearing minutes after an observation, in a region
with one observer, is a correlation — the shield does not help if the timing
does the talking. The schedule is client-side and has no exception:

| Rule                          | Value                                                  | Where                 |
| ----------------------------- | ------------------------------------------------------ | --------------------- |
| Minimum delay from capture    | **30 minutes**                                         | `anchorMinDelayMs`    |
| Batch window (per-entry draw) | **20 minutes**, uniform                                | `anchorJitterMs`      |
| Anchor time                   | `max(observed_at + 30 min, first_seen) + U(0, 20 min)` | `schedule.js`         |
| Draws per commitment          | one, persisted, never re-rolled                        | `vickrey.anchor_plan` |
| Reconnect after a dead zone   | spreads from _now_, no burst                           | `planAnchors`         |

What that buys: "sealed and immediately anchored" is impossible by
construction, a batch of entries does not leave together, and a reload does
not reshuffle a deadline into a suspicious one.

What it does **not** buy — stated plainly:

1. **The window is the leak.** An anchor leaves between 30 and 50 minutes after
   capture. An observer who knows an observation happened in that region can
   still narrow it to that window. The jitter raises the cost of correlation;
   it does not remove it.
2. **The block time re-narrows it.** The chain timestamps the transaction, so
   the window is bounded by the block, not only by the schedule.
3. **The service sees arrival.** `zanchor` sees a commitment and the moment it
   arrived, even though nothing in the body identifies the observation. The
   schedule is what keeps arrival away from capture time.
4. **Volume correlates.** An area with one field device produces one anchor a
   day; an area with fifty produces fifty. Timing mitigation helps the second
   case far more than the first.
5. **The demo shrinks the numbers.** `?minDelay=…&jitter=…` exists so a
   two-minute video is watchable. Any run with those overrides must say so
   aloud; quoting the demo's numbers as the design would be the same lie in
   the other direction.

## Replay protection (answered by D0, 2026-10-25, zcashd v6.20.0 regtest)

Shielded spends work: the D0 run funded a dedicated anchor account, burned
one note in a constant-amount `z_sendmany` (0.001 ZEC), and the node mined it.
Replaying the anchor therefore means double-spending that note, and the node
enforces it at consensus: resubmitting the identical raw transaction is
rejected with `bad-txns-orchard-duplicate-nullifier`. The service's `409` on
a known commitment is defense in depth on top of that, not the mechanism.

Two honest footnotes:

- **The transparent fallback has no nullifier.** If a node ever refuses
  shielded spends, the fallback beacon is a transparent constant-amount
  transfer and the `409` is the only replay protection — verifier-side trust,
  not a chain guarantee. The fallback reports `shielded: false` so no one can
  miss that. (The 6.12.5 Orchard-circuit vulnerability that motivated the
  "temporarily disabled" flag in that release is fixed by NU6.2, which
  v6.20.0 activates, and the D0 run is the direct check.)
- **Replay protection is per-note, not per-commitment, on the chain side.**
  The chain knows the spent note cannot be spent again; it does not know what
  a commitment is. The commitment↔txid binding that makes "this exact anchor
  is already anchored" checkable lives in the verifier. Both facts are true
  at once; neither weakens the other.

Also verified in the same run: **Orchard memos are consensus-active in
v6.20.0** — a 512-bit memo written on the anchor's output was read back
intact by `z_viewtransaction`. Mode B (the commitment lives in the memo) is
wired (`ZANCHOR_MODE=B`) and live-verified: the raw transaction — the same
bytes a public explorer sees — carries only the encrypted `outCiphertext`,
while the verifier's wallet view decrypts the commitment. A mode-B anchor
is indistinguishable from any other memo-bearing shielded transfer, and a
node that refuses memos falls back to mode A, with the receipt saying
which mode actually ran.

## Selective disclosure (policy set 2026-10-25)

The verifier holds `commitment ↔ txid ↔ height` and, in mode B, a viewing key.
Disclosure is one anchor at a time, to a named recipient (researcher, court),
and to nobody else — the receipt endpoint answers only for a receipt id and
there is no list endpoint.

- **Who holds the key:** the verifier operator, in the verifier process
  environment only; the receipt database never stores the viewing key or any
  memo contents. Mode B memo bytes are decrypted in memory, used, and dropped.
- **What is logged when a receipt is disclosed:** an append-only local audit
  line — receipt id, UTC timestamp, and the operator-supplied purpose string.
  No recipient identity is stored by the service; the operator's own records
  are the operator's policy. The audit log is not exposed by any endpoint.
- **What a recipient is told about the rest of the corpus:** exactly one fact
  per disclosure — that this commitment was anchored at this height and time.
  The existence of other anchors, of the corpus, or of the observing program
  is not revealed. A recipient who holds one receipt cannot enumerate any
  others.

## Verifier trust (policy set 2026-10-25)

Shielding moves the linkage from the chain to the verifier. That is the real
trade: the chain no longer knows what the transaction is, and the verifier
does. What it must never do: publish receipts, enumerate anchors, or answer
"what was anchored this week" — and the service enforces the first two by
construction (no list endpoint, receipts served only by id).

- **Who operates it:** the project (sneldao) operates the verifier for the
  hackathon demo and the initial commons. It is one FastAPI process in front
  of one zcashd wallet, same trust domain as the existing Vickrey ledger.
- **What it stores:** the receipt table (commitment, txid, height, status,
  mode, shielded) and a two-entry capability cache. It never receives a
  species, an area, a timestamp, a signature, or a public key — the wire body
  is the 64-hex commitment and nothing else (`docs/ZANCHOR_API.md`).
- **What happens to receipts when the demo ends:** the demo receipt database
  is kept as a demo artifact of the submission (it is small and contains no
  observation data); a production commons would define and publish its own
  retention policy before taking real traffic. Both statements go in the
  submission README.

## Keypair policy (policy set 2026-10-25)

Device keys sign observations and stay on the device; an anchor carries no
signature and no public key, so the chain cannot link two anchors of the same
observer. The verifier's Zcash keypairs follow the same rule as the chain-side
policy: per-role, never reused.

- **Observer device:** one Ed25519 keypair per device, generated on-device,
  never transmitted. Anchors carry no key material, so device key reuse is
  invisible on-chain; off-chain, the sealed record binds observation to
  device.
- **Anchor account:** a dedicated Zcash account that only burns anchor notes;
  it is funded in a single transparent transaction _before_ the observation
  window opens, and is never funded again mid-window (a funding tx during the
  window would be a timing marker).
- **Verifier account:** a separate receiving account, separate from the
  anchor account. Anchor, verifier, and any future reward accounts are
  distinct keypairs; cross-account transfers are how a pool's privacy is
  actually spent, and we do not do them.
- **Rotation:** there is nothing to rotate on-chain — the anchor account's
  notes are its only state and are consumed, not reused. A compromised or
  burned-out anchor account is replaced by funding a fresh one; old receipts
  remain valid because they bind to txids, not to the account.

## What the demo may say

| Run                             | May say                                                                    | Must also say                                                     |
| ------------------------------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `scripts/demo_zcash.sh` (mock)  | the client and explorer handle a receipt end to end                        | no chain, no shielded pool, no transaction                        |
| same script, `--zanchor <real>` | a transaction exists at height H and reveals nothing about the observation | who operates the verifier, and that timing is bounded, not hidden |
| `--transparent`                 | what the chain shows: a constant-amount transfer                           | the transaction is public; only the observation stays hidden      |

`scripts/demo_zcash.sh` prints the mock banner itself and refuses to let a
contract breach pass silently, so the demo cannot drift into claiming more than
it ran.
