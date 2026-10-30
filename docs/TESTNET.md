# Testnet path — status (2026-10-30)

## Why the old node can't anchor

The existing `vickrey-zcashd-testnet` (zcashd v6.20.0, protocol 170150) sits
at height 0 with 0 peers — it is protocol-incompatible with the current
testnet. NU6.3 (ZIP-258) raised the minimum to 170160, and **NU7** activated
at testnet height 4,465,026 requiring **170190**. The old daemon is
incompatible with both. zcashd has no newer release (6.20.0 is latest).

## Chain — syncing, not done

Zebra 7.0.0 is the supported node for the current network:
https://github.com/ZcashFoundation/zebra/releases/tag/v7.0.0

It runs as `vickrey-zebra-testnet` from `docker-compose.testnet.yml` —
localhost-bound RPC (`127.0.0.1:28632`, cookie auth in the `auth` volume),
health `127.0.0.1:28680`, 1.5 CPU / 3 GiB caps, isolated `testnet` network.
Sync is in progress and has not reached ready status; `/ready` HTTP 200 +
tip currency are the completion criteria.

```bash
docker compose -f docker-compose.testnet.yml up -d zebra
docker logs -f vickrey-zebra-testnet
```

## Wallet — compat sidecar running, syncing (not live)

The supported temporary route is running: Zebra 7 plus the
`zebra-compat-v1.3.0` zcashd sidecar
(https://zebra.zfnd.org/user/zcashd-compat.html,
https://github.com/ZcashFoundation/zcashd/releases/tag/zebra-compat-v1.3.0),
pinned to the local Zebra peer only — **transparent/Sapling only; Orchard
and Ironwood are expressly unsupported**. `vickrey-wallet-testnet`
(compat image, sha256-pinned download) peers solely with the local Zebra
(`/Zebra:7.0.0/` outbound, protocol 170190) and is syncing; RPC is
localhost-only with `walletrequirebackup=1`. The wallet config mounts
read-only at `/data/zcash.conf` inside its own volume; required fields are
`testnet=1 server=1 rpcbind=0.0.0.0 rpcallowip=0.0.0.0/0 rpcport=18232
rpcuser=… rpcpassword=… walletrequirebackup=1
allowdeprecated=z_getnewaddress exportdir=/data/exports` (provisioned
outside the repo, mode 600).

### Operator wallet backup (human step — required by the daemon)

The daemon's `walletrequirebackup=1` refuses new key and address generation
until the operator confirms a backup. Run it yourself in a private terminal:

    ssh -t nuncio-vultr 'docker exec -it vickrey-wallet-testnet zcashd-wallet-tool --datadir=/data --testnet'

This is the unmodified upstream `wallet_tool.rs` (see
`services/zanchor/docker/wallet-tool/README.md`): it prints the seed
phrase, asks a word-challenge, and writes a plaintext wallet export under
`/data/exports` (mode-700 dir inside the wallet volume — protect that
file). **Never paste the phrase into chat or a shared terminal.** This
seed is separate from the regtest backend's recovery key. Do not run this
command through an agent or shared log capture. Modern Zallet awaits a Zebra-7-compatible release — the
current bridge is the supported temporary Sapling path using the app's
existing RPC methods.

Still before any public-testnet anchor: both syncs complete, the
operator-side wallet backup confirmation, test funding, and a memo
round-trip. No public-testnet anchor claim yet.
