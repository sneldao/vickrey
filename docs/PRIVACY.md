# Privacy and threat model

The honest leak list. This document exists so the project cannot claim more
secrecy than it has: every row names what leaks, what was done about it, and
what is still true afterwards.

**Ownership.** The timing section is complete and matches
`apps/field/schedule.js` and `apps/field/config.js`. The sections marked
**open** need the lead: they depend on how the verifier is operated, not on
client code, and the numbers in them are policy decisions.

**What is built.** Only the client half is built: the schedule, the
commitment-only wire body, and the receipt-aware explorer. `services/zanchor`
(the service that makes the transaction) is **not** built. So nothing below is
evidence about a chain — it is the design the client already enforces plus the
leaks that will remain once the service exists. `STATUS.md` is the authority on
what actually runs.

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

## Replay protection (open — depends on the D0 spike)

Two cases, and which one applies is not yet known:

- **If shielded spends work:** mode A burns one dedicated note per commitment.
  Replaying the anchor means double-spending that note, which the node rejects.
  The service's `409` on a known commitment is defense in depth.
- **If the node refuses shielded spends** (Orchard actions disabled in some
  releases): there is no note and no nullifier to burn. The `409` is then the
  **only** replay protection, and it is verifier-side — trust in the verifier's
  database, not a chain guarantee.

Write this section only after the spike answers it. Do not let "unique
nullifier" appear in the submission unless a test shows the node rejecting a
replayed anchor.

## Selective disclosure (open)

The verifier holds `commitment ↔ txid ↔ height` and, in mode B, a viewing key.
Disclosure is one anchor at a time, to a named recipient (researcher, court),
and to nobody else — the receipt endpoint answers only for a receipt id and
there is no list endpoint. Open questions for the lead: who holds the key, what
is logged when a receipt is disclosed, and what a recipient is told about the
rest of the corpus.

## Verifier trust (open)

Shielding moves the linkage from the chain to the verifier. That is the real
trade: the chain no longer knows what the transaction is, and the verifier
does. What it must never do: publish receipts, enumerate anchors, or answer
"what was anchored this week". What has to be stated for judging: who operates
it, what it stores, and what happens to receipts when the demo ends.

## Keypair policy (open)

Device keys sign observations and stay on the device; an anchor carries no
signature and no public key, so the chain cannot link two anchors of the same
observer. Open for the lead: whether the same key is reused across devices or
trips, and what a key rotation looks like.

## What the demo may say

| Run                             | May say                                                                    | Must also say                                                     |
| ------------------------------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `scripts/demo_zcash.sh` (mock)  | the client and explorer handle a receipt end to end                        | no chain, no shielded pool, no transaction                        |
| same script, `--zanchor <real>` | a transaction exists at height H and reveals nothing about the observation | who operates the verifier, and that timing is bounded, not hidden |
| `--transparent`                 | what the chain shows: a constant-amount transfer                           | the transaction is public; only the observation stays hidden      |

`scripts/demo_zcash.sh` prints the mock banner itself and refuses to let a
contract breach pass silently, so the demo cannot drift into claiming more than
it ran.
