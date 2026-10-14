# Vickrey — Prove What You Saw

**A sealed bid on what you saw.** Vickrey is an offline, open-source AI field
identifier with a tamper-evident ecological logbook — for
[Hacktoberfest 2026, Week 1: **Touch Grass**](https://hacktoberfest.com).

The name is the metaphor: **Vickrey** is named for William Vickrey's **sealed-bid
auction** — a mechanism that makes truth the winning strategy. We point the same
mechanism at the world: your phone **seals** what you saw, the network
countersigns it, and tampering **cracks the seal**. See
[`docs/BRAND.md`](docs/BRAND.md).

The vision: point your phone at a bird, a plant, or a fall tree with **no
signal**. An open-weight model running **on the device** names what you saw.
Vickrey signs the
observation, chains it into a tamper-evident log, and — when you are back in
range — anchors the _commitment_ to a shared ledger. The result is a field record
you can later prove nobody edited, and a shared, citable commons for research.

The screen is the shortest part of the experience. The model is meant to run
locally, the record is yours, and the proof survives the walk.

## Status — what runs today vs the plan

**Live field client:** <https://sneldao.github.io/vickrey/field/> — the real
thing, no query string, talking to the deployed ledger on Fly.io. Verified in a
browser from a cold start: load the sample walk → tamper → sync **refused** →
restore → sync → three `Anchored · VERIFIED`, with the Atlas Commons panel and
live Tavily context both working.

**Public showcase:** [Vickrey on GitHub Pages](https://sneldao.github.io/vickrey/) embeds the [92-second film on YouTube](https://youtu.be/9BmpLblSHUM) (unlisted). The film demonstrates server-hosted Gemma and a mock Hornet — not outdoor, on-phone, or public-ledger use. Pages serves the static story and the field client; the ledger and commons run on Fly.io and Atlas. It does not host the model. The older hosted incident explorer is a separate Veles-era demo, not this field client.

**Week 1 entry cutoff:** October 11, 2026 at 11:59 PM PDT ([official rules](https://dev.to/page/hacktoberfest-week1-2026-10-05-contest-rules)). An eligible entry needs a published DEV post using the challenge template and tags, a demo link or video, a code repository link, and an explanation of why open innovation matters. The project and repository must have begun during October 5–11. This repository's initial commit was October 6; the Veles ledger/explorer began during that window and is reused for the field client. Disclose that reuse; eligibility is the organizer's call.

**Verified end-to-end, all local:** photo → model **suggestion** → the
observer **confirms or corrects** it → Ed25519 seal (the decision is part of
the signed payload) → field journal + hash-chained outbox that verifies →
anchor relay → mock Hornet → ledger `VERIFIED`. Editing the queued copy cracks
the seal and **sync refuses to send it**; the journal keeps the sealed record,
which can be put back. Sync never erases a sighting: the journal is the
device's history and the outbox only holds what is still unsent. Run it with
`bash scripts/demo_field.sh`.

The opening vision describes the _planned_ production architecture. Not yet
verified or built:

- **The ledger is deployed** at <https://vickrey-ledger.fly.dev> (one machine,
  `lhr`, `HORNET_EMBEDDED=1`). The full loop — seal, tamper, refused sync,
  restore, `VERIFIED` — was verified against it over the public internet, as was
  the ledger-side `PAYLOAD_MISMATCH`. Two caveats that are not obvious: the SQLite
  copy resets on every `fly deploy` (no volume — creating one needs a payment
  method), and **the app must be scaled to exactly one machine after every
  deploy**, because Fly's rolling deploy otherwise leaves two machines each
  holding their own block store. See the Fly section below.
- **Atlas and Tavily are both live.** `MONGODB_URI` and `TAVILY_API_KEY` are set
  as Fly secrets; `/health` reports `observations: true` and `context: true`, and
  the Commons panel serves real anchors from a real M0 cluster. Getting there took
  three fixes that are worth knowing about, because each failure looked like the
  same thing:
  1. **An empty IP access list.** Atlas refuses an unknown IP with a TLS alert
     (`tlsv1 alert internal error`) that looks exactly like a certificate fault.
     It is not — it is an access-list rejection.
  2. **No CA bundle.** Local Python had no trust store for Atlas's certificate;
     `app.atlas.connect` now passes certifi's bundle explicitly.
  3. **`atlas dbusers update` needs the username positionally**, so a `--username`
     flag silently changed nothing and auth failed with `bad auth`.
     Atlas is reachable from anywhere (`0.0.0.0/0`) because Fly's egress IPs are
     dynamic. That is acceptable here precisely because of the anchoring rule: the
     collection holds commitments, coarse areas and species summaries — no photos,
     no notes, no precise location.
- A real **on-device/offline** model run is still unverified. A real
  server-hosted Gemma 3 4B vision inference through the field client did run
  over a private SSH tunnel: on a credited Wikimedia Commons European robin
  photo it returned "Robin" (`model_id: gemma3:4b`), and the sealed entry
  reached `VERIFIED` against the mock Hornet. The remote model received the
  photo; this does not demonstrate phone/offline operation. The same model,
  run with Ollama on a CPU cloud VM, again suggested "Robin" (self-reported
  confidence 0.95, about 20 s); the observer confirmed it before sealing. A
  model's confidence is its own score, not calibrated accuracy.
- The real Messages API / public Hornet anchor. The local demos use
  `scripts/mock_hornet.py` + `scripts/anchor_relay.py`, or
  `HORNET_EMBEDDED=1` for the single-process shape.
- The Temporal sync workflow (scaffold only) and Darwin Core export. The field
  walk and the Week 1 DEV post (submitted October 11, 2026) are done; see
  [`docs/BUILD.md`](docs/BUILD.md) for the post-submission Buildathon work.

## The loop

```
see it ──► on-device open-weight model IDs it   (no signal, no upload)
       ──► sign {observed_at, coarse location, model_id, payload} on the device
       ──► append to a local hash-chained log
       ──► (back in range) Messages API ──► Hornet block ──► solid / milestone
       ──► anchor the commitment + signature + timestamp + coarse location
           + species summary — never the raw photo, notes, or precise GPS
       ──► commons API + explorer: trust checklist, mismatch detection,
           (planned) Darwin Core export
```

## Three layers

1. **Identify — on-device, open-weight AI.** The model is the product's core.
   The design runs it locally (bird audio → BirdNET-class model; photo → a
   small Gemma VLM) to enable eventual airplane-mode identification without
   uploading photos. Today's field client talks to any
   OpenAI-compatible endpoint — verified with the built-in sample, a
   stubbed reply, and with real Gemma 3 4B on a remote server; the real test
   sent a photo over a private SSH tunnel, not offline/on-phone. Open weights are what
   make this possible: no per-call API, runs on a laptop, swappable,
   inspectable.
2. **Prove — tamper-evident log.** Every observation is signed at capture time
   and hash-chained to the one before it. Editing a past entry breaks the chain;
   the device signature proves the observation **predates the upload**. This is
   the Vickrey two-source check, now between your device and the ledger.
3. **Share — an open commons.** The anchor makes a record citable and
   contributor-owned without a platform gatekeeper. Raw data stays off-chain;
   the anchor is a commitment — hash, signature, coarse location, summary —
   you can publish.

## The anchoring rule (what makes this responsible)

**Anchor commitments, not observations.** Put a hash + signature + timestamp +
coarse location + species summary on the ledger; keep the record (exact
location, photo, notes) off-chain and mutable. One inversion, three payoffs:

- **Precise location stays off the ledger.** An immutable public map of a rare
  bird is a poaching map; the anchor carries only a coarse location and a
  species summary — raw photos, notes, and exact GPS are not anchored. Hosted
  inference transmits the photo to the model server.
- **Science can still retract.** Wrong IDs get corrected off-chain while the
  anchor still proves the record's early state (a `superseded by` pointer).
- **Interop survives.** The ledger is the trust wrapper; the plan is for
  records to export as [Darwin Core](https://dwc.tdwg.org/) so researchers can
  actually use them (export is not yet implemented).

Integrity is not accuracy: a ledger proves a record was not altered, not that the
ID was right. The model's quality carries accuracy; the ledger carries provenance.

## What is reused

Vickrey's existing evidence ledger (`services/ledger`) and explorer
(`apps/explorer`) already implement the second half of the loop, and are reused
as-is as the **commons / anchor verifier**:

- The two-source check and its truth table —
  `VERIFIED / PENDING / PAYLOAD_MISMATCH / NOT_SOLID`.
- `flow_id` grouping (a walk, a patrol, a garden bed).
- Trust checklist, side-by-side mismatch view, deep-links.

The reused engine keeps its own demo: a **VERIFIED** row, then the demo-only
tamper route edits the application copy → **PAYLOAD MISMATCH** with both
payloads side by side. The block never changed. That is the legacy
ledger/explorer path — separate from the field client, where a locally edited
entry cracks the seal and **sync refuses to send it** instead.

## Stack

- **On-device AI:** open-weight model (see [`docs/SPONSORS.md`](docs/SPONSORS.md)).
- **Commons / anchor verifier:** `services/ledger` — FastAPI + SQLite, port 8088.
  Optional MongoDB Atlas commons mirror and optional Tavily web context; both
  are off unless configured.
- **Explorer / logbook:** `apps/explorer` — static page, port 8090.
- **Ledger hosting:** Fly.io, single container, `services/ledger/fly.toml`.
- **Anchor (optional):** private Hornet via
  [eclipse-aerios/iota-tangle](https://github.com/eclipse-aerios/iota-tangle);
  insert path through [iota-messages-api](https://github.com/eclipse-aerios/iota-messages-api).
- **License:** [Apache-2.0](LICENSE).

## Run the local field demo

```bash
bash scripts/demo_field.sh
# prints a field-client URL wired to a mock Hornet via the anchor relay;
# seal a sample, verify the chain, edit it, watch the crack refuse to sync
```

For the optional **server-hosted Gemma** demo, run Ollama with `gemma3:4b` on a host the browser can reach — on the same machine (`ollama serve`, then `ollama pull gemma3:4b`) or through a private tunnel (for example `ssh -fN -L 127.0.0.1:11435:127.0.0.1:11434 YOUR_HOST`). Append `&endpoint=http://127.0.0.1:11434&model=gemma3:4b` (or the tunnel port) to the printed field-client URL, choose a credited photo, then **Ask the model for a suggestion**. Review it, then **Confirm & seal** or **Correct it**. The photo is sent to that model server for inference; it is not an offline or on-phone demo. The mock Hornet/ledger are still local. Add `&area=LAT,LON` to record a coarse area (rounded to about 1 km) with each sighting.

### The sample walk

On an empty device the field client offers a **sample walk**: three sightings
sealed on demand, so the journal, the outbox and the seal-crack demo all have
something real to work on. It is not a mock — each step goes through the
ordinary logbook, so the hashes are computed and the Ed25519 signatures are
genuine, and the chain verifies exactly as a walk you made yourself would.

The walk is _a walk around Dalston_ (the anchor carries the coarse area only):
common ivy confirmed, a robin **corrected** — the model read the orange bib as
a common blackbird, which is a confusion a small VLM genuinely makes — and
hawthorn confirmed. The correction is sealed inside the record beside the
model's original suggestion, which is the whole thesis in one row.

The specimen plates in `apps/field/specimens.js` are labelled illustrations
drawn in the client's own ink-on-parchment language, not photographs: they are
data URIs, so the sample walk needs no camera, no network and no stock imagery,
and a plate can never disagree with the name printed on it. **Clear this
device** returns to an empty journal and keeps the device key, because it is
the same device — only the walk is cleared.

### The field journal and the outbox

- **Suggestion, then decision.** The model only suggests a name. Nothing is sealed until the observer confirms it or writes a correction; the decision, and the model's original suggestion, are inside the signed payload, so changing either later cracks the seal.
- **Journal ≠ outbox.** Each sealed record is kept in a local field journal (`vickrey.journal` in `localStorage`, with a small local thumbnail that is never hashed or sent). The outbox (`vickrey.queue`) only holds records not yet synced. A successful sync empties the outbox and marks the journal record `Anchored · VERIFIED`; it never removes the sighting.
- **The crack.** The demo control edits the copy waiting in the outbox. The chain no longer verifies, sync refuses, the journal record shows the cracked seal, and **Put the sealed copy back** restores the outbox from the journal.

## Run the commons

Host process, Hornet on localhost:

```bash
python3 -m venv services/ledger/.venv
services/ledger/.venv/bin/pip install -r services/ledger/requirements.txt
cd services/ledger
HORNET_URL=http://127.0.0.1:14265 DATABASE_PATH=./data/ledger.db \
  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8088
```

Docker, beside the ledger:

```bash
docker compose up -d --build
# explorer http://localhost:8090
# ledger   http://localhost:8088/docs
```

Explorer alone against a running ledger:

```bash
python3 -m http.server 8090 --bind 127.0.0.1 --directory apps/explorer
```

Endpoints and configuration are unchanged from the ledger/explorer design; the
full table lives in [`docs/STRATEGY.md`](docs/STRATEGY.md).

### Deploy the single-process ledger (Fly.io)

`HORNET_EMBEDDED=1` makes the ledger hold the tagged-data block itself before
reading it back, so the field client posts straight to `/ingest` — no anchor
relay, no separate Hornet, one container. `scripts/mock_hornet.py` keeps its
blocks in a module-level dict and so cannot be split across serverless
invocations, which share no memory; one always-on process can.

```bash
cd services/ledger
fly secrets set MONGODB_URI="mongodb+srv://..."
fly deploy && fly scale count 1 --yes
```

Or just `scripts/deploy_fly.sh`, which creates the app if needed, sets secrets
when the environment variables are exported, deploys, and scales to one machine.

**Scale to one after every deploy.** Fly's rolling deploy leaves the old
machine running alongside the new one, so the app comes up with **two** of them.
With `HORNET_EMBEDDED=1` each machine holds its own in-memory block store and
its own SQLite file, so requests round-robin between two ledgers that cannot see
each other: a block registered on one is invisible on the other, records strand
at `PENDING`, and `/messages/{id}/tamper` randomly 404s. The failure is silent —
health stays green on both machines. `scripts/deploy_fly.sh` handles it and
prints the count.

Then point the field client at it — `?ledger=https://vickrey-ledger.fly.dev&commons=…`
— or change the defaults in `apps/field/config.js`. `services/ledger/fly.toml`
carries the rest.

**What embedded mode changes.** The block store moves into the ledger's own
process, so the ledger no longer only ever GETs — in embedded mode it writes the
block before reading it back. The two-source property survives at the data
layer, which is what the check tests: the application copy is in SQLite, the
block is in a separate structure, so editing the copy alone still yields
`PAYLOAD_MISMATCH`. What is lost is the guarantee that a _different process_
holds the block. Point `HORNET_URL` at a real node and none of this applies —
the ledger only ever GETs, as it does locally. `scripts/demo_field.sh` runs the
faithful three-process version; `scripts/demo_single.sh` runs the deployable one.

**The store is in memory, so the app must run exactly one instance.** Scale to
zero and a restart drops every registered block, stranding its record at
`PENDING`. `fly.toml` therefore sets `auto_stop_machines = "off"` and
`min_machines_running = 1`. `/health` reports `anchoring` and
`blocks_registered` so you can see this working.

### Seed the commons with sample observers

The Commons panel is much stronger with rows in it, but seeding it with a real
person's records would be a lie. `scripts/seed_commons.py` writes anchors under
`flow_id = sample-observer-NN`, which the field client badges **sample observer**
and `sampleMark()` filters on.

The signatures are **real**. Each sample observer gets its own Ed25519 device
key, every commitment is signed over a record body in the same shape
`trust.sealObservation` uses, and every anchor is re-verified after it is
written — so a MongoDB engineer can pull a document and check it. The public key
for each observer prints on every run. Records that were corrected keep the
model's score off the final name, exactly as the field client does.

```bash
scripts/ledger/.venv/bin/python scripts/seed_commons.py \
  --uri "$MONGODB_URI" --seed-demo-data
scripts/ledger/.venv/bin/python scripts/seed_commons.py \
  --uri "$MONGODB_URI" --verify      # re-check every stored signature
```

It refuses to write without `--seed-demo-data`, and the check happens _before_
any connection is opened, so it cannot contaminate a real commons. To remove:
`db.observations.deleteMany({flow_id: {$regex: '^sample-observer-'}})`.

Note what `--verify` cannot do: recompute a commitment. That needs the sealed
record body, which the commons deliberately does not store — the anchoring
rule, not a gap.

### Web context (Tavily)

An identifier that says "European robin" and stops is half a product. What is
missing is context — is this species expected here, is it notable, when did
others last report it nearby? That is public, slow-changing knowledge, and a
web search is the right tool for it. `POST /context` on the ledger returns
recent reports from Tavily, shown **beside** an anchored record.

Three rules, all enforced by tests:

- **Context is never sealed.** Nothing from a search is written into the record
  or the anchor. The seal is the observer's own observation; a third party's
  answer cannot be part of a commitment someone is expected to reproduce.
- **The ledger stays the source of truth.** A Tavily outage, quota error or
  missing key degrades to a line of text on the page. It never fails an ingest
  and never moves a status off `VERIFIED`.
- **Only coarse geography leaves the device.** The query carries the species and
  an optional place _name_ the observer already chose to record (`&place=…`). It
  never carries a coordinate.

The API key is server-side, so this is a route on the ledger rather than a fetch
from the browser. The species name is quoted, so a bare "robin" cannot be
silently substituted with the American bird — which matters on a UK record.
`search_depth: basic` keeps each lookup at one credit, and the credit use is
displayed.

```bash
fly secrets set TAVILY_API_KEY="tvly-..."
bash scripts/demo_context.sh     # runs it against a local fake, no key needed
```

Without a key the button does not appear: the field client probes `/health` for
`context`, the same way it probes for the commons. `scripts/fake_tavily.py` is a
standalone stand-in, and `TAVILY_ENDPOINT` points the client anywhere.

### Tests

```bash
services/ledger/.venv/bin/pip install -r services/ledger/requirements-dev.txt
(cd services/ledger && .venv/bin/python -m pytest)
node --test apps/field/*.test.mjs apps/explorer/app.test.mjs
```

91 JS tests and 119 ledger tests cover the seal, the chain, the tamper path, the
sample walk and the embedded block store. The walk tests seal through the real
logbook rather than a stand-in, and assert that a seeded chain verifies, that
tampering cracks it, and that the anchor carries a commitment, a coarse area
and the device key — never the record itself. The embedded tests assert the
property that matters most for hosting: a tampered application copy is still
caught when the block store is in-process.

## The showcase site

`apps/site` is the GitHub Pages page, published on every push to `main` by
`.github/workflows/pages.yml`, which assembles `apps/site` at the root and
`apps/field` at `/field/`.

Its "What is actually running" section fetches `/health` and
`/observations/recent` when the page loads and renders the real state, so the
page cannot claim something that has stopped being true. If the ledger is
unreachable it says so.

## Docs

- [`docs/BRAND.md`](docs/BRAND.md) — the seal narrative, colour and type system.
- [`docs/STRATEGY.md`](docs/STRATEGY.md) — positioning, architecture, anchoring
  design, ecological externalities, risks, interop.
- [`docs/PITCH.md`](docs/PITCH.md) — Hacktoberfest submission plan and demo script.
- [`docs/BUILD.md`](docs/BUILD.md) — build log.
- [`docs/SPONSORS.md`](docs/SPONSORS.md) — partner stack mapped to prize categories.

## References

- <https://github.com/eclipse-aerios/iota-tangle>
- <https://github.com/eclipse-aerios/iota-messages-api>
- <https://github.com/iotaledger/hornet>
- <https://dwc.tdwg.org/>
- <https://hacktoberfest.com>
