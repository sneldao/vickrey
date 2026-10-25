# Status — the one honest table

This is the **only** place status claims live. Every other document — README,
STRATEGY, BUILD, archive — links here instead of restating what is verified.
When reality moves, this file moves; nothing else needs correcting.

_Ledger last checked live: 2026-10-15 against `https://vickrey-ledger.fly.dev`
(`/health` → `anchoring: embedded`, `observations: true`, `context: true`).
Tests on `main`: 91 JS + 119 ledger, all passing._

## Vocabulary

- **Live** — running on public infrastructure right now; checkable by a stranger.
- **Verified** — proven end-to-end locally, with tests; the exact run is reproducible.
- **Verified once** — a real run that happened, recorded honestly, not yet continuous.
- **Partial** — some of it works; the row says which part.
- **Scaffold** — code exists and is labelled; it has never driven anything.
- **Not built** — a plan. Nothing more.

## The table

| Claim                                                                                                         | Status                           | Evidence / how to check                                                                                                                                                                                                       |
| ------------------------------------------------------------------------------------------------------------- | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Field loop: seal → chain → tamper → sync refused → restore → `VERIFIED`                                       | **Live**                         | <https://sneldao.github.io/vickrey/field/> driven from a cold start on the deployed ledger; also reproducible via `scripts/demo_field.sh`                                                                                     |
| Ledger service                                                                                                | **Live**                         | <https://vickrey-ledger.fly.dev>, one machine, `HORNET_EMBEDDED=1`; `/health` reports real state                                                                                                                              |
| Embedded-block caveat: the ledger writes the block it later reads, so the two-source check is data-layer only | **Live, with the stated caveat** | `/health` publishes `independent_source: false`; `tests/test_honesty.py` fails the build if that ever drifts. See [OPS.md](OPS.md#what-embedded-mode-changes)                                                                 |
| Atlas commons (commitments + coarse areas, no raw records)                                                    | **Live**                         | M0 cluster; `/observations/recent` returns real anchored records; `seed_commons.py --verify` re-checks every stored signature                                                                                                 |
| Tavily web context, shown beside (never inside) a record                                                      | **Live**                         | `/health` → `context: true`; three rules enforced by tests — never sealed, outage never un-verifies, query never carries a coordinate                                                                                         |
| SQLite copy on Fly survives a redeploy                                                                        | **Not built**                    | No volume attached (creating one needs a payment method); the store resets on every `fly deploy`. `blocks_registered` is a live counter you can watch reset                                                                   |
| Real Hornet / public IOTA Messages API anchor                                                                 | **Not built**                    | Local demos use `mock_hornet.py` + `anchor_relay.py` or the embedded store; the public-tangle path is unrun                                                                                                                   |
| On-device, offline model run (the opening vision)                                                             | **Not built**                    | No phone run has ever happened. See the next row for what _did_ run                                                                                                                                                           |
| Open-weight model identification through the field client                                                     | **Verified once**                | Gemma 3 4B (Ollama, CPU VM, and once over a private SSH tunnel) returned "Robin" on a credited Wikimedia photo; self-reported confidence 0.95, ~20 s. **Server-hosted: the photo left the device.** Not offline, not on-phone |
| Confidence meaning                                                                                            | **Structural caveat**            | A model's confidence is its own score, not calibrated accuracy; the record seals the observer's decision, not the model's claim                                                                                               |
| Ed25519 seal + hash-chained journal + outbox split                                                            | **Verified**                     | 91 JS tests; the sample walk seals through the real logbook, so hashes and signatures are genuine                                                                                                                             |
| Tamper detection, both shapes                                                                                 | **Verified**                     | Field client: cracked seal refuses sync. Reused ledger demo route: edited application copy → `PAYLOAD_MISMATCH` side by side                                                                                                  |
| Sample walk (Dalston: ivy, corrected robin, hawthorn)                                                         | **Live**                         | Offered on an empty device; plates are self-drawn SVG data URIs, so no camera, network, or stock imagery is needed                                                                                                            |
| Temporal durable sync workflow                                                                                | **Scaffold**                     | `services/sync` exists, never run                                                                                                                                                                                             |
| Darwin Core export                                                                                            | **Not built**                    | Planned interop layer; see [STRATEGY.md](STRATEGY.md)                                                                                                                                                                         |
| Showcase page truthfulness                                                                                    | **Live**                         | "What is actually running" fetches `/health` at page load; the page cannot claim what has stopped being true                                                                                                                  |

## ECATHON (Zcash privacy hackathon — submission due 2026-10-28 23:59 UTC)

Hacktoberfest Week 1 was milestone 1; ECATHON is the current target. Plan:
[ECATHON.md](ECATHON.md). Everything in this table is **Not built** as of
2026-10-25.

| Claim                                                                | Status        | Evidence / how to check                                                                                         |
| -------------------------------------------------------------------- | ------------- | --------------------------------------------------------------------------------------------------------------- |
| Whole repo written in the Sep 28 – Oct 28 build window               | **Verified**  | First commit `ced42d0` dated 2026-10-06 17:09 +0100; `git log --reverse --date=iso` — no pre-window code exists |
| Zcash node (mainnet or testnet) running locally                      | **Not built** | `docker-compose` entry for `zcashd` + synced state                                                              |
| Shielded beacon anchor: commitment sealed, unidentifiable tx         | **Not built** | `services/zanchor`; a block-explorer view of the anchor tx must reveal nothing about species, area, or observer |
| Commitment carried in encrypted shielded memo (stretch)              | **Not built** | Same service, memo mode; verifier decrypts with viewing key                                                     |
| Per-commitment note burn → unique nullifier (replay = double-spend)  | **Not built** | One dedicated shielded note per commitment; replaying an anchor must be rejected as a double-spend              |
| Verifier receipt + selective disclosure via viewing key              | **Not built** | Receipt endpoint; disclosure flow documented in the threat model                                                |
| Batched, jittered anchor scheduling (timing-leak mitigation)         | **Not built** | Scheduler in the field client / ledger; interval + jitter documented                                            |
| Shielded TAZ field rewards (stretch)                                 | **Not built** | Verified-observation payout to a shielded address, memo = observation id, jittered                              |
| Threat model: timing / memo / address-reuse / verifier trust         | **Not built** | `docs/PRIVACY.md` (or inside ECATHON.md); names each leak and its mitigation                                    |
| End-to-end demo: seal → shielded anchor → crack → "nothing on-chain" | **Not built** | `scripts/demo_zcash.sh`; demo video under 2 min                                                                 |

## What the product claims about itself

- **Integrity is not accuracy.** The ledger proves a record was not altered after
  anchoring. It never proves the ID was right, nor that the observation was honest.
- **The anchor is a commitment**, never the observation: hash + signature +
  timestamp + coarse area + species summary. No photos, no notes, no precise GPS.
- **The opening vision is the plan, not the demo.** "No signal, on the phone" is
  the architecture being aimed at; what is demonstrated is server-hosted
  inference and a real seal — see the table.
