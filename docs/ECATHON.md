# ECATHON — shield the anchor

**Zcash privacy hackathon. Submission due 2026-10-28 23:59 UTC.**
Track: **Wildcard** — "anything that makes a shielded transaction worth making."
One account registers and submits; we build with a small team.

## Why this submission, why this track

Vickrey's week-1 build proved the **seal**: an observation signed on-device,
hash-chained, and anchored as a _commitment_ (hash + signature + timestamp +
coarse area + species summary) — never the photo, notes, or precise GPS.

It left one leak. The anchor ledger is **public**: a stranger can correlate
`who anchored, what summary, which coarse area, at what time`. For a rare
species in a sensitive region, "who observed what, where, when" is a
correlation map even without the coordinates.

**ECATHON closes that gap:** the anchor moves into the **shielded pool**.
A shielded Zcash transaction exists precisely so that the _fact of a
transaction_ — who sent, who received, how much, and (with memos) what it
carries — is not readable from the chain. That is exactly the property a
sensitive field observation needs from its trust anchor. This is not
"Zcash for payments"; it makes a shielded transaction worth making for
**provenance**.

The Vickrey name is the pitch's spine: a sealed bid commits without
disclosing and cannot be changed after close. The sealed _observation_ does
the same — now against the chain itself.

## What was built in-window (and why we're eligible)

Rules: _"All code written during the build window. Libraries are fine;
existing products are not."_

- Build window: **Sep 28 – Oct 28, 2026**.
- First commit in this repo: **`ced42d0`, 2026-10-06 17:09 +0100** — inside
  the window. Every line of code in the repo was written Sep 28 onward;
  `git log --reverse --date=iso` proves it.
- The repo's first _weeks_ were milestone 1 (Hacktoberfest Week 1, filed
  Oct 11). That is foundation code laid early in the window, not an
  imported product. The **submission is the new Zcash layer**, with the
  existing field client, seal/journal, and commons as its load-bearing
  foundation — the same way a payment app on Zcash stands on the wallet SDK.
- The submission README states this split explicitly and honestly.

Positioning line: _"Milestone 1 proved the seal. ECATHON shields the anchor."_

## The design

### Anchor mode A — the shielded beacon (core, must ship)

1. The device seals the observation exactly as today: Ed25519 signature +
   hash chain → commitment `C = sha256(canonical body)`.
2. The anchor service holds an **anchor account** on Zcash. Anchoring
   observation `C` = making a **shielded transaction** from the anchor
   account. The tx is deliberately _unremarkable_: any small, constant
   amount to a destination account of the commons. On the chain it is
   indistinguishable from ordinary shielded activity.
3. **What the chain reveals: nothing.** No species, no area, no observer, no
   amount pattern (fixed amount), and the very existence of "this tx is an
   anchor" is unknown to anyone but the parties.
4. **What the verifier holds:** a receipt row binding `C ↔ txid + block
height`. Block height still gives public _time-ordering_ ("a
   transaction with this hash exists at height H" is checkable), while the
   _content and purpose_ of that transaction are not.
5. **Trust shift, stated openly in the docs:** public mode (current IOTA/Fly
   ledger) = anyone can verify the anchor. Shielded mode = the commons
   verifier holds the linkage and can vouch for it; selective disclosure is
   possible via the viewing key. This is a deliberate privacy trade-off, not
   a bug. Both modes ship; sensitive species/regions route to shielded.

### Anchor mode B — commitment in the encrypted memo (stretch)

Shielded txs carry an **encrypted memo** (recipient-side, decrypted with the
viewing key). Put `C` in the memo instead of the verifier's local binding:

- the commitment rides _inside_ the sealed transaction — no off-chain table
  can be lost or coerced away from the proof;
- **selective disclosure becomes a protocol primitive**: the verifier (or
  the observer, with their own viewing key) can reveal "this commitment was
  anchored at height H" to a researcher, court, or journal — and only to
  them. Nobody else can.

### Replay protection — nullifiers, used correctly

- **Mode A:** each anchor burns **one dedicated shielded note**, so its
  nullifier is unique per commitment. Replaying an anchor means spending the
  same note twice — a double-spend the node rejects. Non-replay is
  inherited from the protocol, not from our database.
- **Mode B (memo):** memos don't consume nullifiers, so replay protection
  additionally comes from the verifier rejecting a commitment already
  anchored. State exactly which guarantee comes from where — judges probe
  mechanism claims.

### Timing-leak mitigation (a leak is disqualifying — plan for it)

- **Batched, jittered anchoring:** anchors are sent on a randomized schedule
  (min delay after capture + jitter across the batch window), never
  immediately on "back in range". A shielded tx appearing seconds after an
  observation in the same region is a correlation.
- **Constant anchor amount** in both modes.
- **Separate keypairs** per role (anchor account, verifier account, per-
  observer reward accounts). Address reuse re-links everything the pool
  hid.

### Shielded field rewards (stretch, makes it "payments" too)

The commons pays a small **TAZ reward** for verified observations, to a
**per-observer shielded address**, memo = observation id (encrypted),
jittered timing. What this hides: which contributor was paid, how much, and
when — so the reward stream can't fingerprint who surveys what, where.

## Threat model (must exist as a doc at submission)

Judges score: _"Does it actually preserve privacy, or does it only look
like it? Leaks are disqualifying."_ `docs/PRIVACY.md` (or a section here)
will name each leak and its mitigation:

| Leak                       | Shape                                                    | Mitigation                                                                                                      |
| -------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Timing                     | anchor tx height ↔ observation time ↔ observer location  | batched + jittered schedule, min delay, documented interval                                                     |
| Amount                     | variable tx amounts fingerprint anchor events            | constant anchor amount; reward amounts small + jittered                                                         |
| Memo                       | commitment or obs id in an encrypted memo                | memo only in mode B, encrypted recipient-side; never re-published by the verifier                               |
| Address reuse              | anchor / verifier / reward accounts re-linked            | per-role keypairs, stated policy, no shared funding txs in the demo                                             |
| Verifier trust             | verifier holds C ↔ txid linkage and (mode B) viewing key | stated trust model; public mode retained for those who don't need shielding; future: multi-verify               |
| Off-chain commons          | the Fly ledger currently publishes commitments           | **shielded mode keeps commitments out of the public API entirely** — this is the concrete, demonstrable upgrade |
| Funding the anchor account | a transparent funding tx links the commons               | funded before the demo window; noted as operational hygiene                                                     |

## Build plan (Oct 25 → Oct 28 23:59 UTC)

**Cut line: mode A + threat model + demo ship. Modes B, rewards, and film
polish are stretch in that order of risk.**

### D0 — Fri Oct 25: spikes + GO/NO-GO — **GO (evening of the 25th)**

**Verdict:** zcashd **v6.20.0 regtest**, run via `services/zanchor/spike/probe6.py`:

1. Dedicated anchor account funded with shielded notes (`z_shieldcoinbase`) — shielded spends work.
2. Constant-amount `z_sendmany` (0.001 ZEC) with a 512-bit commitment **memo** mined: the transaction is one unremarkable shielded transfer — mode A safe, and **Orchard memos are consensus-active, so mode B is viable**.
3. The memo read back intact with `z_viewtransaction`.
4. Resubmitting the identical raw tx: node rejects with **`bad-txns-orchard-duplicate-nullifier`** — replay protection is a consensus rule, not a service promise.

Engineering notes from the run (all recorded in the probe): 6.x op-status
RPC takes `[[opid]]` and reports `status`; ZIP 317 fee rules apply
(2-action shielded tx = 0.0001 grace fee; fees > 4× conventional refused);
regtest coinbase pays a legacy keypool address that `z_shieldcoinbase`
consumes directly.

**Findings (day of the 25th, for the record):**

- No prebuilt `zcashd` binaries are published anywhere we can find
  (GitHub releases for v6.12.5/v6.20.0 carry no assets; the Docker Hub
  images are from 2020). **Source build is the path.**
- Current release: **v6.20.0** (NU6.2, June 2026 — Orchard circuit
  remediation). v6.12.5 notes mention "temporary disabling of Orchard
  actions" (GHSA-ghc3-g8w4-whf9); the v6.20.0 builder code fully supports
  memos, so whether on-chain memos are currently consensus-enabled is an
  **empirical question the spike answers**. Mode A (beacon) does not depend
  on it; mode B and memo-carried reward signalling do.
- Dev loop: `zcashd` built from source on nuncio-vultr (regtest — we
  mine, no funding dependency); `services/zanchor/spike/probe6.py` is the
  D0 gate and it ran to GO.
- **Demo chain: regtest on nuncio-vultr.** Mainnet cannot sync in the
  window on this hardware, and zcashd 6.x's testnet sync thread does not
  start against the current Zebra-dominated testnet (reproducible; init
  and peering complete, then nothing). Regtest is therefore the demo
  chain, documented as such in the submission. The service is
  node-agnostic — one RPC URL. (The image push to GHCR is blocked on a
  token-scope quirk; nothing depends on it.)

- Register the single submitting account; lock track = Wildcard.
- `docker-compose`: `zcashd` (mainnet, small real amounts — avoids testnet
  faucet flakiness; ~0.01 ZEC total is enough). **Start the node sync** —
  this is the long pole; image built from source on nuncio-vultr
  (`vickrey-zcashd:v6.20.0`, Dockerfile committed) and pending push to the
  registry for the Fly machine.
- Spike (throwaway script): create wallet + viewing key, send a note to the
  anchor account, and make **one shielded tx via RPC** (`z_sendmany` from a
  shielded source), then confirm we can read the tx back with the viewing
  key. **GO/NO-GO at end of day:** if shielded txs via RPC work, mode A is
  safe; if not, fall back to "transparent tx with no identifiable memo +
  verifier-side linkage" for the beacon and put shielded in mode B/rewards
  only — and re-scope the narrative to what actually runs.
- Decide note-burn mechanics concretely (one note per commitment: fund the
  anchor account with N notes, one per planned anchor).

### D1 — Sat Oct 26: `services/zanchor` core — **done, a day early**

Everything below landed Oct 25 and was verified against a live v6.20.0
node, not a mock:

- `POST /anchor` (202 + receipt), `GET /receipts/{id}`, `GET /chain/tx/{txid}`
  — exactly the pinned contract, plus the live-learned bits: one anchor in
  flight (503) because the wallet's shielded view lags the chain, a
  `failed` receipt state with retry-after-failure, and node HTTP-500
  tolerance (6.x answers degenerate inputs with bare 500s).
- **Mode A (beacon) and mode B (memo) both verified live.** Mode B's
  decisive check: the raw transaction carries only encrypted
  `outCiphertext`; the verifier's wallet decrypts the commitment.
- Note burn: dedicated anchor account, constant 0.001 ZEC, ZIP 317 grace
  fee 0.0001; funding via `z_shieldcoinbase` (regtest) documented in
  `docker/fund_regtest.sh`.
- 12 contract tests (mocked RPC) + `demo_zcash.sh` **33/33 against the
  live node**, including the 409 replay and the unknown-txid 404.
- 6.x migration recorded along the way: `z_getoperationstatus [[opid]]`,
  `status` field, `z_listshieldedreceivednotes` gone (note count from
  `z_getnotescount`), `gettransaction` height via `getblockheader`, and
  Python 3.12 urllib refusing `user:pass@` URLs (creds split into the
  Basic header).

**Wire format is pinned in [ZANCHOR_API.md](ZANCHOR_API.md)** — shapes,
status enum, error codes, and the deliberate absence of a receipts list
endpoint. Change the contract there first; the client codes against it.

### D2 — Sun Oct 27: integration + threat model + demo

**Client slice already landed (evening of Oct 25), ahead of D2:**

- **Field client shielded mode** — `?anchor=shielded` (or the config
  default) routes **only** `{commitment}` to `zanchorUrl`; no species, area,
  timestamp, signature, or key reaches any service edge. Public mode is
  byte-for-byte unchanged. Held entries stay queued rather than reordering
  the outbox, and "find similar" is disabled in shielded mode because a
  species query would leak the observation.
- **Batched/jittered scheduler** — `apps/field/schedule.js`: each
  commitment gets exactly one anchor time,
  `max(capture + 30 min, planned) + U(0, 20 min)`, persisted so a reload
  never re-rolls. The `planned` base spreads a dead-zone backlog instead of
  firing a burst on reconnect.
- **Explorer `SHIELDED · VERIFIED` panel** — `?receipt=…` renders the
  shielded card beside the public checklist: receipt binding, "what the
  public chain reveals" (every row Hidden), and a live proof-of-existence
  check. `VERIFIED` is claimed only when the receipt is confirmed **and**
  the chain check agrees.
- **Receipt truth in the contract and both clients** — `mode` and
  `shielded` are now part of every receipt. The `SHIELDED` stamp is derived
  from the service's answer, never from the routing: a node that refuses
  shielded spends yields `TRANSPARENT · …` and an Exposed-rows checklist
  instead of a false claim. This is the honesty gate the D0 spike may force.
- **`scripts/mock_zanchor.py` + `scripts/demo_zcash.sh`** — the mock speaks
  the contract; the demo runs the whole walk against it (health → anchor →
  409 replay → 400 bad body → settle → proof of existence → no leak → no list
  endpoint) and exits non-zero on any breach. `--zanchor URL` points the same
  checks at the real service, so D1's acceptance test is one command.
- 25 new JS tests (121 total). Written against the **mock** zanchor that
  implements the contract — and since Oct 25 the same walk has also run
  against the live stack in a real browser (seal → sync → confirmed
  receipts → tamper → restore → explorer `SHIELDED · VERIFIED`).

**Still D2, and still not mine to pre-build:** the service itself, the
`zcashd` compose entry, note burn, verifier receipts, and the D2 numbers in
`PRIVACY.md` that depend on them (replay protection among them).

_Updated evening of Oct 25 — all of the above landed; what remains of D2:
the demo video (parked by the lead, 2026-10-25) and the D3 full walk.
`docs/PRIVACY.md` is fully closed: replay answered by D0, verifier trust,
disclosure and keypair policy set the same day._

- **Rewards (stretch):** commons → per-observer shielded TAZ payout, memo =
  observation id, jittered. Design only — not claimed in the submission.
- **`docs/PRIVACY.md`**: timing section is written and complete; replay,
  verifier trust, disclosure and keypair policy stay **open** until the spike
  and the lead answer them.
- `scripts/demo_zcash.sh` against the **real** service, then the seal →
  anchor → block explorer → crack → receipt demo, recorded.

### D3 — Mon Oct 28 (deadline 23:59 UTC): harden + submit

- Full end-to-end run on the live node, recorded; demo video < 2 min
  (parked by the lead 2026-10-25; the walk itself is one browser session —
  sample walk → sync → receipts → tamper → restore → explorer VERIFIED).
- Submission text: drafted in [SUBMISSION.md](SUBMISSION.md); what is the
  Zcash submission vs. the in-window foundation, how to run it, honest
  status table.
- Commit before ~21:00 UTC, buffer for the submit click; keep editing
  rights until the deadline (we can fix post-commit bugs until 23:59).
- Repo is public on GitHub (sneldao/vickrey) and in sync as of Oct 25 —
  nothing in the submission lives only on a laptop.

## Team split (2 developers + you as lead)

Three people is doable but with three days and a shared RPC/node, **two
hands on the code is the sweet spot** — fewer merge conflicts, one GO/NO-GO.
Add a third only if the D0 spike is a clean GO.

| Person                                                       | Scope                                                                                                                                                        | Delivers                                                    |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| **Dev 1 — Zcash core** (comfortable with RPC/Python or Rust) | D0 spike, `zcashd` compose, `services/zanchor` (modes A + B), note-burn, verifier/receipts, integration test                                                 | The shielded anchor that actually settles on-chain          |
| **Dev 2 — client + story** (JS/TS)                           | field-client shielded mode, explorer `SHIELDED · VERIFIED` panel, scheduler, `demo_zcash.sh`, demo video, submission README                                  | The 90-second demo a judge can rerun                        |
| **You — lead**                                               | threat model (`docs/PRIVACY.md`), positioning, STATUS/STRATEGY/README, registration + submission, D0 GO/NO-GO, rewards design (delegate to Dev 1 as stretch) | The doc that answers "does it _actually_ preserve privacy?" |

If only one extra dev is available: Dev 1 does zanchor **and** rewards; you
take the demo script and video. The client `shielded` mode can be a small
ledger route rather than a field-client change if time slips.

## The pitch in one paragraph (for the submission)

> Vickrey seals what you saw — a signed, hash-chained observation — and
> anchors only a commitment, never the record. Milestone 1's anchor ledger
> still told the world _who_ sealed _what_, roughly _where_, and _when_.
> This submission moves the anchor into Zcash's shielded pool: each
> observation is anchored by an unremarkable shielded transaction — a
> constant-amount note burn whose unique nullifier makes replay a
> double-spend — with batched, jittered timing so the block itself leaks
> nothing. The verifier holds the commitment-to-transaction binding and can
> selectively disclose an anchor to a researcher via the viewing key, while
> anyone can still check that a transaction exists at a given height. The
> public chain now proves _when_ a seal was made, without ever revealing
> _what_, _where_, or _by whom_. Field rewards for verified observations
> pay out the same way: TAZ to a shielded address, encrypted memo, no
> fingerprint.

## Risks

| Risk                                                | Mitigation                                                                                                                                                                                |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Shielded tx via RPC proves finicky (D0 spike fails) | Fallback: transparent constant-amount beacon with verifier-side linkage + memo/privacy story carried by mode B and rewards; re-scope narrative to what runs. Never submit a broken claim. |
| `zcashd` sync slower than expected                  | Start tonight; testnet as fallback (faucet flakiness is the only cost); worst case, a hosted mainnet node + RPC                                                                           |
| "Repackaged" reading                                | Submission is the Zcash layer; foundation disclosed with git dates; narrative leads with the leak we close, not the week-1 app                                                            |
| Timing-leak we can't fully close                    | Batch + jitter + min delay + constant amount, and _document the residual honestly_ — a named residual beats a claimed total                                                               |
| Scope creep past the cut line                       | Cut line is law: mode A + threat model + demo. Stretch items only after D1 is merged and green                                                                                            |
