# Vickrey

**Private, verifiable field records.** Record a sighting, seal it on your
device with an Ed25519 signature, and anchor its commitment in a Zcash
encrypted memo. Share one sealed record when you choose: a recipient can
check its contents and signature locally, then ask the anchor service to
check the memo. The shielded demo uses a private regtest chain; it is not a
mainnet or public-testnet deployment. On-phone, offline identification is
planned; the current model integration uses a reachable server.

> **Try the field loop locally:** load the sample walk, tamper with a queued
> copy, watch sync refuse it, restore it. [Deployment instructions](docs/DEPLOY_DEMO.md)
> describe the combined site + shielded service — prepared but not yet
> launched. The older GitHub Pages demo below uses the public ledger.

The name borrows the metaphor: **Vickrey** is named for William Vickrey's
**sealed-bid auction** — committing to a value in secret. Here the commit is
cryptographic, not economic: your phone **seals** what you saw and tampering
**cracks the seal**. Nothing in the mechanism makes an observation true —
it makes changes detectable ([docs/BRAND.md](docs/BRAND.md)).

**What is real vs. what is planned lives in exactly one place:
[docs/STATUS.md](docs/STATUS.md).** Every claim below links there rather than
arguing for itself.

## The loop

```
see it ──► record an observation; optionally ask a reachable model for an ID
     ──► sign {observed_at, location, model_id, payload} on the device
     ──► append to a local hash-chained log
     ──► (back in range) anchor the commitment in an encrypted Zcash memo
     ──► share one signed record; verify locally and check its memo via the service
```

Three layers, one job each:

1. **Identify** — the field client talks to any OpenAI-compatible endpoint;
   a real Gemma 3 4B run is verified server-hosted over a reachable server.
   On-device, offline execution is planned, not shipped — there is no claim
   the page identifies anything without a network.
2. **Prove** — each record is signed by a device key and hash-chained to its
   predecessor. A signature verifies the signed bytes under that key; it does
   not prove the observer's identity or capture time. A verified memo binds
   the commitment to a transaction at a block height. On a trusted chain this
   establishes that the committed record existed no later than that block.
   Our regtest demo is a chain operated by this project.
3. **Share** — export an encrypted backup, or disclose one sealed record as
   a signed bundle a recipient can check locally before asking the anchor
   service to confirm the memo. That check runs on the service's wallet —
   a trusted service, not independent verification. Raw data stays
   off-ledger.

## The anchoring rule (what makes this responsible)

**Anchor commitments, not observations.** In the default shielded mode,
only a commitment goes to the anchor service, which places it in an encrypted
memo. The public chain does not reveal the observation, device signature or
device public key. It does reveal a transaction, its block placement and fee.

The explicitly selected legacy public mode also publishes the device key,
signature, timestamp, coarse area and species summary. Exact coordinates and
photos are not published by either anchor flow. A disclosure file intentionally
reveals the selected record, including its recorded coordinates.

- **Locations stay off the public anchor.** The observer decides whether to
  share a record containing them with a recipient.
- **Science can still retract.** Wrong IDs get corrected off-chain while the
  anchor still proves the record's early state.
- **Researchers can actually use it.** The ledger is the trust wrapper; the
  plan is Darwin Core export.

**Integrity is not accuracy**: verification detects changes against a sealed
commitment. It does not establish that the observation or identification was
true, or that a device's clock was correct.

## ECATHON history and subsequent improvements

Week 1 (Hacktoberfest) proved the seal; **ECATHON** closes the privacy gap
it left open. The current anchor ledger publishes `who + what + coarse where +
when` — an immutable correlation map. A stranger who checks block height can
still build "who observed the rare bird, where, and when".

The current implementation puts the commitment in the **encrypted memo**.
Unlike the original beacon-only mode, this binds the commitment to the
transaction's contents. The service reads the memo with its wallet; a browser
recipient still trusts that service for the memo check. Shielded field rewards
remain a design, with no payouts.

The first commit was **2026-10-06**, within the documented Sep 28 – Oct 28
build window. The verification, disclosure, recovery and deployment work
dated **2026-10-30 is post-submission work**. It must not be represented as
part of the code available before the Oct 28 deadline.
Historical plan: [docs/ECATHON.md](docs/ECATHON.md).

## Run it locally

```bash
bash scripts/demo_field.sh
# prints a field-client URL wired to a mock Hornet via the anchor relay;
# seal a sample, verify the chain, edit it, watch the crack refuse to sync
```

The **sample walk** (around Dalston: ivy confirmed, a robin _corrected_ from
the model's wrong "common blackbird", hawthorn confirmed) seals through the
ordinary logbook — real hashes, real Ed25519 signatures — so the demo needs no
camera, no model, and no network. The correction is sealed beside the model's
original suggestion, which is the whole thesis in one row.

Want the real model in the loop: run `gemma3:4b` in Ollama and append
`&endpoint=…&model=gemma3:4b` to the printed URL — [docs/OPS.md](docs/OPS.md)
covers it, including what that does _not_ prove.

## Earlier public demo (GitHub Pages — static only)

Pushes to `main` publish these static files via GitHub Pages. There is **no
anchor service behind that host**: the new `/api` default does not resolve
there until the demo deployment is separately live, and nothing silently
falls back to public — the client shows shielded anchoring as offline. To
see the legacy public-ledger flow explicitly, pass `anchor=public`:

- **Field client (public anchor):** <https://sneldao.github.io/vickrey/field/?anchor=public>
- **Field client (default; shielded offline on Pages):** <https://sneldao.github.io/vickrey/field/>
- **Explorer:** <https://sneldao.github.io/vickrey/explorer/> — the evidence board,
  with a plain-language glossary and the same definition on every status stamp
- **Showcase:** <https://sneldao.github.io/vickrey/> — its "What is actually
  running" panel fetches `/health` at page load, so the page can't claim what
  has stopped being true.
- **Ledger:** <https://vickrey-ledger.fly.dev> (`/health`, `/docs`)
- **92-second film:** [YouTube](https://youtu.be/9BmpLblSHUM) (unlisted; shows
  server-hosted Gemma and a mock Hornet)

## Stack

- **Identify:** open-weight model (Gemma 3 4B verified server-hosted; on-device planned)
- **Prove:** WebCrypto Ed25519 seal + hash-chained journal (`apps/field`)
- **Commons / anchor verifier:** `services/ledger` — FastAPI + SQLite, optional Atlas + Tavily
- **Explorer:** `apps/explorer` — static; published at `/explorer/`, also served
  on port 8090 for the local demo box
- **Hosting:** Fly.io (ledger), GitHub Pages (client + showcase)
- **Shielded demo:** combined static site and zanchor behind HTTPS; a private
  regtest node, with persistent receipts. See [deployment](docs/DEPLOY_DEMO.md).
- **Anchor (optional):** private Hornet via
  [eclipse-aerios/iota-tangle](https://github.com/eclipse-aerios/iota-tangle)
- **License:** [Apache-2.0](LICENSE)

## Docs

- [docs/STATUS.md](docs/STATUS.md) — **the** honest table. Start here.
- [docs/OPS.md](docs/OPS.md) — runbook: local demos, Fly deploy, Atlas/Tavily
  gotchas, seeding, the ledger API, tests.
- [docs/STRATEGY.md](docs/STRATEGY.md) — positioning, architecture, anchoring
  design, competitors, risks, interop.
- [docs/ECATHON.md](docs/ECATHON.md) — historical Zcash hackathon plan.
- [docs/ZANCHOR_API.md](docs/ZANCHOR_API.md) — the pinned wire contract between the field client / explorer and the shielded anchor service.
- [docs/PRIVACY.md](docs/PRIVACY.md) — the threat model: the timing mitigation with its numbers, the residual leaks named, and the questions still open.
- [docs/DISCLOSURE_DESIGN.md](docs/DISCLOSURE_DESIGN.md) — implemented sharing flow and its trust limits.
- [docs/DEPLOY_DEMO.md](docs/DEPLOY_DEMO.md) — combined site, private regtest service, and recovery runbook.
- [docs/ON_DEVICE_SPIKE.md](docs/ON_DEVICE_SPIKE.md) — feasibility write-up for running field identification on-device; unmeasured.
- [docs/SHIELDED_REWARDS_DESIGN.md](docs/SHIELDED_REWARDS_DESIGN.md) — design write-up for shielded TAZ rewards; no payouts.
- `scripts/demo_zcash.sh` — one command: mock shielded anchor, contract walk, explorer link. `--zanchor URL` runs the same checks against the real service.
- [docs/film/ecathon/](docs/film/ecathon/) — the 92 s ECATHON submission film source (HyperFrames): it seals its own narration hash through zanchor (`SEAL.json`); renders and media are not committed.
- `scripts/seed_ledger.mjs` — refill a ledger's board from the sample walk, under a visible `sample-walk` flow (every deploy resets it; see OPS.md).
- [docs/BRAND.md](docs/BRAND.md) — the seal narrative, colour and type system.
- [docs/BUILD.md](docs/BUILD.md) — build log (history; status moved to STATUS.md).
- [docs/archive/](docs/archive/) — the Hacktoberfest Week 1 submission record
  and partner/prize plan, kept as filed on October 11, 2026.

## References

- <https://github.com/eclipse-aerios/iota-tangle>
- <https://github.com/eclipse-aerios/iota-messages-api>
- <https://github.com/iotaledger/hornet>
- <https://dwc.tdwg.org/>
