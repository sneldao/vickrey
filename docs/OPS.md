# Ops — running and hosting Vickrey

> _Current as of 2026-10-30: [STATUS.md](STATUS.md) is the live status table, [DEPLOY_DEMO.md](DEPLOY_DEMO.md) the prepared private deployment, and [DISCLOSURE_DESIGN.md](DISCLOSURE_DESIGN.md) the implemented disclosure contract. Public-ledger sections below are the legacy path._

Everything a builder needs: the three hosting shapes, deploying the ledger,
the failure modes we already hit so you don't hit them blind, seeding, and
tests. Product story and honest status live elsewhere —
[README](../README.md) and [STATUS.md](STATUS.md).

## Hosting shapes

| Mode                                           | Processes                                              | Two-source check              | When                                  |
| ---------------------------------------------- | ------------------------------------------------------ | ----------------------------- | ------------------------------------- |
| `scripts/demo_field.sh`                        | 3 (field client → anchor relay → mock Hornet + ledger) | separate processes            | the faithful local demo               |
| `scripts/demo_single.sh` (same shape Fly runs) | 1                                                      | separate stores, same process | one container, simplest to host       |
| real `HORNET_URL`                              | ≥ 2                                                    | fully independent             | production, once a real node is wired |

## Run the local field demo

```bash
bash scripts/demo_field.sh
# prints a field-client URL wired to a mock Hornet via the anchor relay;
# seal a sample, verify the chain, edit it, watch the crack refuse to sync
```

Optional **server-hosted Gemma** demo: run Ollama with `gemma3:4b` on a host the
browser can reach — same machine (`ollama serve && ollama pull gemma3:4b`) or a
private tunnel (`ssh -fN -L 127.0.0.1:11435:127.0.0.1:11434 YOUR_HOST`). Append
`&endpoint=http://127.0.0.1:11434&model=gemma3:4b` (or the tunnel port) to the
printed field-client URL, choose a credited photo, **Ask the model for a
suggestion**, then **Confirm & seal** or **Correct it**. The photo is sent to
that model server; this is not an offline or on-phone demo. Add `&area=LAT,LON`
to record a coarse area (rounded to ~1 km) with each sighting.

## Run the commons locally

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

## Ledger API & configuration

Endpoints (ledger on port 8088; OpenAPI at `/docs`):

| Route                                                | What                                                                                                  |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `GET /`                                              | Service identity, including `guarantee.independent_source`                                            |
| `GET /health`                                        | Real state: `anchoring`, `blocks_registered`, `observations`, `context`                               |
| `POST /ingest`                                       | Accept a sealed anchor; runs the two-source check                                                     |
| `GET /messages`                                      | List, filtered by `flowId`, `tag`, `status`, `from`, `to`                                             |
| `GET /messages/{id}`                                 | One record + its verdict                                                                              |
| `POST /messages/{id}/tamper` · `/restore`            | **Demo-only** — mutate the application copy, then restore it, to show `PAYLOAD_MISMATCH` side by side |
| `POST /messages/{id}/reverify`                       | Re-run the two-source check                                                                           |
| `GET /observations/recent` · `/observations/similar` | Atlas commons panel feeds (recency and word-overlap similarity)                                       |
| `POST /context`                                      | Tavily web context, server-side key                                                                   |

Environment: `HORNET_URL`, `HORNET_EMBEDDED`, `DATABASE_PATH`, `MONGODB_URI`,
`MONGODB_DB` (default `vickrey`), `TAVILY_API_KEY`, `TAVILY_ENDPOINT`,
`LOG_LEVEL`. Ports: ledger 8088, explorer 8090, mock Hornet 14265.

## Deploy the ledger (Fly.io)

`HORNET_EMBEDDED=1` makes the ledger hold the tagged-data block itself before
reading it back, so the field client posts straight to `/ingest` — no anchor
relay, no separate Hornet, one container. `scripts/mock_hornet.py` keeps its
blocks in a module-level dict and so cannot be split across serverless
invocations, which share no memory; one always-on process can.

```bash
cd services/ledger
fly secrets set MONGODB_URI="mongodb+srv://..." TAVILY_API_KEY="tvly-..."
fly deploy && fly scale count 1 --yes
```

Or just `scripts/deploy_fly.sh`, which creates the app if needed, sets secrets
when the environment variables are exported, deploys, and scales to one machine.

### Scale to one after every deploy

Fly's rolling deploy leaves the old machine running alongside the new one, so
the app comes up with **two** of them. With `HORNET_EMBEDDED=1` each machine
holds its own in-memory block store and its own SQLite file, so requests
round-robin between two ledgers that cannot see each other: a block registered
on one is invisible on the other, records strand at `PENDING`, and
`/messages/{id}/tamper` randomly 404s. **The failure is silent — `/health`
stays green on both machines.** `scripts/deploy_fly.sh` handles it and prints
the count.

### What embedded mode changes

The block store moves into the ledger's own process, so the ledger no longer
only ever GETs — in embedded mode it writes the block before reading it back.
The two-source property survives at the **data** layer, which is what the check
tests: the application copy is in SQLite, the block is in a separate structure,
so editing the copy alone still yields `PAYLOAD_MISMATCH`. What is lost is the
guarantee that a _different process_ holds the block. The ledger publishes this
as `guarantee.independent_source` (`/health` → `independent_source: false`) and
`tests/test_honesty.py` fails the build if that ever drifts. Point `HORNET_URL`
at a real node and none of this applies — the ledger only ever GETs.

### Persistence

The block store is in memory and the SQLite file has no volume (creating one on
Fly needs a payment method), so **a redeploy resets the ledger's copy** —
watch `blocks_registered` drop to 0. `fly.toml` therefore sets
`auto_stop_machines = "off"` and `min_machines_running = 1`: scale to zero and
a restart drops every registered block, stranding its record at `PENDING`.

### The deployed board's contents

**Every deploy resets the ledger's copy**, so the board comes up empty. Refill it
with the product's own sample walk — sealed by the real modules, not a fixture:

```bash
node scripts/seed_ledger.mjs                        # https://vickrey-ledger.fly.dev
node scripts/seed_ledger.mjs http://127.0.0.1:8088   # a local ledger
```

The script runs `apps/field`'s own `trust.js`, `logbook.js` and `app.js` over
`seed.js`'s walk, so every hash, chain link and Ed25519 signature is genuine and
the ledger's two-source check reads `VERIFIED`. It anchors them under flow id
`sample-walk`, which the board shows as a flow label — the rows read as the demo
they are, not as a contributor's walk. One labelled probe row (`seed-probe`) is
left over from a seeding check; it says what it is in its payload.

`POST /ingest` is an upsert keyed on block id, and a sample-walk entry's hash
covers its `observed_at`, so `--now <ISO>` reproduces an earlier walk's three
block ids and overwrites those rows instead of adding a second copy.

### Point the field client at it

Append `?ledger=https://vickrey-ledger.fly.dev&commons=…`, or change the
defaults in `apps/field/config.js`. `services/ledger/fly.toml` carries the rest.

## Atlas gotchas (all three bit us; each looked like the same fault)

1. **An empty IP access list.** Atlas refuses an unknown IP with a TLS alert
   (`tlsv1 alert internal error`) that looks exactly like a certificate fault.
   It is not — it is an access-list rejection.
2. **No CA bundle.** Local Python had no trust store for Atlas's certificate;
   `app.atlas.connect` now passes certifi's bundle explicitly, and `certifi` is
   a direct requirement, not a transitive one.
3. **`atlas dbusers update` takes the username positionally** — a `--username`
   flag silently changed nothing and auth failed with `bad auth`.

Atlas is reachable from anywhere (`0.0.0.0/0`) because Fly's egress IPs are
dynamic. That is acceptable here precisely because of the anchoring rule: the
collection holds commitments, coarse areas and species summaries — no photos,
no notes, no precise location.

## Web context (Tavily)

`POST /context` on the ledger returns recent public reports of a species, shown
**beside** an anchored record. Three rules, all enforced by tests:

- **Context is never sealed.** Nothing from a search enters the record or the
  anchor — the seal is the observer's own observation.
- **The ledger stays the source of truth.** An outage, quota error, or missing
  key degrades to a line of text; it never fails an ingest and never moves a
  status off `VERIFIED`.
- **Only coarse geography leaves the device.** The query carries the species
  and an optional place _name_, never a coordinate. The species name is quoted,
  so a bare "robin" cannot be silently substituted with the American bird.

The API key is server-side, so this is a route on the ledger, not a browser
fetch. `search_depth: basic` keeps each lookup at one credit, and the credit
use is displayed. Without a key the button does not appear: the field client
probes `/health` for `context`, the same way it probes for the commons.

```bash
fly secrets set TAVILY_API_KEY="tvly-..."
bash scripts/demo_context.sh   # runs against scripts/fake_tavily.py, no key needed
```

`TAVILY_ENDPOINT` points the client anywhere.

## Seed the commons with sample observers

The Commons panel is stronger with rows in it, but seeding it with a real
person's records would be a lie. `scripts/seed_commons.py` writes anchors under
`flow_id = sample-observer-NN`, which the field client badges **sample observer**
and `sampleMark()` filters on.

The signatures are **real**: one Ed25519 key per sample observer, every
commitment signed over a record body in the same shape `trust.sealObservation`
uses, and every anchor re-verified after writing. Corrected records keep the
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

## Tests

```bash
services/ledger/.venv/bin/pip install -r services/ledger/requirements-dev.txt
(cd services/ledger && .venv/bin/python -m pytest)
node --test apps/field/*.test.mjs apps/explorer/app.test.mjs
```

The walk tests seal through the real logbook rather than a stand-in, and assert
that a seeded chain verifies, that tampering cracks it, and that the anchor
carries a commitment, a coarse area and the device key — never the record
itself. The embedded tests assert the property that matters most for hosting:
a tampered application copy is still caught when the block store is
in-process.

## The showcase site

`apps/site` is the GitHub Pages page, published on every push to `main` by
`.github/workflows/pages.yml`, which assembles `apps/site` at the root and
`apps/field` at `/field/`. Its "What is actually running" section fetches
`/health` and `/observations/recent` at page load, so the page cannot claim
something that has stopped being true; if the ledger is unreachable it says so.
