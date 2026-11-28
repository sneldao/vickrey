# Zcash public-testnet path — status (2026-11-28)

## Current disposition

The Zcash public-testnet experiment is **decommissioned on `nuncio-vultr`** and
remains outside the QIE critical path. No public-testnet anchor was ever
claimed.

On 2026-11-28 the stopped `vickrey-zebra-testnet` and
`vickrey-wallet-testnet` containers were removed, followed by the
`vickrey-testnet_chain` and `vickrey-testnet_wallet` volumes. This reclaimed
about 15 GB. The chain volume was reproducible public chain data and was not
backed up; reviving the node requires a fresh network sync.

Before deletion, the small unique testnet-wallet artifacts were encrypted and
copied off-host:

- artifact: `vickrey-testnet-wallet-20261128-124814.gpg`
- SHA-256: `d5ab974d7a2a57fa4f23bd914629c4a38fd6457b5eb28011db850755a1536362`
- verified contents: `testnet3/wallet.dat`, `exports/trust`, wallet
  configuration, and container metadata
- passphrase: the operator's existing local Vickrey recovery key, never in
  this repository

The archive was decrypted and its critical file list verified before the
source volume was deleted. Keep the recovery-key passphrase independently; a
lost passphrase makes the archive unreadable.

## Why the old zcashd node could not anchor

The old `vickrey-zcashd-testnet` deployment (zcashd v6.20.0, protocol 170150) was protocol-incompatible with the then-current testnet: NU6.3
(ZIP-258) raised the minimum to 170160 and NU7 activated at testnet height
4,465,026 requiring 170190. Its partial chain data was abandoned at about
14% sync and deleted on 2026-11-08. zcashd had no newer release; 6.20.0 was
the final line.

## Zebra/compat-wallet experiment — historical findings

Zebra 7.0.0 is the supported node line for that network:
https://github.com/ZcashFoundation/zebra/releases/tag/v7.0.0

The now-deleted `vickrey-zebra-testnet` container reached ready status on
2026-11-08 at tip ~4,597,477. Its configuration remains in
`docker-compose.testnet.yml`: localhost-bound RPC and health endpoints,
cookie authentication, resource caps, and an isolated Docker network.

The companion `zebra-compat-v1.3.0` zcashd wallet never became usable. Under
its 2 GiB container memory limit it was repeatedly OOM-killed during initial
block download at roughly 2.5% sync. The wallet also had not completed the
required operator backup ceremony. No funded testnet wallet is documented.

## If this path is revived

1. Re-create the Zebra container and accept a full public-chain resync:

   ```bash
   docker compose -f docker-compose.testnet.yml up -d zebra
   docker logs -f vickrey-zebra-testnet
   ```

2. Prefer a currently supported Zebra-compatible wallet rather than the old
   compat sidecar. If the old encrypted wallet artifact is restored, treat it
   as sensitive key material, use a fresh isolated volume, and expect a full
   rescan/sync. Generating a new wallet may be simpler because the deleted
   wallet had no documented funded addresses.
3. Do not run the interactive wallet-backup tool through an agent or shared
   log capture. It prints seed material; use a private operator terminal and
   never paste the phrase into chat.
4. Before any public-testnet anchor claim, complete wallet synchronization,
   backup confirmation, test funding, and a memo round-trip.
