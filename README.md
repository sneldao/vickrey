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

**Film:** [watch the 92-second demo on YouTube](https://youtu.be/9BmpLblSHUM)
(unlisted). The 92-second film is on YouTube; a GitHub Pages showcase will
embed it once deployed. It demonstrates server-hosted Gemma against the mock
Hornet — not outdoor, on-phone, or public-ledger use.

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

- A real **on-device/offline** model run is still unverified. A real
  server-hosted Gemma 3 4B vision inference through the field client did run
  over a private SSH tunnel: on a credited Wikimedia Commons European robin
  photo it returned "Robin" (`model_id: gemma3:4b`), and the sealed entry
  reached `VERIFIED` against the mock Hornet. The remote model received the
  photo; this does not demonstrate phone/offline operation. The same model,
  run with Ollama on a CPU cloud VM, again suggested "Robin" (self-reported
  confidence 0.95, about 20 s); the observer confirmed it before sealing. A
  model's confidence is its own score, not calibrated accuracy.
- The real Messages API / public Hornet anchor (the demo uses
  `scripts/anchor_relay.py` + `scripts/mock_hornet.py`).
- MongoDB Atlas commons search — the code is unit-tested against a fake store;
  `MONGODB_URI` was unset in the live demo.
- The Temporal sync workflow (scaffold only), Darwin Core export, the field
  walk, and the DEV post.

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
- **Explorer / logbook:** `apps/explorer` — static page, port 8090.
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

### Tests

```bash
services/ledger/.venv/bin/pip install -r services/ledger/requirements-dev.txt
(cd services/ledger && .venv/bin/python -m pytest)
node --test apps/field/*.test.mjs apps/explorer/app.test.mjs
```

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
