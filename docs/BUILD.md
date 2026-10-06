# Build log — Oct 6–8 (as it happened)

Challenge 2 (O-CEI): verified incident evidence for a private IOTA Tangle.
Product: `services/ledger` evidence database + `apps/explorer` Incident
Evidence Explorer on a private Hornet network.

## Compliance

- [x] Public repo `sneldao/vickrey` created at event start — fresh code
- [x] Apache-2.0 license (`LICENSE`)
- [x] README: setup, run, strategy, endpoints
- [ ] 6-minute pitch — run of show in [`PITCH.md`](PITCH.md)

## Day 1 — private Tangle

- [eclipse-aerios/iota-tangle](https://github.com/eclipse-aerios/iota-tangle)
  up on the Vultr host: Hornet 2.0, INX coordinator, INX dashboard.
- Challenge-sheet port mapping sorted: Hornet REST on both 14265
  (`send_data.py` default) and 14625 (sheet).
- Insert path via sibling clone
  [eclipse-aerios/iota-messages-api](https://github.com/eclipse-aerios/iota-messages-api).

## Day 2 — evidence ledger

- `services/ledger` (FastAPI + SQLite, port 8088): stores the application
  copy at ingest, then independently GETs the Hornet block + metadata.
- Status truth table: `VERIFIED / PENDING / NOT_SOLID / PAYLOAD_MISMATCH`
  (payload mismatch outranks solidity).
- `patches/iota-messages-api-send_data.py.diff` fans every upstream insert
  into the ledger — write-path contract unchanged.
- Demo-only `POST /messages/{id}/tamper` mutates only the application copy.
- `scripts/demo_day2.sh` runs verify-then-tamper against a mock Hornet.

## Day 3 — explorer + deploy

- `apps/explorer`: static page, timeline grouped by `flow_id`, trust
  checklist (payload match / solid / milestone / tag), status filters,
  side-by-side mismatch view, links out to the INX dashboard and the raw
  Hornet block.
- Deployed on the Vultr host via `docker-compose.yml` (+ `iotanet` overlay):
  explorer :8090, ledger :8088. Bare-IP `http://45.76.242.245` proxies to
  the explorer through the host Caddy.
- Seeded state: fresh VERIFIED `incident.critical` alarm
  (`0x6d90d792…5313f5`, flow `line-7`) for the live tamper flip, plus a
  standing `PAYLOAD_MISMATCH` exhibit. `./scripts/restore_demo.sh`
  restores all rows if anything touches them early.
- Tests: 28 ledger (pytest) + 12 explorer (node --test).
- Pitch: [`PITCH.md`](PITCH.md).

## Cuts / non-goals

- No auth on the ledger or tamper routes — demo scope, stated openly in
  the pitch. Not a production posture.
- No block submission from our services — writes stay on the patched
  upstream Messages API.
