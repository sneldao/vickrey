# Demo deployment runbook — QIE receipts + archived regtest zanchor

**Live at `https://vickrey.144.202.117.160.sslip.io`**. The current public
surface is the QIE-testnet-backed Reality Receipts demo:

- `vickrey-receipts` — FastAPI receipts service, internal to `vickrey-net`;
- `vickrey-demo-web` — nginx static site plus allowlisted same-origin proxies,
  localhost-only `127.0.0.1:18094` and the external Traefik router.

The legacy private regtest zanchor surface (`vickrey-demo-api`,
`vickrey-demo-miner`, `vickrey-zanchor-test`, and `vickrey-zcashd-regtest`)
was decommissioned on 2026-11-28 after the backup described below. Its
containers and data volumes are gone. The compose services remain in source
only behind the `legacy-zcash` profile so a normal deployment does not
recreate them. Legacy `/api/` zanchor routes may return 5xx while that
surface is absent; `/receipts/` is unaffected.

Pushing `main` republishes only the static GitHub Pages site; it does not
deploy or touch this host.

Both compose networks are external and must exist already: `vickrey-net` and
`coolify` (Traefik).

## Current operator steps

1. Keep the env file outside the repo, never committed:

   ```bash
   mkdir -p ~/.config/vickrey && chmod 700 ~/.config/vickrey
   # write ~/.config/vickrey/demo.env (mode 600) containing, for the
   # QIE receipts service:
   #   RECEIPTS_TOKENS_JSON=<compact demo-role JSON; claimant/observer subjects are QIE addresses>
   #   RECEIPTS_SETTLEMENT_ADAPTER=qie_escrow
   #   RECEIPTS_QIE_NETWORK=qie_testnet
   #   RECEIPTS_QIE_RPC_URL=https://rpc4testnet.qie.digital/
   #   RECEIPTS_QIE_CONTRACT_ADDRESS=<deployed escrow address>
   #   RECEIPTS_QIE_OPERATOR_PRIVATE_KEY=<testnet-only secret>
   #   RECEIPTS_MAX_BOUNTY_AMOUNT=1000000000000000
   #   RECEIPTS_QUOTA_PER_HOUR=24
   chmod 600 ~/.config/vickrey/demo.env
   ```

   Keep QIE testnet keys separate from any future mainnet keys. Zcash RPC and
   zaddr variables are needed only when restoring the archived legacy surface.

2. From the repo copy root on the host, build and start the current public
   services:

   ```bash
   VICKREY_DEMO_ENV=~/.config/vickrey/demo.env \
     docker compose -f docker-compose.demo.yml up -d --build receipts web
   ```

   Do not use `--profile legacy-zcash` unless the archived regtest state has
   first been restored.

3. Check readiness with non-secret output:

   ```bash
   docker exec vickrey-receipts python -c \
     "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8099/healthz').read().decode())"
   curl -sS 127.0.0.1:18094/healthz
   ```

   Health must report `settlement_adapter=qie_reality_receipts_escrow`,
   `settlement_network=qie_testnet`, and `real_funds=false` for the current
   testnet demo. After Traefik issuance, complete one browser workflow and
   confirm three explorer links render.

## Optional QIE mainnet proof service

The interactive public demo must remain testnet-only: its documented demo
credentials would otherwise let strangers move real funds. The optional mainnet
service is therefore an operator-controlled proof service with separate strong
bearer tokens, a localhost-only mutation port, and nginx exposure limited to
`GET /mainnet/healthz` and `GET /mainnet/v1/receipts/{id}`.

1. Create `~/.config/vickrey/mainnet.env` outside the repo, mode 600. It must
   use fresh strong tokens and fresh mainnet-only QIE keys, never the documented
   demo credentials or testnet keys. Required receipts variables:

   ```bash
   RECEIPTS_TOKENS_JSON=<compact strong-token role JSON; claimant subject is the operator QIE address, observer subject is the payout QIE address>
   RECEIPTS_VERIFIER_PUBLIC_KEY=<operator-generated Ed25519 public key hex>
   RECEIPTS_SETTLEMENT_ADAPTER=qie_escrow
   RECEIPTS_QIE_NETWORK=qie_mainnet
   RECEIPTS_QIE_RPC_URL=https://rpc1mainnet.qie.digital/
   RECEIPTS_QIE_CHAIN_ID=1990
   RECEIPTS_QIE_EXPLORER_URL=https://mainnet.qie.digital/
   RECEIPTS_QIE_CONTRACT_ADDRESS=<fresh mainnet escrow address>
   RECEIPTS_QIE_OPERATOR_PRIVATE_KEY=<mainnet-only secret>
   RECEIPTS_QIE_MAINNET_ACK=I_APPROVE_REAL_QIE_MAINNET_FUNDS
   RECEIPTS_MAX_BOUNTY_AMOUNT=1000000000000000
   RECEIPTS_QUOTA_PER_HOUR=12
   ```

   Keep the corresponding verifier private key and per-role tokens only in a
   separate operator-local file. Do not place them in the public browser config,
   repository, docs, shell history, or submission text.

2. Build and start the optional service with the compose override:

   ```bash
   VICKREY_DEMO_ENV=~/.config/vickrey/demo.env \
   VICKREY_MAINNET_ENV=~/.config/vickrey/mainnet.env \
     docker compose -f docker-compose.demo.yml -f docker-compose.mainnet.yml \
     up -d --build receipts-mainnet
   ```

   Its internal health must report `settlement_network=qie_mainnet` and
   `real_funds=true` before any workflow is attempted.

3. Run one controlled proof through the localhost-only port. From the operator
   machine, forward the port and use the non-secret-writing runner:

   ```bash
   ssh -L 18095:127.0.0.1:18095 <host>
   # in another shell, with the operator-local token/private-key environment loaded:
   python services/receipts/scripts/run_qie_flow.py \
     --base-url http://127.0.0.1:18095 \
     --approve-mainnet \
     --output /tmp/vickrey-mainnet-proof.json
   ```

   The script prints only challenge, receipt, transaction and explorer metadata.
   It writes the local sealed record and public receipt without private keys or
   bearer tokens.

4. Rebuild/start web so nginx includes the read-only mainnet routes. Public
   receipt lookup can then use:

   ```text
   https://<host>/receipts/index.html?receipts=/mainnet&challenge=<challenge-id>
   ```

   `POST /mainnet/...` is intentionally not exposed. If the mainnet service is
   absent, those routes may return 502/404 but the testnet demo must remain up.

## Logging policy

The receipts API image runs Uvicorn with `--no-access-log`; application
failures record only event names and exception types. nginx suppresses access
and error logs for the entire demo server, including explorer query strings.
The inspected shared Traefik configuration does not enable access logging.
Historical logs are not erased, and adding another proxy or CDN requires
checking its logging policy. Receipt paths must not be exported to logs.

## 2026-11-28 legacy decommissioning record

Before deletion, the legacy regtest zanchor stack was backed up and the backup
was copied to operator-local backup storage. The source containers and these
volumes were then removed:

- `vickrey-regtest-data` — regtest chain and wallet;
- `vickrey-demo_vickrey_demo_receipts` — zanchor receipt database.

The encrypted cold backup is:

- artifact: `vickrey-zanchor-cold-20261128-125629.gpg`
- size: 536,743,008 bytes
- SHA-256: `41ea9cb4af98e48312a5baa3494bc7e20657d116776c305b7b0bba83916bb227`
- contents verified by decrypting the archive stream and checking the critical
  entries: `node/zcash.conf`, `node/regtest/wallet.dat`, regtest blocks and
  chainstate, `receipts/zanchor.db`, `settings/demo.env`, and
  `metadata/node.json`
- passphrase: the operator's existing local Vickrey recovery key, never in
  this repository

This was an archive-integrity verification, not a fresh full node restore. The
same cold-backup procedure had a successful isolated restore drill on
2026-10-30. During that drill a restored node and API came up healthy, a known
receipt returned `transaction_verified`/`commitment_verified: true`, and the
receipt DB passed `PRAGMA quick_check`.

Two supplementary archives were made because the original zcashd image tag was
no longer present in the host image store even though the stopped container
still existed:

- `vickrey-zcashd-runtime-20261128.tar.gz` — copied `zcashd` and `zcash-cli`
  binaries plus `Dockerfile.zcashd`; SHA-256
  `af9b5e8deebcc63d50136117bc96a9e3662952d82fa9f6462d8d98681551c913`
- `vickrey-legacy-container-metadata-20261128-metadata.gpg` — encrypted Docker
  inspect metadata for the legacy containers and available service images;
  SHA-256 `a239f44bae8ea2c883b5e33fc67a916bc501bc1041809c6a9a1086722076b335`

The temporary copy of the recovery passphrase used on the host was removed
after the backup copies were hash-verified locally.

## Restoring the archived legacy surface

Restore only when there is a concrete need; the QIE receipts demo does not
depend on this surface.

1. Ensure the recovery-key passphrase is available locally. Never paste seed
   phrases, wallet exports, plaintext `demo.env`, receipt ids, or backup keys
   into chat or shared logs.
2. Decrypt `vickrey-zanchor-cold-20261128-125629.gpg` into fresh task-only
   volumes, not over any active volume. The archive layout is `node/`,
   `receipts/`, `settings/demo.env`, and `metadata/`.
3. Recreate a zcashd runtime image. Prefer rebuilding from
   `services/zanchor/docker/Dockerfile.zcashd`; if that is impractical, use the
   preserved binaries in `vickrey-zcashd-runtime-20261128.tar.gz` with the same
   Ubuntu 24.04 runtime dependencies documented in that Dockerfile.
4. Recreate the node using `metadata/node.json` and the archived runtime
   flags, initially isolated (`-connect=0 -discover=0`, no public ports) for
   validation. Let it load cleanly before stopping or snapshotting again.
5. Restore the receipts database into a fresh `vickrey_demo_receipts`-shaped
   volume, configure the archived `demo.env`, then enable the compose profile:

   ```bash
   VICKREY_DEMO_ENV=~/.config/vickrey/demo.env \
     docker compose -f docker-compose.demo.yml --profile legacy-zcash \
     up -d --build api miner
   ```

6. Verify on localhost first: mode B, regtest network, node ok, miner blocks
   advancing, and `GET /receipts/{id}/verify` returning
   `transaction_verified`/`commitment_verified` for a known confirmed receipt.
   A lost in-flight operation is never re-sent automatically; operator
   reconciliation is required and no new transaction should be fabricated.

The legacy nginx zanchor proxy upstream is deliberately resolved dynamically.
The web container can therefore start while the archived zanchor service is
absent; legacy `/api/` requests fail closed without taking down `/receipts/`.
