# Reality Receipts — product direction and demo slice

_Status: release-candidate checkpoint, 2026-11-24. A local/demo implementation
of the claim → remote check → field task → signed verdict → simulated settlement
loop now exists in `services/receipts` and `apps/receipts`. It is not deployed,
and its independent review remediation is still in progress. QIE wallets,
identity, escrow, mainnet settlement and live remote-evidence providers remain
proposed. [STATUS.md](STATUS.md) is authoritative for what is built, verified
and deployed._

## Implementation checkpoint

The demo slice is deliberately narrower than the product direction:

- FastAPI + SQLite enforce role-scoped bearer credentials, idempotency, immutable
  submissions, signed Ed25519 verdicts and fixed-window quotas.
- The remote-evidence adapter is deterministic synthetic context. It can return
  likely, unlikely, insufficient or unavailable, but it is not a live evidence
  provider and never proves truth.
- Observers submit a commitment plus bounded public metadata. The independent
  privacy review has identified contract gaps that must be fixed before this is
  treated as acceptable for public use.
- Settlement is a deterministic testnet simulator. It moves no real funds and
  creates no chain transaction.
- The browser source provides a single-claim workflow and public receipt
  lookup/share view, but same-origin hosting, deployment and browser integration
  are still pending.

This is enough to exercise the workflow and review its trust boundaries. It is
not a production marketplace, a QIE integration or a public claim of accuracy.

## One line

**Vickrey is the fact-checker that can leave the internet.**

A user or agent posts a claim about the physical world. Vickrey first checks
what remote evidence can establish. If the claim still cannot be resolved, the
agent funds a bounded field task and pays for a sealed ground-truth record.
The outcome is a public, shareable receipt.

The consumer-facing packaging is **Reality Receipts**: post a claim, get
receipts. The technical product remains Vickrey's sealed field record and
selective-disclosure layer underneath.

## Why this shape

A general evidence marketplace has a cold-start problem: sponsors, observers,
and verifiers all have to arrive together. The Reality Receipts shape avoids
that by making Vickrey the first sponsor and first verifier. A challenge can
run with one observer because the product itself creates the task, applies the
rubric, pays the bounty, and publishes the result.

Birdwatching remains the proving ground because it exercises the mechanism
cleanly: a bounded observation, a sensitive location, a signed record, and a
verifier that can accept or reject the evidence. The company is the
verification loop, not the bird app.

## The loop

```text
claim or challenge
  -> evidence brief
  -> remote-evidence check
  -> if unresolved, bounded field task
  -> sealed Vickrey record
  -> verifier decision
  -> simulated payout + public receipt (demo)
  -> QIE payout + public receipt (proposed)
```

The first version should use safe, public challenges where a disclosed field
record does not create a privacy or safety problem. Sensitive observations can
continue to use the existing private/disclosure path without a public bounty.

## The agent services

The workflow is agentic even though the evidence source may be human:

- **Claim agent** — turns casual language into a bounded evidence brief:
  what must be observed, where, by when, and what would count against it.
- **Remote-evidence agent** — checks applicable public context such as maps,
  weather, sensors, web results, or satellite/aerial imagery where the claim
  is actually answerable at that resolution.
- **Dispatch agent** — creates a bounded field task only when remote evidence
  is insufficient. The task carries a location radius, evidence requirements,
  expiry, and a fixed bounty.
- **Review agent** — applies the evidence rubric and returns accepted,
  rejected, needs-another-witness, or cannot-determine. It does not decide
  truth without an explicit policy.
- **Settlement agent** — releases the QIE payout and writes the receipt.
- **Receipt agent** — renders the result as a shareable proof card.

The human observer is not a marketplace category the product depends on for
every answer. They are the premium evidence source the agent calls when the
internet and remote data cannot resolve the claim.

## Remote evidence is not the product

Satellite and public data are first-pass evidence, not truth. They can help
with floods, fire scars, vegetation, construction, snow cover, and other
large-scale conditions. They will not reliably prove a bird was present, a
sign was posted, a shop is open, or a small object exists today.

Keep the receipt honest by showing separate states:

- `remote_evidence: likely | unlikely | insufficient | unavailable`
- `field_evidence: sealed_record | none | challenged`
- `verdict: accepted | rejected | needs_witness | cannot_determine`

A remote check may lower the need for a field task; it must not silently
replace a sealed field record.

## What QIE would do

The proposed QIE slice is meaningful because it controls money and public
settlement, not because it stores a hash:

- **QIE Wallet** identifies sponsors and observers.
- **QIE ID** can carry verifier identity or observer reputation later.
- **A challenge contract** escrows the bounty and records the criteria hash.
- **A submission transaction** records the sealed-record commitment hash.
- **A resolution transaction** records the verifier decision and releases or
  refunds escrow.
- **A public receipt** links the challenge, commitment, verdict, and payout
  without publishing the raw record.

The current Zcash anchor and manual disclosure design are not replaced by
this. They are the private evidence path. QIE is proposed for public,
safe-challenge settlement and receipts; sensitive observations need a separate
policy before being attached to public payouts.

## QIE fit

Primary track: **AI + Autonomous Agents**. The product is an agent that
resolves physical-world uncertainty, dispatches human ground truth when
remote evidence is insufficient, and settles the result. Secondary fit:
**Commerce & Real World**, because the agent is paying for a real-world
evidence service.

The hackathon version must be net-new work, not a port label. The defensible
QIE slice is the claim/brief workflow, remote-evidence adapter, field-task
contract, verifier surface, QIE wallet/payment integration, mainnet receipt,
and share card. The existing field-record primitive is baseline and should be
disclosed as such.

## Proposed contracts

Keep the contract surface boring:

```text
createChallenge(challengeId, criteriaHash, expiry) payable
submitEvidence(challengeId, submissionId, commitmentHash, observer)
resolve(submissionId, verdict, proofHash)
refund(challengeId)
```

The contract enforces funding, expiry, one resolution, and payout binding. It
does not decide whether the evidence is true; the verifier's signed verdict
and the disclosed evidence policy do that.

## Payout and abuse constraints

Public QIE payouts are different from the unresolved private TAZ reward
design. Do not promise payout privacy on QIE: a public challenge transaction
can already reveal the task, timing, observer address, and resolution.

Before implementation, decide:

- who prefunds each challenge escrow
- whether payout is fixed or ranked
- whether payout releases immediately or after a review window
- how duplicate submissions, copied evidence, and colluding wallets are
  rejected
- whether observer reputation starts with QIE ID, an allowlist, or a small
  bond
- which challenge categories are safe enough for public settlement

The first MVP should use small fixed bounties, bounded public tasks, one
resolution per submission, and a verifier review step. Private rewards and
sensitive-location bounties remain out of scope until their own timing and
anti-farming policies are designed.

## The first product surface

Do not lead with sponsor dashboards or marketplace categories. Build a single
claim screen:

1. Post or pick a claim.
2. Watch the agent produce an evidence brief.
3. See remote evidence and a confidence state.
4. If unresolved, watch the agent post a simulated bounty in the demo; QIE funding is proposed.
5. A field submission arrives and is checked.
6. The agent pays or refuses.
7. A shareable receipt is published.

The demo story should be visual: “the agent thought it knew, then paid a
human to prove it.”

## Packaging signal

A small Monid/TikTok keyword sample on 2026-11-23 supports the packaging
choice: technical labels are weak while challenge, outdoors, and reality-check
frames are stronger. Directional top results included `nature is healing`
(~36M views), `touched grass` (~25M), `urban exploration` (~12M), `reality
check` (~9.8M), `prove me wrong` (~7.2M), `satellite imagery` (~5.8M),
`birdwatching` (~4.2M), `scavenger hunt` (~3M), `receipts or it didn't
happen` (~0.8M), and `citizen science` (~0.24M). This is positioning signal,
not market research by itself.

## Viral mechanics

The share object is not a hash. It is a story:

- **Agent vs reality** — “the model thought the lake was frozen; a field
  observer proved it was not.”
- **Paid proof reveals** — “an AI paid a stranger to walk outside and check.”
- **Daily Drop** — one safe, local, funded reality check each day.
- **Creator challenges** — a creator posts “prove me wrong” and Vickrey
  returns a receipt.
- **Before/after evidence** — remote guess beside the sealed ground-truth
  result.

Good challenge types are public, safe, and bounded: trail conditions, public
art, posted notices, event installations, seasonal nature sightings, public
equipment status, and visibly countable outputs. Do not make people,
interiors, minors, or unsafe locations the subject of challenges.

## Traction metrics

For a hackathon or pilot, measure the loop rather than claiming adoption:

- claims resolved remotely
- field bounties funded
- unique observer wallets
- accepted vs rejected submissions
- QIE payout volume
- median time from claim to verdict
- receipt cards generated and shared
- repeat claimants or challenge creators
- cost per verified claim

A successful first campaign is small: one funded challenge per day, several
real field submissions, at least one accepted payout and one honest rejection.

## Claim boundary

Vickrey must not call itself a truth oracle.

A sealed record proves that bytes were signed under a device key and that the
same bytes still recompute to the committed hash. An anchor proves existence
by a block on the configured chain. A verifier applies a policy and may still
be wrong. Remote evidence is contextual, not cryptographic. Raw sensitive
records stay off-chain; selective disclosure remains owner-controlled.

The product claim is narrower and stronger:

> Vickrey makes the evidence path auditable: what was claimed, what was
> checked remotely, what field record was committed, who verified it under
> which rules, and what was paid.

## Relationship to existing docs

- [STATUS.md](STATUS.md) — authoritative build state.
- [STRATEGY.md](STRATEGY.md) — the durable product reasoning and history.
- [BRAND.md](BRAND.md) — Vickrey's sealed-bid metaphor and public packaging.
- [DISCLOSURE_DESIGN.md](DISCLOSURE_DESIGN.md) — the implemented owner-controlled
  disclosure bundle and its limits.
- [PRIVACY.md](PRIVACY.md) — what the existing shielded anchor leaks and does
  not leak.
- [SHIELDED_REWARDS_DESIGN.md](SHIELDED_REWARDS_DESIGN.md) — unresolved private
  reward design; QIE bounty payouts are a different, public settlement model.
