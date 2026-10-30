# Demo deployment runbook — private regtest

**Live since 2026-10-30** at `https://vickrey.144.202.117.160.sslip.io` —
`vickrey-demo-api`, `vickrey-demo-miner` and `vickrey-demo-web` all running;
the old `vickrey-zanchor-test` / `vickrey-zcashd-regtest` containers are
unchanged. The runbook below is the record of how it was brought up and how
to rebuild it. Pushing `main` republishes only the static GitHub Pages site
(the workflow patches the generated `config.js` to point at this live API);
it does not deploy or touch the node.

- `vickrey-demo-api` — zanchor mode B, `ZANCHOR_EXPECTED_NETWORK=regtest`
  (the service checks the configured node's reported network before each
  anchor and refuses mismatches; this is a configured-deployment guard, not
  an absolute security guarantee), receipts on the named volume
  `vickrey_demo_receipts`, localhost-only `127.0.0.1:18093`.
- `vickrey-demo-miner` — `app.mine_regtest`; refuses unless the node reports
  `regtest`, checked before every block; publishes no ports at all.
- `vickrey-demo-web` — nginx static + allowlisted `/api/` proxy on
  `127.0.0.1:18094`; Traefik router `vickrey-demo` on the external `coolify`
  network.

Both compose networks are external and must exist already: `vickrey-net`
(the node's network) and `coolify` (Traefik).

## Operator steps

1. Env file outside the repo, never committed:

   ```bash
   mkdir -p ~/.config/vickrey && chmod 700 ~/.config/vickrey
   # write ~/.config/vickrey/demo.env (mode 600) containing ONLY:
   #   ZANCHOR_RPC=http://user:pass@<zcashd-on-vickrey-net>:28432
   #   ZANCHOR_ANCHOR_ZADDR=<dedicated zaddr, copied from vickrey-zanchor-test env>
   #   ZANCHOR_RECIPIENT_ZADDR=<dedicated zaddr, same source>
   #   ZANCHOR_CORS_ORIGINS=https://vickrey.144.202.117.160.sslip.io,https://sneldao.github.io
   chmod 600 ~/.config/vickrey/demo.env
   ```

   Do not fund or reset anything; the existing wallet already holds the
   dedicated addresses.

2. From the repo copy root on the host, build all three images:

   ```bash
   VICKREY_DEMO_ENV=~/.config/vickrey/demo.env \
     docker compose -f docker-compose.demo.yml build api miner web
   ```

3. Start the private pieces only (both bind localhost — nothing public):

   ```bash
   VICKREY_DEMO_ENV=~/.config/vickrey/demo.env \
     docker compose -f docker-compose.demo.yml up -d api miner
   ```

4. Check readiness (all output is non-secret):

   ```bash
   curl -s 127.0.0.1:18093/health          # {"status":"ok","node":"ok","mode":"B","network":"regtest",...}
   docker logs vickrey-demo-miner --tail 5 # "mining one regtest block every 3s"
   docker exec vickrey-demo-api ls -l /svc/data   # inspect volume contents
   ```

## Receipt persistence and recovery

`vickrey_demo_receipts` is a named Docker volume — unlike the old API's
ephemeral container storage, receipts survive `up -d --force-recreate`. No
receipts are migrated from the old service; the demo DB starts empty.
Compose prefixes the project name, so refer to volumes through compose
rather than a hardcoded name:

```bash
VICKREY_DEMO_ENV=~/.config/vickrey/demo.env \
  docker compose -f docker-compose.demo.yml run --rm --no-deps api \
  ls -l /svc/data                          # list the volume's contents
```

### Snapshot the receipt database

The service exposes an online snapshot (SQLite backup API) that works while
the API is running:

```bash
VICKREY_DEMO_ENV=~/.config/vickrey/demo.env \
  docker compose -f docker-compose.demo.yml exec api \
  python -m app.backup_receipts --output /svc/data/receipt-snapshot.db
```

`--output` must be a fresh path — existing files are refused, and the file
is created mode 600 inside the receipts volume. **The snapshot is plaintext
sensitive data: receipt ids are bearer capabilities and commitments link to
real observations. Encrypt it before moving it off the host.** This command
covers the receipt book only; the cold-backup procedure below also includes
the node's wallet and chain state.

### Restore and re-verify (isolated service only)

Never overwrite the live database. To test a restore:

1. Copy the (decrypted) snapshot into a NEW empty isolated service's data
   volume — e.g. a scratch `vickrey-demo-api` on another host or a `run --rm`
   container with a fresh volume, pointed at the same regtest node.
2. Start it and call `GET /receipts/{id}/verify` on a known receipt: the
   fresh node read should return `transaction_verified`/`commitment_verified`
   for confirmed mode-B anchors.

Receipts the live service wrote _after_ the snapshot are absent by design;
an anchor whose operation was in flight at snapshot time stays `queued`
until the new service's worker advances it — and a lost operation is never
re-sent automatically (operator reconciliation required; no new transaction
is fabricated).

## Live-verification gate (before any web publication)

Complete all of these on the private binds first; only then is `up -d web`
justified:

1. `/health` shows `mode B`, `network regtest`, `node ok`.
2. Miner logs confirm blocks advancing.
3. Seal + anchor a sample entry from a locally served field client pointed
   at `127.0.0.1:18093` (or via a port forward).
4. `GET /receipts/{id}/verify` returns `commitment_verified: true` with
   `network: regtest`, and `POST …/disclosure` returns the receipt + verification metadata; the field client assembles the shareable bundle locally.
5. Then `VICKREY_DEMO_ENV=~/.config/vickrey/demo.env docker compose -f docker-compose.demo.yml up -d web`
   and let Traefik issue the cert.

## Logging policy

The API image runs Uvicorn with `--no-access-log`; application failures
record only event names and exception types. nginx suppresses access and
error logs for the entire demo server, including explorer query strings.
The inspected shared Traefik configuration does not enable access logging.
Historical logs are not erased, and adding another proxy or CDN requires
checking its logging policy. Receipt paths must not be exported to logs.

## Cold backup and recovery (restore verified)

`scripts/backup_zanchor.sh KEY_FILE OUTPUT.gpg` on the host takes a
consistent cold snapshot: it stops the demo API and the old zanchor
service, refuses if the receipts queue is not empty (queued/broadcast),
stops the miner then the node, streams a read-only tar of the node
volume (chain + wallet), the receipts volume and `~/.config/vickrey/demo.env`
through GPG AES-256 symmetric encryption, and places the result atomically.
The archive is an exact allowlist: `node/` (chain + wallet), `receipts/`,
`settings/demo.env`, and `metadata/` (the node's `docker inspect` for
restore flags). On every exit it restarts only the containers that were
running — node first, then APIs, then miner. Expect brief 503s during
the stop window; the API must show an empty queue beforehand.

- The passphrase file lives permanently in the operator's LOCAL
  `~/.config/vickrey/recovery.key` — never in the repo. During the drill a
  copy sits in a transient protected dir under `~/.cache/vickrey-backup-*`
  on the host (outside the archived `~/.config/vickrey`, and the script
  rejects a key whose real path is inside it). Keep your own secure backup
  of the passphrase — losing it makes the archive unreadable.
- The `.gpg` output is the only thing safe to move off-host. Older backups
  are never deleted automatically.
- Recovery drill **verified 2026-10-30**: an encrypted archive was
  decrypted into fresh task-only volumes on an internal network, a restored
  node (`-connect=0 -discover=0`, no ports) + restored API came up healthy
  (`regtest`, `node ok`), and the known sample receipt returned
  `transaction_verified`/`commitment_verified: true` at height 1305 with the
  expected txid/commitment. The receipt DB passed `PRAGMA quick_check` and
  the on-clone snapshot CLI produced a valid second snapshot. Task volumes,
  containers, network and temp files were removed after the proof.
- A lost passphrase = unreadable backup; local gpg absent → decrypt on
  the host or install gpg locally.
