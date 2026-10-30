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

## What a shielded anchor puts on the chain (mode B, default)

One observation commitment becomes an encrypted memo in a shielded
transaction. The service sends a constant amount between its dedicated
accounts. Public chain data reveals transaction existence, block placement
and fees, but does not expose the observation or its device key.

Mode B is required for a commitment-verified result. A refused shielded
memo send fails closed: the service does not retry without a memo or send a
transparent transaction. Explicit legacy mode A sends a shielded beacon
without the commitment. Its database binding is a service assertion, and a
confirmed beacon does not prove when the observation existed.

## Timing (complete)

A shielded transaction appearing minutes after an observation, in a region
with one observer, is a correlation — the shield does not help if the timing
does the talking. The client-side schedule defaults to the delays below;
explicit demo query overrides can shorten them:

| Rule                          | Value                                                  | Where                 |
| ----------------------------- | ------------------------------------------------------ | --------------------- |
| Minimum delay from capture    | **30 minutes**                                         | `anchorMinDelayMs`    |
| Batch window (per-entry draw) | **20 minutes**, uniform                                | `anchorJitterMs`      |
| Anchor time                   | `max(observed_at + 30 min, first_seen) + U(0, 20 min)` | `schedule.js`         |
| Draws per commitment          | one, persisted, never re-rolled                        | `vickrey.anchor_plan` |
| Reconnect after a dead zone   | spreads from _now_, no burst                           | `planAnchors`         |

What that buys: under the default scheduler "sealed and immediately anchored"
does not happen — a batch of entries does not leave together, and a reload does
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
Resubmitting that exact transaction was rejected with
`bad-txns-orchard-duplicate-nullifier`. This establishes note-level
double-spend protection. Anchoring the same commitment with a different
note is a different operation: only the application's receipt database
prevents that duplicate, by returning `409`.

Two honest footnotes:

- **Nullifiers prevent spending the same note twice — nothing more.** The
  consensus rule stops a double-spend of the burned note; it says nothing
  about commitments. There is no per-commitment uniqueness at the protocol
  level: "this commitment is already anchored" is enforced by the service's
  receipt database (the `409`), under the service's lock. (The 6.12.5
  Orchard-circuit vulnerability that motivated the "temporarily disabled"
  flag in that release is fixed by NU6.2, which v6.20.0 activates, and the
  D0 run is the direct check.)
- **The service is fail-closed.** Earlier drafts allowed a transparent
  constant-amount fallback when the node refused shielded spends; that
  path is gone. A refused anchor is a 503 with nothing downgraded, in
  either mode — there is no transaction left whose "shielded" claim needs
  footnoting.

Also verified in the same run: **Orchard memos are consensus-active in
v6.20.0** — a memo written on the anchor's output was read back intact by
`z_viewtransaction`. Mode B (the commitment lives in the encrypted memo) is
wired (`ZANCHOR_MODE=B`, the default) and live-verified: the raw transaction —
the same bytes a public explorer sees — carries only the encrypted
`outCiphertext`, while the service wallet's view decrypts the commitment.
A mode-B anchor is indistinguishable from any other memo-bearing shielded
transfer. Mode A (note-burn beacon) survives as an explicit legacy mode;
its receipts never carry a memo proof — the binding is verifier-held only.

## Selective disclosure (policy set 2026-10-25)

The verifier holds `commitment ↔ txid ↔ height` and reads mode-B memos with
its own wallet (`z_viewtransaction`). A receipt id is a bearer capability:
any holder can request its verification or disclosure. The endpoint requires
a purpose, checks the memo, and appends an audit row; it does not authenticate
the recipient or enforce the stated purpose. There is no list endpoint and
no viewing-key export. A recipient can copy a downloaded file; the app cannot
revoke it.

- **Who holds the key:** wallet keys live in the zcashd wallet the service
  talks to; the service process holds only the RPC credentials, in its
  environment. The receipt database stores no key material or memo contents,
  and no endpoint exports viewing or spending keys. Mode B memos are read
  through the wallet's own view (`z_viewtransaction`), used, and dropped.
- **What is logged when a receipt is disclosed:** an append-only audit row
  in the service's SQLite store — receipt id, UTC timestamp, and the
  caller-supplied purpose string. A disclosure serves whoever presents the
  receipt id: it is a bearer capability, so the audit names a stated purpose,
  not a verified recipient. The audit table is not exposed by any endpoint.
  A downloaded disclosure file cannot be revoked cryptographically.
- **What a recipient is told about the rest of the corpus:** exactly one fact
  per disclosure — that this commitment was anchored at this height and time.
  The existence of other anchors, of the corpus, or of the observing program
  is not revealed through the API. A recipient who holds one receipt has no
  route to enumerate the others — but the operator still sees every id.

## Verifier trust (policy set 2026-10-25)

Shielding moves the linkage from the chain to the verifier. That is the real
trade: the chain no longer knows what the transaction is, and the verifier
does. What it must never do — publish receipts, enumerate anchors, answer
"what was anchored this week" — is limited by the API shape (no list
endpoint, receipts served only by id) but not prevented: the operator can
always read its own receipt database, and receipt ids in Uvicorn or proxy
logs are bearer capabilities in plain text. Trust in the operator's logging
and DB hygiene is part of the model, stated rather than assumed.

- **Who operates it:** the project (sneldao) operates the verifier for the
  hackathon demo and the initial commons. It is one FastAPI process in front
  of one zcashd wallet, same trust domain as the existing Vickrey ledger.
- **What it stores:** the receipt table (commitment, txid, height, status,
  mode, shielded), capability metadata, and the append-only disclosure_audit
  rows (receipt id, UTC timestamp, purpose). It never receives a
  species, an area, a timestamp, a signature, or a public key — the wire body
  is the 64-hex commitment and nothing else (`docs/ZANCHOR_API.md`).
- **What happens to receipts when the demo ends:** the demo receipt database
  is kept as a demo artifact of the submission (it is small and contains no
  observation data); a production commons would define and publish its own
  retention policy before taking real traffic. Both statements go in the
  submission README.

## What the demo may say

| Run                             | May say                                                                    | Must also say                                                     |
| ------------------------------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `scripts/demo_zcash.sh` (mock)  | the client and explorer handle a receipt end to end                        | no chain, no shielded pool, no transaction                        |
| same script, `--zanchor <real>` | a transaction exists at height H and reveals nothing about the observation | who operates the verifier, and that timing is bounded, not hidden |
| `--transparent`                 | what the chain shows: a constant-amount transfer                           | the transaction is public; only the observation stays hidden      |

`scripts/demo_zcash.sh` prints the mock banner itself and refuses to let a
contract breach pass silently, so the demo cannot drift into claiming more than
it ran.

## Keys, accounts and backup limits (updated 2026-10-30)

The device key signs observations and stays in browser storage; encrypted
backup includes it. The Zcash anchor and recipient accounts live in the
node's wallet. RPC credentials stay server-side. Sending between those
accounts is how anchors are created; shielding does not remove timing,
funding or service-side linkage risks. No viewing or spending keys are
included in disclosure files.

The encrypted backup module covers the five `vickrey.*` localStorage keys
with AES-256-GCM under a user passphrase (PBKDF2-SHA256, 600k iterations,
fixed). Restore is empty-device only, validates the journal chain before
writing, and rolls back on failure. It is not a production-grade secret
store: localStorage and any passphrase typed into a page inherit the
page's XSS exposure.
