# Testnet path — status (2026-11-08)

## Why the old node can't anchor

The old `vickrey-zcashd-testnet` deployment (zcashd v6.20.0, protocol 170150) was protocol-incompatible with the current testnet — NU6.3
(ZIP-258) raised the minimum to 170160 and **NU7** activated at testnet
height 4,465,026 requiring **170190** — and its chain data was abandoned
at ~14% sync. The container is gone and its `vickrey-testnet-data`
volume was deleted on 2026-11-08; `run_testnet.sh` would recreate both,
but the incompatibility stands. zcashd has no newer release (6.20.0 is
latest).

## Chain — synced, currently stopped

Zebra 7.0.0 is the supported node for the current network:
https://github.com/ZcashFoundation/zebra/releases/tag/v7.0.0

It runs as `vickrey-zebra-testnet` from `docker-compose.testnet.yml` —
localhost-bound RPC (`127.0.0.1:28632`, cookie auth in the `auth` volume),
health `127.0.0.1:28680`, 1.5 CPU / 3 GiB caps, isolated `testnet` network.
As of 2026-11-08 it reached ready status: `/ready` returned `ok` at tip
~4,597,477, matching the live network. Chain state persists in the
`vickrey-testnet_chain` volume, so restarts resume without re-syncing.

```bash
docker compose -f docker-compose.testnet.yml up -d zebra
docker logs -f vickrey-zebra-testnet
```

## Wallet — compat sidecar blocked on memory, currently stopped

The supported temporary route is Zebra 7 plus the
`zebra-compat-v1.3.0` zcashd sidecar
(https://zebra.zfnd.org/user/zcashd-compat.html,
https://github.com/ZcashFoundation/zcashd/releases/tag/zebra-compat-v1.3.0),
pinned to the local Zebra peer only — **transparent/Sapling only; Orchard
and Ironwood are expressly unsupported**. `vickrey-wallet-testnet`
(compat image, sha256-pinned download) peers solely with the local Zebra
(`/Zebra:7.0.0/` outbound, protocol 170190); RPC is
localhost-only with `walletrequirebackup=1`. The wallet config mounts
read-only at `/data/zcash.conf` inside its own volume; required fields are
`testnet=1 server=1 rpcbind=0.0.0.0 rpcallowip=0.0.0.0/0 rpcport=18232
rpcuser=… rpcpassword=… walletrequirebackup=1
allowdeprecated=z_getnewaddress exportdir=/data/exports` (provisioned
outside the repo, mode 600).

**Known blocker (found 2026-11-08):** the wallet cannot finish IBD under
its 2 GiB `mem_limit` — zcashd is OOM-killed by the container cgroup at
~2.06 GB anon RSS once per sync cycle (398 restarts observed). It was
only ~2.5% synced (height ~115k of ~4.6M). Restarting resumes from disk
but the memory ceiling makes completion unlikely at this limit; either
raise `mem_limit` substantially (the host has ~8 GB total shared with
other workloads) or wait for a Zebra-7-compatible Zallet. Both
testnet containers were stopped on 2026-11-08 during hackathon judging;
the regtest demo stack is unaffected.

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

Still before any public-testnet anchor: wallet IBD completes within its
memory budget (or is replaced by Zallet), the operator-side wallet
backup confirmation, test funding, and a memo round-trip. No
public-testnet anchor claim yet.
