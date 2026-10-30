# Status — current build status (2026-10-30)

As of 2026-10-30. Verification, disclosure, backup and demo-deployment work on
this date is **post-submission**; the recorded hackathon deadline was
2026-10-28. Older claims about this repo describe the pre-2026-10-30
revision — see the historical snapshot linked at the bottom — and do not
certify code changed since.

## Current

| Claim                                                                                                          | Status                                                 | Evidence                                                                                                                                                                                           |
| -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Local Ed25519 seals + hash chain                                                                               | Built                                                  | `apps/field/trust.js`; exercised in browser QA                                                                                                                                                     |
| Mode-B memo anchor, fail-closed (no downgrade)                                                                 | Built                                                  | `services/zanchor/app/main.py`                                                                                                                                                                     |
| Receipt verification (txid/height/confirmations/memo, `service_wallet` source)                                 | Built                                                  | `GET /receipts/{id}/verify`; contract tests                                                                                                                                                        |
| Single-record disclosure (local signature check + server memo read; no private/viewing/spending keys exported) | Local verifier browser-tested; service contract-tested | `POST /receipts/{id}/disclosure` + `apps/field/disclosure.js`; browser QA 2026-10-30: file import verified signature + hash, tampered file rejected                                                |
| Encrypted backup + empty-device restore                                                                        | Built, browser-verified                                | `apps/field/backup.js`; browser QA 2026-10-30: export encrypted (no plaintext), wrong passphrase refused without mutation, correct restore reproduced all three journal hashes + device public key |
| Mobile layout                                                                                                  | Checked                                                | field + explorer at 390px: no horizontal overflow                                                                                                                                                  |
| Public regtest deployment                                                                                      | Prepared, **not launched**                             | `docker-compose.demo.yml`, `docs/DEPLOY_DEMO.md`; compose images not yet built; remote host unreachable (SSH TCP timeouts) at attempt                                                              |
| Live end-to-end anchor on the real regtest node                                                                | **Not yet verified**                                   | blocked on the same SSH timeout; memo output shape is contract-tested only                                                                                                                         |
| Old public ledger (`vickrey-ledger.fly.dev`)                                                                   | Legacy, embedded anchoring                             | `/health` answered `anchoring: embedded`, `independent_source: false` at earlier check — not an independent verifier                                                                               |
| Offline on-phone model                                                                                         | Not built                                              | server-hosted inference previously verified                                                                                                                                                        |
| Wallet/account login                                                                                           | Not built                                              | device key + service-held anchors                                                                                                                                                                  |
| Shielded rewards                                                                                               | Not built                                              |                                                                                                                                                                                                    |
| Independent (service-free) memo proof                                                                          | Not built                                              | the memo is read with the service wallet; verification is service-held                                                                                                                             |

## Test evidence actually run

- `PYTHONPATH=services/zanchor python3 -m pytest services/zanchor/tests/test_contract.py -q` — 32 passed
- `node --test apps/field/*.test.mjs apps/explorer/app.test.mjs` — 142 passed
- `node --test apps/field/backup.test.mjs apps/field/disclosure.test.mjs apps/field/app.test.mjs` — 41 passed
- `bash -n scripts/demo_zcash.sh` — clean

## Historical record

The submission-era status table is preserved at the pre-cutoff revision:
[STATUS.md at fd88eb8](https://github.com/sneldao/vickrey/blob/fd88eb8/docs/STATUS.md).
Its "live" and "verified" claims are historical claims, not current proof —
they certify the code at that revision, not today's tree.
