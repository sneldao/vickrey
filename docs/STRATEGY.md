# Strategy — Vickrey: A sealed bid on what you saw

> _Current as of 2026-10-30: [STATUS.md](STATUS.md) is the live status table, [DEPLOY_DEMO.md](DEPLOY_DEMO.md) the prepared private deployment, and [DISCLOSURE_DESIGN.md](DISCLOSURE_DESIGN.md) the implemented disclosure contract. Public-ledger sections below are the legacy path._

**One line:** Identify it offline. Prove it later.

**Milestone 1 (done): Hacktoberfest 2026 — Week 1: Touch Grass.** An
offline, open-weight field identifier with a tamper-evident ecological
logbook — submitted October 11, 2026. The entry period and the record of
what was filed live in [`BUILD.md`](BUILD.md) and [`archive/`](archive/).

**Milestone 2 (current): ECATHON — a Zcash privacy hackathon.** Submission
due **October 28, 2026, 23:59 UTC**. The target is the privacy gap the Week
1 build left open: our public anchor ledger still reveals _who_ sealed _what_
_where_ _when_ — a correlation map, not a poaching map, but a map nonetheless.
ECATHON is where the anchor moves into the shielded pool. Full plan in
[`ECATHON.md`](ECATHON.md).

**Status:** the single honest table is [`STATUS.md`](STATUS.md) — this document
is the plan and the reasoning, not a live-state report. The seal → verify →
anchor → crack loop is Live; the on-device model that opens the vision is Not
built; the ledger anchors to embedded/mock Hornet, not a public tangle. Read
STATUS.md before borrowing any claim from below.

## The re-frame: outcome first, domain second

The primitive is not "a trail app." It is **tamper-evident record
reconciliation**: an app keeps a copy, a ledger keeps an independent copy, and
Vickrey proves they still agree. Any outsider can parse that in one sentence —
_"someone changed the record, and nobody noticed."_ The outdoor domain is the
warmth; the mechanism is the hook.

```
offline AI ID  →  signed observation  →  hash chain  →  ledger anchor  →  open commons
```

## Name and narrative

**Vickrey** comes from William Vickrey's **sealed-bid auction** — mechanism design
that makes truth the winning strategy. The seal is not a design choice; it is the
name's origin, and it drives the whole visual system. A sealed bid commits without
disclosing, and cannot be changed after close — exactly the commitment property our
anchor relies on. Full system in [`BRAND.md`](BRAND.md).

Voice: _"Vickrey proved that a sealed bid makes people honest. We just asked the
same of a memory."_

## Why open-source AI is the core (not decoration)

The prompt requires the open pieces to be what makes the project work. Here they
are load-bearing:

- **Runs with no signal.** A local open-weight model is the only way to identify
  a species on a trail. A hosted API simply cannot answer offline.
- **Data stays with you.** That is the on-device design goal; the verified
  server-hosted Gemma test sent its photo to our server for inference.
- **Costs nothing per call.** Thousands of observations, zero inference bill.
- **Swappable and inspectable.** BirdNET for audio, a small Gemma VLM for
  photos; the trust layer does not care which model ran.

If the model were a closed API, the entire off-screen premise collapses.

## Architecture

```
                 (on device, offline)                     (back in range)
see it → open-weight model → sign + hash-chain → local log → Messages API
                                                                    │
                                                                    ▼
                                                          Hornet block + milestone
                                                                    │
                          anchor commitment (hash + sig + ts + coarse loc + summary)
                                                                    │
                                                                    ▼
                                              commons API + explorer (services/ledger,
                                                                       planned open commons)
```

Three layers, one job each:

| Layer    | Runs            | Job                                                             |
| -------- | --------------- | --------------------------------------------------------------- |
| Identify | On device       | Open-weight model names the observation offline                 |
| Prove    | On device       | Signature + hash chain make edits detectable                    |
| Share    | Server + ledger | Anchor the commitment; (planned) export Darwin Core to research |

### A fourth, deliberately outside the record

Web context (Tavily) answers a question the loop otherwise leaves open: is this
species expected here, and when did others last report it? It is shown **beside**
an anchored record, never inside it.

This is a boundary, not an oversight. The seal is the observer's own
observation; a third party's answer, fetched later, cannot be part of a
commitment someone is expected to reproduce. Feeding search results into the
review step would be worse — it would let unverified content shape a decision
about to be cryptographically sealed. So a Tavily outage, a quota error or a
missing key degrades to a line of text and can never move a status off
`VERIFIED`.

### Hosting shapes

The three shapes — three-process faithful demo, single-process embedded (what
Fly runs), and real independent Hornet — are documented with their deploy
constraints in [`OPS.md`](OPS.md#hosting-shapes). The strategy point is the
middle one: embedded mode keeps the two-source check at the **data** layer
(application copy in SQLite, block in a separate structure) but gives up the
guarantee that a _different process_ holds the block, so the ledger publishes
`independent_source: false` rather than hiding it.

## The anchoring rule

**Anchor commitments, not observations.** On-chain: the commitment hash
(`sha256` of the canonical committed body), device signature, `observed_at`,
coarse/obscured location, `model_id`, a species/kind summary, schema version.
Off-chain: raw payload, precise location, media, observer identity.

This is the single design decision that makes the ecological story responsible
and defensible.

### Why not raw data on-chain

- **Endangered species.** An immutable public ledger of exact GPS for a rare
  species is a poaching map. Publishing an anchor reveals at most a coarse
  location and a species summary; precise location stays private or delayed.
- **Retraction.** Science needs to correct wrong IDs. Immutability is a _bug_ for
  data hygiene. Anchoring hashes lets you delete/repair off-chain while the
  anchor preserves proof of the record's early state. Model a `superseded_by`
  link for corrections.
- **Interop.** Raw ledger blobs are useless to researchers. The wrapper is the
  ledger; the planned payload export is Darwin Core (not yet implemented).

**Integrity ≠ accuracy.** The ledger proves a record was not altered after
anchoring. It does not prove the ID was correct, nor that the observation was
honest. Say this out loud in the pitch — it is the honest ceiling of the design.

## Ecological externalities (why a public ledger earns its place)

Versus other entries (a model, and nothing else), the ledger unlocks:

- **Citable, tamper-evident research data.** A paper can point at an observation
  set that provably was not edited after the fact.
- **Provenance and attribution.** The observer holds a permanent, timestamped
  record of their contribution — a reason to contribute.
- **An open commons, not a platform silo.** Permissionless, any researcher can
  verify, no gatekeeper.
- **Anti-fraud / lineage.** Hash chains let aggregators flag records altered
  after anchoring; supports dedup and quality scoring across organisations.
- **Cross-institution trust without a middleman.** Two labs compare datasets
  against the same anchor.

## Competitors

- **Bird-ID apps** identify offline or online, then trust their own output. None
  prove the record wasn't changed later.
- **iNaturalist / eBird** are platforms: useful, gated, and their data is not
  independently verifiable.
- **IOTA Audit Trails / Notarization** anchor data so a hash can be shown to have
  been published. Generic. Vickrey is the _reconciliation_ on top: it compares
  the record against an independent read and shows the verdict.

The differentiator is not "we anchor things." It is "we prove your copy and the
ledger still agree — and we can retract without losing the proof."

## Reused engine

`services/ledger` and `apps/explorer` already implement the commons layer. The
two-source truth table is domain-agnostic and unchanged:

| Last Hornet read              | Payload | Solidity          | Status             |
| ----------------------------- | ------- | ----------------- | ------------------ |
| Unreachable / missing         | unknown | unknown           | `PENDING`          |
| Tagged data differs           | no      | any               | `PAYLOAD_MISMATCH` |
| Tagged data matches           | yes     | not solid         | `NOT_SOLID`        |
| Matches, solid, no milestone  | yes     | solid             | `PENDING`          |
| Matches, solid, milestone set | yes     | solid + milestone | `VERIFIED`         |

`PAYLOAD_MISMATCH` outranks solidity: a solid block can still be a lying copy.

## Risks and mitigations

| Risk                                     | Mitigation                                                                                                                      |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Reads as a re-skin of the old build      | The offline gap + device signature + anchoring rule are new, load-bearing mechanics                                             |
| Ledger is heavy for a one-week build     | Keep it optional; ship the offline signed log first, anchor second                                                              |
| Sensitivity of location data             | Precise location and raw records stay off-chain; the anchor carries only coarse location + species summary; delayed publication |
| "A ledger doesn't make a wrong ID right" | State the accuracy/integrity split openly; lead with the model quality                                                          |
| Research can't consume it                | Darwin Core export is a planned first-class deliverable, not a nice-to-have — currently unimplemented                           |

## Leave for later

- Shielded field rewards in TAZ (promoted to the ECATHON build window —
  see [ECATHON.md](ECATHON.md)).
- Micro-credits / incentives for verified observations.
- Webhook alerts on status flip (mismatch → page, not poll).
- Signed, anchored audit summaries fed back to the commons.
- Federated anchoring across institutions.
