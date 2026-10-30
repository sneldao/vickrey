# Demo deployment runbook — private regtest

Planned host: `https://vickrey.144.202.117.160.sslip.io` (the
`VICKREY_DEMO_HOST` default in compose). The demo adds three NEW containers
beside the existing ones — `vickrey-zanchor-test` and
`vickrey-zcashd-regtest` stay untouched throughout, and pushing `main` only
republishes the static GitHub Pages site; it changes nothing on the node.

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

## Receipt persistence

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

## Logging caveat

The nginx layer suppresses API access logs, but bearer receipt ids can still
appear in **Uvicorn access logs** (the image currently runs uvicorn with
access logging enabled) and in Traefik's own logs. Production log handling
is pending — treat any log shipped off the box as containing receipt paths.
