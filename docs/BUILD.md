# Build log — Hacktoberfest 2026, Week 1: Touch Grass

> **This is a log, not a status page.** Entries are dated, written in the tense
> of the evening they happened, and kept as evidence. What is true _now_ is in
> [`STATUS.md`](STATUS.md); how to run things is in [`OPS.md`](OPS.md).

**Vickrey — Prove What You Saw.** Offline, open-source AI field identification
with a tamper-evident ecological logbook. Entry period: October 5, 2026
at 9:00 AM PDT through October 11, 2026 at 11:59 PM PDT
([Week 1 rules](https://dev.to/page/hacktoberfest-week1-2026-10-05-contest-rules)).
The first commit in this repository is dated October 6; the ledger/explorer
started as Veles Hack work inside that window and is reused for the field
client. Describe that reuse transparently in the entry; the organizer decides
eligibility.

> **History.** The repository began at the Veles Hack (Challenge 2) as verified
> _incident_ evidence for a private IOTA Tangle. That engine — the two-source
> check, statuses, `flow_id` grouping, trust checklist, mismatch view, deep
> links — is reused unchanged as the commons/anchor verifier. The domain moved
> from incidents to field observations; the primitive did not.

## The pivot

- **Old:** app event → Messages API → Hornet → solid/milestone → incident evidence.
- **New:** offline AI ID → signed observation → hash chain → (optional) ledger
  anchor → open, citable ecological commons.

What is new and load-bearing: on-device open-weight identification, the
capture-time device signature, the local hash chain, and the **anchor
commitments, not observations** rule.

## What is reused as-is

- `services/ledger` — two-source truth table, `VERIFIED / PENDING /
PAYLOAD_MISMATCH / NOT_SOLID`, ingest fan-out, tamper + restore (demo-only).
- `apps/explorer` — timeline grouped by `flow_id`, trust checklist, side-by-side
  mismatch, `#<blockId>` deep links.

## Current local demo vs planned production

**Verified end-to-end locally** (`bash scripts/demo_field.sh`): sample
identification → Ed25519 seal → hash chain verifies → anchor relay → mock
Hornet → ledger `VERIFIED`; a tampered queue entry cracks the seal and sync
refuses to send it. The public [GitHub Pages showcase](https://sneldao.github.io/vickrey/) embeds the YouTube film, and the field client itself is now
[published and live at `/field/`](https://sneldao.github.io/vickrey/field/) — see
the Buildathon section below for what changed after this line was written.
Everything below is the build plan against the _planned_
production architecture, with status per item.

## Build plan → status

1. **Model-backed ID.** `apps/field/infer.js` calls an OpenAI-compatible
   endpoint. Real Gemma 3 4B vision inference ran on `snapflip-vultr` over a
   private SSH tunnel using a credited Wikimedia robin image; the model
   returned "Robin" with `model_id: gemma3:4b`. The browser sealed that result
   and reached `VERIFIED` against a mock Hornet. The remote model received the
   photo; no phone/offline or outdoors model run is verified. A labelled sample
   still works without a model.
2. **Signed observation.** Done — WebCrypto/Ed25519 device key, hash-chained
   log (`apps/field/trust.js`, `apps/field/logbook.js`); the chain head resumes
   from the persisted queue across page reloads.
3. **Offline queue.** Done — buffers entries, verifies the chain, and drains to
   the local anchor relay (`scripts/anchor_relay.py`, a stand-in for the
   Messages API). A cracked chain refuses to send. Caveat: there is no service
   worker — offline identification needs the page already loaded and a local
   model running, and none of this is proved on a real phone.
4. **Anchor.** Done locally — `commitment + signature + observed_at + coarse
location + model_id + species summary`, never the raw record, reaching
   `VERIFIED` against the mock Hornet via the relay. The real Messages API /
   public Hornet path is unrun.
5. **Commons.** Atlas observation store + vector-search code exists and is
   unit-tested against a fake store; `MONGODB_URI` was unset in the live demo,
   so similar-sightings reported "no observation store configured". Darwin
   Core export: not implemented.
6. **Write-up.** DEV post per `archive/PITCH.md` (submitted October 11, 2026); partner stack per
   `archive/SPONSORS.md` (targets, not realised integrations).

## Field review and journal (October 11)

- Inference now produces a **suggestion**; sealing requires the observer to
  confirm or correct it (`reviewedIdentification` in `apps/field/app.js`). The
  review decision and the model's original suggestion are in the signed
  payload; the anchor summary carries only the decision word.
- New `apps/field/journal.js`: durable per-device history, separate from the
  outbox queue. Sync marks journal records anchored with the ledger row; a
  refused sync marks the cracked record; the sealed copy can be restored to
  the outbox (`queue.replace`). Fixes the old behaviour where a verified sync
  drained the only local copy and the UI showed "0 sealed".
- Regression tests: `apps/field/journal.test.mjs` and a `queue.replace` test.
- Re-ran Gemma 3 4B (Ollama, CPU cloud VM) on the credited Wikimedia robin
  photo: suggestion "Robin", self-reported 0.95, ~20 s; confirmed, sealed,
  tamper refused, restored, `VERIFIED` on the mock Hornet. Still server-hosted,
  not on-phone, not outdoors.

## Buildathon — HYPE / Buildathon London, 14 October 2026

The Week 1 entry was submitted on October 11. Everything below is
**after submission**: it does not change what was judged, and it is committed
separately so the submitted state stays legible. The Buildathon partners
(MongoDB, Vercel, Tavily) are a different event with a different jury from the
Week 1 partners; see [`archive/SPONSORS.md`](archive/SPONSORS.md).

The goal for the evening was not new mechanics. It was that the loop must be
**demonstrable by a stranger on a laptop with no camera, no model and no
signal**, in two minutes.

### The cold open was the real problem

Traced what a first-time visitor actually sees: an empty journal, an empty
outbox, two disabled buttons, and a `<input capture="environment">` that has no
camera on a laptop. The only escape was "Try a labelled sample suggestion",
which sealed a species against an empty photo plate — the product demonstrating
it had no input.

### What was added

- **`apps/field/specimens.js`** — three labelled specimen plates (ivy, robin,
  hawthorn) as SVG data URIs, drawn in the client's ink-on-parchment language.
  Chosen over stock photography on purpose: Wikimedia Commons blocks bots from
  this host, and more importantly a photo that disagrees with its caption would
  be worse than an illustration that cannot.
- **`apps/field/seed.js`** — a specification of a sample walk, _not_ a mock.
  Each step is sealed through the ordinary `logbook.seal`, so hashes are
  computed and Ed25519 signatures are genuine, and the chain verifies exactly as
  a walk you made yourself would. The middle step is the one that matters: the
  model suggests a **common blackbird**, the observer **corrects it to a robin**,
  and the correction is sealed beside the suggestion.
- **Commons panel** promoted out of a `Proof` disclosure, and it only renders
  when `/health` reports a store is reachable — so there is no empty search box
  on a laptop with no Atlas behind it. It uses `/observations/recent`, not
  vector search: "who else has anchored lately?" is a recency question, and
  `atlas.py` is explicit that the local embedder matches shared words and
  nothing more.
- **`services/ledger/app/embedded.py`** (`HORNET_EMBEDDED=1`) — the block store
  in-process, so the ledger is one container: the field client posts straight to
  `/ingest`, with no anchor relay and no separate Hornet. `mock_hornet.py` keeps
  blocks in a module-level dict, so it cannot be split across serverless
  invocations, which share no memory. `services/ledger/fly.toml` runs it; the
  store is in memory, so the app must run exactly one instance with
  auto-stop off. `scripts/demo_single.sh` rehearses it locally.
- **`services/ledger/app/context.py`** — Tavily web context for an anchored
  record: recent public reports of the species, shown _beside_ the record. Three
  rules are enforced by tests, not comments: it is never sealed, a Tavily outage
  never moves a status off `VERIFIED`, and the query never carries a coordinate.
  The key is server-side. `scripts/demo_context.sh` runs it against
  `scripts/fake_tavily.py` with no key and no credits.
- **`scripts/seed_commons.py`** — sample-observer seeding for the commons, under
  `flow_id = sample-observer-NN` and badged as such in the UI. The signatures are
  **real**: one Ed25519 key per observer, commitments signed over a record body
  in the same shape `trust.sealObservation` uses, every anchor re-verified after
  writing. It refuses to write without `--seed-demo-data`, and that check runs
  before any connection opens.
- **`public_key` now travels with the anchor.** `anchorMessage()` omitted it
  while `atlas.py` listed it in `ANCHOR_FIELDS` and stored it, so every Atlas
  record would have carried `public_key: null` and the commons would have held
  anchors it could not verify.

### Verified after these changes

Full loop in a browser against `scripts/demo_single.sh` — the exact shape Fly
runs: sample walk → 3 waiting → tamper → sync **refused** ("nothing unsent left
the device") → restore → sync → 3 × `Anchored · VERIFIED`, with `/health`
reporting `anchoring: embedded` and `blocks_registered: 3`. Same again with web
context on. 91 JS tests and 119 ledger tests pass.

### Still not verified

- **The ledger is now deployed** — <https://vickrey-ledger.fly.dev>, one
  machine in `lhr`, `HORNET_EMBEDDED=1`. Verified over the public internet:
  the full field loop (seal → tamper → refused sync → restore → `VERIFIED`)
  driven in a real browser, and the ledger-side `PAYLOAD_MISMATCH` via curl.
- **A silent two-machine bug, found in deployment and worth recording.** Fly's
  rolling deploy leaves the old machine running alongside the new one, so the app
  came up with **two**. Each holds its own in-memory block store and its own
  SQLite file, so requests round-robin between two ledgers that cannot see each
  other: `/messages/{id}/tamper` returned 404 for a record that `/ingest` had
  just written seconds earlier, while `/health` stayed green on both machines.
  `fly scale count 1 --yes` fixes it. This is exactly the single-instance
  constraint the embedded mode implies — it just fails invisibly, and only under
  a real load balancer. `scripts/deploy_fly.sh` now scales to one and prints the
  count.
- **No volume**, so the SQLite copy resets on every `fly deploy` — creating one
  needs a payment method, which was not worth blocking the evening on.
- **Atlas and Tavily are now both deployed and verified live.** `MONGODB_URI`
  and `TAVILY_API_KEY` are Fly secrets; the Commons panel serves real anchors
  from an M0 cluster and the context route returns real Tavily results. The
  Atlas collection holds 12 documents: 9 labelled sample anchors across 3
  observers, plus 3 mirrored live from the field client.
- **Atlas took three fixes, each masquerading as the same fault.**
  `tlsv1 alert internal error` on connect is not a certificate problem — it is
  Atlas rejecting an IP that is not on the network access list, which is empty
  on a new cluster. Once that was fixed the error honestly became
  `CERTIFICATE_VERIFY_FAILED`, because local Python had no CA bundle for
  Atlas's certificate; `app.atlas.connect` now passes certifi's bundle
  explicitly, and `certifi` is a requirement rather than a transitive one.
  Third, `atlas dbusers update` takes the username as a positional argument, so
  `--username` changed nothing and auth failed with `bad auth`. Worth recording
  because "TLS handshake failed" sent the diagnosis in the wrong direction
  twice.

### Later that evening

Vickrey was **not** the project demoed at the Buildathon — a different project
was chosen, because this one was not ready to present. Everything after that is
consequence work on Vickrey itself.

### What changed once there was no clock

- **The ledger stopped overstating itself.** `/` had described the service as
  _"independently read the Hornet block"_, which is false in embedded mode
  because the ledger writes the block first. It now publishes an explicit
  `guarantee.independent_source`, and `tests/test_honesty.py` fails the build if
  that ever drifts.
- **Atlas went live**, after three failures that all presented as the same
  `tlsv1 alert internal error`: an empty network access list, a missing CA
  bundle, and a `dbusers update` invocation that silently changed nothing.
- **The field client went public.** It had only ever existed on a laptop.
  Vercel was tried first and deployed fine, but the account has Deployment
  Protection on, so it redirects to a login — unusable as a link. GitHub Pages
  needed no auth wall, so `pages.yml` now assembles `apps/site` at the root and
  `apps/field` at `/field/`.
- **The showcase now proves itself.** The nav leads to the live client, and the
  "What is actually running" section fetches `/health` and
  `/observations/recent` at page load, so the badges report the real state
  rather than the state at deploy time. When the ledger went down mid-write, the
  first draft of that badge reported the embedded block-store count as if it
  were the commons size — the same class of error the ledger had just been fixed
  for.

- **On-device inference remains unverified.** Still no offline phone run.

## Compliance

- [x] Public repo under Apache-2.0 (`LICENSE`).
- [ ] Confirm the October 6 repository/project timeline and disclose Veles code reuse in the DEV entry; organizer determines eligibility.
- [x] Publish an accessible demo video or deployed demo and link the code repository in the entry (YouTube film + GitHub Pages showcase live).
- [x] Docs: strategy, pitch, sponsors, build log.
- [x] DEV post published with `#devchallenge` + `#hf26challenge` (submitted October 11, 2026).
- [ ] Take it outside and write up how it went.

## Non-goals

- No auth on the demo ledger or tamper routes — demo scope, stated openly.
- No raw or precise-location data on-chain — the anchor is a commitment plus
  coarse location and species summary.
- No block submission from our services — in the local demo the stand-in
  anchor relay writes to a mock Hornet; the intended production path keeps
  writes on the patched upstream Messages API.
