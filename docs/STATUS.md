# Status — current build status (2026-11-28)

As of 2026-11-28, the QIE **testnet** Reality Receipts slice is implemented and
publicly smoke-tested end to end. This is still not a production release and no
mainnet funds have been used: QIE mainnet deployment is blocked on explicit
operator approval and funding. Verification, disclosure, backup and demo-
deployment work dated 2026-10-30 remains post-submission work; the recorded
ECATHON deadline was 2026-10-28.

## Current

| Claim                                             | Status                                                            | Evidence                                                                                                                                                                                                                                     |
| ------------------------------------------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Local Ed25519 seals + full-journal verification   | Hardened in source; browser-tested                                | `apps/field/trust.js`, `journal.js`, `integrity.js`; verification covers retained history even when the outbox is empty.                                                                                                                     |
| Atomic device persistence + recovery              | Hardened in source; browser-tested                                | IndexedDB transactions commit journal, outbox, schedule and signed head together; corruption and storage failures stop the flow explicitly.                                                                                                  |
| Signed journal heads + append-only corrections    | Built; unit/browser-tested                                        | Checkpoints cover head hash and entry count; corrections reference `supersedes` without rewriting sealed observations.                                                                                                                       |
| Encrypted backup `/2` + legacy `/1` restore       | Built; browser-tested                                             | AES-256-GCM backup authenticates journal, checkpoint and corrections before restore; old backups remain readable.                                                                                                                            |
| Mode-B memo anchor, fail-closed                   | Hardened in source; contract-tested                               | Durable pre-RPC state, worker leases, reconciliation and exact memo proof in `services/zanchor`; the deployed service still runs older source.                                                                                               |
| Receipt verification and single-record disclosure | Built; prior browser/service-tested                               | Verification still names its `service_wallet` source; it is not independent chain verification.                                                                                                                                              |
| Ledger v2 authority                               | Hardened in source; service-tested                                | Immutable submissions, raw-byte idempotency, version-bound verification, append-only attempts, bearer auth and quotas.                                                                                                                       |
| Privacy-preserving research export                | Built in source; unit-tested                                      | Darwin Core CSV with provenance, default location withholding and explicit consent; not yet published.                                                                                                                                       |
| Reality Receipts backend                          | QIE testnet path built; tests green                               | `services/receipts`: role-scoped FastAPI/SQLite workflow, deterministic remote context, signed verdicts, schema-v3 chain events and QIE escrow settlement. Suite: 53 passed.                                                                 |
| Reality Receipts frontend                         | Hardened and publicly deployed for QIE testnet                    | `apps/receipts`: controlled public metadata, local-only observation notes, strict verdict requests, network-aware amounts and explorer links; 12 unit tests and 11 browser tests pass. Hosted Nginx/API smoke test completed.                |
| Remote-evidence / satellite checks                | Deterministic demo adapter only                                   | No live satellite, sensor or external evidence provider is connected. Remote context is never cryptographic proof.                                                                                                                           |
| QIE Wallet / ID integration                       | Not built                                                         | Proposed for observer/sponsor identity and settlement.                                                                                                                                                                                       |
| QIE challenge, bounty, and payout contract        | Built and deployed on QIE testnet                                 | `RealityReceiptsEscrow` at `0xb5BAEF1117B00D1B230Bf806EBFb3FEe5F7c96Ee`; Forge tests pass. Mainnet deployment remains blocked on explicit operator approval and real funds.                                                                  |
| Shareable reality-receipt cards                   | Built; browser-tested; public testnet smoke run                   | Public receipt lookup, share URL, clipboard copy, redaction, 320px layout and print output pass locally against the real FastAPI demo. The hosted page rendered a complete QIE testnet receipt with three explorer transaction links.        |
| Public demo deployment                            | Live; QIE testnet receipts path smoke-tested                      | [HTTPS demo](https://vickrey.144.202.117.160.sslip.io/receipts/) serves the current receipts frontend/API through the same-origin Nginx route. The legacy regtest zanchor stack was decommissioned into encrypted backups on 2026-11-28.     |
| GitHub Pages frontend                             | Hardened static frontend published                                | Pages deployment for `2305b8d` succeeded and assembles the current field, explorer and receipts runtime assets. Live-surface smoke testing remains pending.                                                                                  |
| Old public ledger (`vickrey-ledger.fly.dev`)      | Legacy, embedded anchoring                                        | Earlier health reported `anchoring: embedded`, `independent_source: false`; not an independent verifier.                                                                                                                                     |
| Offline on-phone model                            | Not built                                                         | Server-hosted inference was previously verified.                                                                                                                                                                                             |
| Wallet/account login                              | Not built                                                         | Device key + service-held anchors.                                                                                                                                                                                                           |
| Shielded rewards                                  | Not built                                                         | No payouts.                                                                                                                                                                                                                                  |
| Encrypted backend backup + isolated recovery      | Restore process verified 2026-10-30; archive refreshed 2026-11-28 | Historical wallet/chain/receipt restore and sample memo proof passed in 2026-10-30. The 2026-11-28 decommissioning archive was decrypted and critical entries verified before deletion; see [DEPLOY_DEMO.md](DEPLOY_DEMO.md).                |
| Independent (service-free) memo proof             | Not built                                                         | The memo is read with the service wallet; verification is service-held.                                                                                                                                                                      |
| Public testnet anchoring                          | Decommissioned — never live                                       | Zebra testnet chain/wallet state was deleted on 2026-11-28 after a small encrypted wallet-artifact backup. Revival requires a fresh sync, compatible wallet, backup confirmation, funding and memo round-trip; see [TESTNET.md](TESTNET.md). |

## Verification evidence

Last local verification of this checkpoint:

- `PYTHONPATH=services/receipts python3 -m pytest services/receipts/tests -q` — 53 passed; covers metadata privacy, replay/quota ordering, remote idempotency, capture authorization, lock-time expiry, principal quotas, settlement consistency, verdict normalization, expired-state reporting, QIE adapter validation and chain-event persistence.
- `node --test apps/receipts/*.test.mjs` — 12 passed; covers canonical signatures, same-origin API configuration, allowlisted metadata, local sealing and receipt redaction.
- `RECEIPTS_UPSTREAM=http://127.0.0.1:18099 npm run test:browser` — 11 passed in Chromium, including corruption, aborted storage writes, backup restore, keyboard/focus, 320px layout, deterministic real-service receipt workflow, public lookup/share and print output.
- `forge test` in `services/receipts/contracts` — passed for the escrow contract suite.
- Public QIE testnet smoke — the hosted browser workflow completed challenge `e9365963-b3c1-44ec-8063-22c0b83f61bf`, rendered all three explorer links and paid 0.001 test QIE; see [QIE_SUBMISSION.md](QIE_SUBMISSION.md).
- The legacy regtest anchor and ledger checks above are historical checkpoint evidence. On 2026-11-28 the legacy regtest zanchor containers and data volumes were decommissioned after backup verification; the current public QIE receipts health and receipt lookup were re-checked successfully after that cleanup.

Docker is not installed in the local environment, so container builds and the
new Compose topology are **not locally verified**. CI run
[45488876759](https://github.com/sneldao/vickrey/actions/runs/45488876759) passed
for commit `2305b8d`: all seven jobs succeeded, including container packaging,
Compose validation, service/client contracts and the real-service browser gate.
GitHub Pages deployment
[45488876780](https://github.com/sneldao/vickrey/actions/runs/45488876780) also
succeeded.

## Remaining before release

1. Decide whether to approve and fund the QIE mainnet deployment. The testnet MVP is live, but the operator wallet has zero mainnet QIE and the deployment tooling intentionally refuses mainnet without explicit approval. Do not reuse testnet keys on mainnet.
2. Commit and publish the final source, then finish the submission package in [QIE_SUBMISSION.md](QIE_SUBMISSION.md) before 2026-11-30 23:59 CET.
3. Treat Zcash public-testnet anchoring as a future revival task, not a release blocker: it now requires a fresh chain sync, compatible wallet, backup confirmation, funding and memo round-trip. It is deliberately outside the QIE critical path.

## Historical record

The submission-era status table is preserved at the pre-cutoff revision:
[STATUS.md at fd88eb8](https://github.com/sneldao/vickrey/blob/fd88eb8/docs/STATUS.md).
Its "live" and "verified" claims are historical claims, not current proof —
they certify the code at that revision, not today's tree.
