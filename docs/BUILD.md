# Build log — Hacktoberfest 2026, Week 1: Touch Grass

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
refuses to send it. The public [GitHub Pages showcase](https://sneldao.github.io/vickrey/) embeds the YouTube film but hosts no inference or ledger service; the field client remains a locally run prototype. Everything below is the build plan against the _planned_
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
6. **Write-up.** DEV post per `PITCH.md` (submitted October 11, 2026); partner stack per
   `SPONSORS.md` (targets, not realised integrations).

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
