# Vickrey

**A sealed bid on what you saw.** Point your phone at a bird, a plant, a fall
tree — with no signal. An open-weight model running on the device names what
you saw; Vickrey signs the observation, chains it into a tamper-evident log,
and — when you're back in range — anchors a _commitment_ to a shared ledger.
The result is a field record you can later prove nobody edited.

> **Try it in 90 seconds, no install:**
> <https://sneldao.github.io/vickrey/field/> → load the sample walk →
> _tamper with a queued copy_ → **sync is refused** → restore → sync →
> three `Anchored · VERIFIED`. That crack is the product.

The name is the metaphor: **Vickrey** is named for William Vickrey's
**sealed-bid auction** — a mechanism that makes truth the winning strategy.
We point the same mechanism at the world: your phone **seals** what you saw,
the network countersigns it, and tampering **cracks the seal**
([docs/BRAND.md](docs/BRAND.md)).

**What is real vs. what is planned lives in exactly one place:
[docs/STATUS.md](docs/STATUS.md).** Every claim below links there rather than
arguing for itself.

## The loop

```
see it ──► on-device open-weight model IDs it   (no signal, no upload)
     ──► sign {observed_at, coarse location, model_id, payload} on the device
     ──► append to a local hash-chained log
     ──► (back in range) anchor the commitment to the ledger
     ──► commons + explorer: trust checklist, mismatch detection,
         (planned) Darwin Core export
```

Three layers, one job each:

1. **Identify** — open-weight model, designed to run on-device. Open weights
   are load-bearing: no per-call API, swappable, inspectable, and the only way
   a trail-side ID works at all. The field client talks to any
   OpenAI-compatible endpoint; a real Gemma 3 4B run is verified, an on-phone
   run is the plan.
2. **Prove** — every observation is Ed25519-signed at capture and hash-chained
   to the one before. Editing a past entry breaks the chain; the signature
   proves the observation **predates the upload**. The model only _suggests_;
   the observer confirms or corrects, and that decision is inside the seal.
3. **Share** — the anchor makes a record citable and contributor-owned without
   a platform gatekeeper. Raw data stays off-ledger.

## The anchoring rule (what makes this responsible)

**Anchor commitments, not observations.** On the ledger goes a hash + signature

- timestamp + coarse area + species summary. Off the ledger stays the record:
  exact location, photo, notes. One inversion, three payoffs:

* **Precise location never becomes public.** An immutable public map of a rare
  bird is a poaching map.
* **Science can still retract.** Wrong IDs get corrected off-chain while the
  anchor still proves the record's early state.
* **Researchers can actually use it.** The ledger is the trust wrapper; the
  plan is Darwin Core export.

**Integrity is not accuracy**: the ledger proves a record was not altered, not
that the ID was right. The model carries accuracy; the ledger carries
provenance.

## Milestone 2: ECATHON (Zcash privacy hackathon, due Oct 28 23:59 UTC)

Week 1 (Hacktoberfest) proved the seal; **ECATHON** closes the privacy gap
it left open. The current anchor ledger publishes `who + what + coarse where +
when` — an immutable correlation map. A stranger who checks block height can
still build "who observed the rare bird, where, and when".

The fix: **move the anchor into the shielded pool.** The anchor becomes an
unremarkable shielded beacon transaction — nothing on-chain identifies what
was sealed, who sealed it, or why the tx exists at all; the commitment-to-tx
link lives only with the verifier, and block height still fixes the time.
Shielded TAZ field rewards are the stretch: money that moves without
publishing who got paid for what.

The whole repository is in-window: first commit **2026-10-06**, inside the
Sep 28 – Oct 28 build window, so every line of code was written for this
hackathon's window. Milestone 1 was the foundation; the Zcash layer is the
submission. Plan and threat model: [docs/ECATHON.md](docs/ECATHON.md).

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

## Live pieces

- **Field client:** <https://sneldao.github.io/vickrey/field/>
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
- **Anchor (optional):** private Hornet via
  [eclipse-aerios/iota-tangle](https://github.com/eclipse-aerios/iota-tangle)
- **License:** [Apache-2.0](LICENSE)

## Docs

- [docs/STATUS.md](docs/STATUS.md) — **the** honest table. Start here.
- [docs/OPS.md](docs/OPS.md) — runbook: local demos, Fly deploy, Atlas/Tavily
  gotchas, seeding, the ledger API, tests.
- [docs/STRATEGY.md](docs/STRATEGY.md) — positioning, architecture, anchoring
  design, competitors, risks, interop.
- [docs/ECATHON.md](docs/ECATHON.md) — **current milestone:** the Zcash shielded-anchor build plan and threat model (submission due Oct 28 2026).
- [docs/ZANCHOR_API.md](docs/ZANCHOR_API.md) — the pinned wire contract between the field client / explorer and the shielded anchor service.
- [docs/PRIVACY.md](docs/PRIVACY.md) — the threat model: the timing mitigation with its numbers, the residual leaks named, and the questions still open.
- [docs/DISCLOSURE_DESIGN.md](docs/DISCLOSURE_DESIGN.md) — design for verifier receipts and selective disclosure; open decisions listed.
- [docs/ON_DEVICE_SPIKE.md](docs/ON_DEVICE_SPIKE.md) — feasibility write-up for running field identification on-device; unmeasured.
- [docs/SHIELDED_REWARDS_DESIGN.md](docs/SHIELDED_REWARDS_DESIGN.md) — design write-up for shielded TAZ rewards; no payouts.
- `scripts/demo_zcash.sh` — one command: mock shielded anchor, contract walk, explorer link. `--zanchor URL` runs the same checks against the real service.
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
