# Status — current build status (2026-11-24)

As of 2026-11-24. This tree is a **release-candidate checkpoint, not a deployed
release**. The public demo and GitHub Pages still run earlier revisions; the
hardened source below has not been rebuilt, published or smoke-tested as a new
deployment. Verification, disclosure, backup and demo-deployment work dated
2026-10-30 remains post-submission work; the recorded hackathon deadline was
2026-10-28.

## Current

| Claim                                             | Status                                         | Evidence                                                                                                                                                                                                                                                  |
| ------------------------------------------------- | ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Local Ed25519 seals + full-journal verification   | Hardened in source; browser-tested             | `apps/field/trust.js`, `journal.js`, `integrity.js`; verification covers retained history even when the outbox is empty.                                                                                                                                  |
| Atomic device persistence + recovery              | Hardened in source; browser-tested             | IndexedDB transactions commit journal, outbox, schedule and signed head together; corruption and storage failures stop the flow explicitly.                                                                                                               |
| Signed journal heads + append-only corrections    | Built; unit/browser-tested                     | Checkpoints cover head hash and entry count; corrections reference `supersedes` without rewriting sealed observations.                                                                                                                                    |
| Encrypted backup `/2` + legacy `/1` restore       | Built; browser-tested                          | AES-256-GCM backup authenticates journal, checkpoint and corrections before restore; old backups remain readable.                                                                                                                                         |
| Mode-B memo anchor, fail-closed                   | Hardened in source; contract-tested            | Durable pre-RPC state, worker leases, reconciliation and exact memo proof in `services/zanchor`; the deployed service still runs older source.                                                                                                            |
| Receipt verification and single-record disclosure | Built; prior browser/service-tested            | Verification still names its `service_wallet` source; it is not independent chain verification.                                                                                                                                                           |
| Ledger v2 authority                               | Hardened in source; service-tested             | Immutable submissions, raw-byte idempotency, version-bound verification, append-only attempts, bearer auth and quotas.                                                                                                                                    |
| Privacy-preserving research export                | Built in source; unit-tested                   | Darwin Core CSV with provenance, default location withholding and explicit consent; not yet published.                                                                                                                                                    |
| Reality Receipts backend                          | Review remediation complete; tests green       | `services/receipts`: role-scoped FastAPI/SQLite workflow, deterministic remote context, signed verdicts and simulated settlement. Suite: 49 passed, including 18 independent-review regressions.                                                          |
| Reality Receipts frontend                         | Hardened in source; same-origin browser-tested | `apps/receipts`: controlled public metadata, local-only observation notes and strict verdict requests; 12 unit tests and 2 real-service browser tests pass. Nginx, Docker, navigation and Pages wiring are present; deployment is pending.                |
| Remote-evidence / satellite checks                | Deterministic demo adapter only                | No live satellite, sensor or external evidence provider is connected. Remote context is never cryptographic proof.                                                                                                                                        |
| QIE Wallet / ID integration                       | Not built                                      | Proposed for observer/sponsor identity and settlement.                                                                                                                                                                                                    |
| QIE challenge, bounty, and payout contract        | Not built                                      | No escrow, mainnet transaction or real-funds settlement exists.                                                                                                                                                                                           |
| Shareable reality-receipt cards                   | Built in source; browser-tested; not deployed  | Public receipt lookup, share URL, clipboard copy, redaction, 320px layout and print output pass against the real local FastAPI demo through the same-origin test proxy.                                                                                   |
| Public regtest deployment                         | Previously live; current source not deployed   | [HTTPS demo](https://vickrey.144.202.117.160.sslip.io/) ran API source 258c568 and passed earlier end-to-end checks. It does not certify this tree.                                                                                                       |
| GitHub Pages frontend                             | Older revision live                            | Published field HTML still lacks the new `integrity.js`, `storage.js` and `export.js`; current hardened source is not published.                                                                                                                          |
| Old public ledger (`vickrey-ledger.fly.dev`)      | Legacy, embedded anchoring                     | Earlier health reported `anchoring: embedded`, `independent_source: false`; not an independent verifier.                                                                                                                                                  |
| Offline on-phone model                            | Not built                                      | Server-hosted inference was previously verified.                                                                                                                                                                                                          |
| Wallet/account login                              | Not built                                      | Device key + service-held anchors.                                                                                                                                                                                                                        |
| Shielded rewards                                  | Not built                                      | No payouts.                                                                                                                                                                                                                                               |
| Encrypted backend backup + isolated recovery      | Verified on 2026-10-30                         | Historical wallet/chain/receipt restore and sample memo proof passed; see [DEPLOY_DEMO.md](DEPLOY_DEMO.md).                                                                                                                                               |
| Independent (service-free) memo proof             | Not built                                      | The memo is read with the service wallet; verification is service-held.                                                                                                                                                                                   |
| Public testnet anchoring                          | Blocked — not live                             | Zebra 7 synced to tip and was stopped on 2026-11-08; the compat Sapling wallet cannot finish IBD inside its 2 GiB limit. Needs a compatible wallet or more memory, then backup confirmation, funding and a memo round-trip; see [TESTNET.md](TESTNET.md). |

## Verification evidence

Last local verification of this checkpoint:

- `node --test apps/field/*.test.mjs apps/explorer/*.test.mjs apps/receipts/*.test.mjs` — 181 passed.
- `RECEIPTS_UPSTREAM=http://127.0.0.1:18099 npm run test:browser` — 11 passed in Chromium, including corruption, aborted storage writes, backup restore, keyboard/focus, 320px layout, real-service receipt workflow, public lookup/share and print output.
- `npm run test:browser` without `RECEIPTS_UPSTREAM` — 9 passed and the 2 real-service scenarios skipped cleanly.
- Ledger suite — 132 passed, 1 skipped.
- `PYTHONPATH=services/zanchor python3 -m pytest services/zanchor/tests -q` — 56 passed.
- `PYTHONPATH=services/receipts python3 -m pytest services/receipts/tests -q` — 49 passed after independent-review remediation; covers metadata privacy, replay/quota ordering, remote idempotency, capture authorization, lock-time expiry, principal quotas, settlement consistency, verdict normalization, expired-state reporting and v1 quota migration.
- `PYTHONPATH=services/receipts node --test apps/receipts/*.test.mjs` — 12 passed; covers canonical signatures, same-origin API configuration, allowlisted metadata, local sealing and receipt redaction.
- Workflow/Compose YAML parsing, shell syntax, Python compilation and `git diff --check` passed.
- Changed-file pre-commit hooks and GitHub Pages runtime-asset assembly checks passed.
- The existing regtest anchor and legacy ledger health endpoints were reachable during this checkpoint; that does not verify the current source.

Docker is not installed in the local environment, so container builds and the
new Compose topology are **not locally verified**. CI contains the build jobs,
but no successful CI run is claimed here.

## Remaining before release

1. Run CI on this tree and verify container builds, Compose/Nginx configuration and the same-origin receipts route.
2. Deploy and smoke-test the hardened source before changing any public URL or Pages claim.
3. Complete the external public-testnet wallet, backup, funding and memo round-trip work. This remains blocked independently of the code checkpoint.

## Historical record

The submission-era status table is preserved at the pre-cutoff revision:
[STATUS.md at fd88eb8](https://github.com/sneldao/vickrey/blob/fd88eb8/docs/STATUS.md).
Its "live" and "verified" claims are historical claims, not current proof —
they certify the code at that revision, not today's tree.
