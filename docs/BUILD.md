# Build plan — 6–8 October

Linux, Docker, and Docker Compose. One machine. This repository is the submission. Clone upstream **beside** it; our apps stay under `apps/` and `services/`.

```bash
git clone https://github.com/eclipse-aerios/iota-tangle.git ../iota-tangle
git clone https://github.com/eclipse-aerios/iota-messages-api.git ../iota-messages-api
```

Leave the sample coordinator keys in `startup.yaml` and `hornet-main.yaml` alone. They match each other and the public keys in `config_private_tangle.json`. Editing one file breaks milestones.

`bootstrap.sh` calls the `docker-compose` binary. Install that, or run the two `docker compose -f startup.yaml run …` steps from the script yourself.

## Compliance

Done:

- [x] Public submission repo: https://github.com/sneldao/vickrey
- [x] Apache-2.0 chosen and committed (`LICENSE`, SPDX `Apache-2.0`)

Still open:

- [ ] Private Tangle up locally (dashboard and Hornet API answering)
- [ ] Discord category **Challenge 2** selected

## Day 1 — node, insert, read-back

Goal: one block on the private Tangle, read back from Hornet. No database yet.

1. Bootstrap and start the main tangle:

   ```bash
   cd ../iota-tangle/docker/main
   sudo ./bootstrap.sh
   docker compose -f hornet-main.yaml up -d
   ```

   Bootstrap builds the genesis snapshot and coordinator state. Compose then starts Hornet, the coordinator, and the dashboard on network `iota-net`.

2. Confirm the challenge URLs:

   - http://localhost:31011 loads and milestones advance. Login `admin` / `admin`.
   - Hornet REST answers. Stock compose publishes **14265**. The sheet says **14625**. Probe both:

     ```bash
     curl -sf http://localhost:14265/api/core/v2/info
     curl -sf http://localhost:14625/api/core/v2/info
     ```

     If 14625 is closed, add `"14625:14265"` beside `"14265:14265"` on `iota-hornet` and recreate that container. Keep 14265, because the Messages API posts to port 14265.

3. Start the Messages API on the same Docker network:

   ```bash
   cd ../iota-messages-api
   docker compose up -d --build
   ```

   A missing-network error means Hornet is not up yet (`iota-net` is external).

4. Insert, then verify. The API wraps Hornet's body as `return_payload` (a JSON string containing `blockId`):

   ```bash
   curl -sS -X POST 'http://localhost:5555/upload?node=iota-hornet' \
     -H 'Content-Type: application/json' \
     -d '{"tag":"incident.demo","message":{"flowId":"line-7","kind":"alarm","detail":"day-1"}}'
   ```

   ```bash
   curl -sS http://localhost:14265/api/core/v2/blocks/<blockId>
   curl -sS http://localhost:14265/api/core/v2/blocks/<blockId>/metadata
   ```

   Done when `isSolid` is true and the block body carries the same tag and payload. Open the block id in the dashboard too.

   If upload fails on proof-of-work, `config_private_tangle.json` has `restAPI.pow.enabled: true`. For the hack, set it to `false`, recreate Hornet, and retry.

## Day 2 — traceability DB and the two checks

Goal: every insert is searchable, with a solid verdict and a content verdict.

1. `services/ledger`. SQLite is enough. Columns: `block_id`, `tag`, `flow_id`, `payload_json`, `inserted_at`, `solid`, `content_match`, `milestone_index`, `raw_block`.
2. Patch sibling `send_data.py`: after Hornet accepts the block, POST `{blockId, tag, message, hornetStatus}` to the ledger. Save the diff under `patches/` in this repo.
3. On ingest, store the row, then:
   - `GET /api/core/v2/blocks/<blockId>/metadata` → set `solid` from `isSolid`, copy `referencedByMilestoneIndex` when present.
   - `GET /api/core/v2/blocks/<blockId>` → strip `0x`, hex-decode tag and data, set `content_match` when they equal the stored tag and `json.dumps` of `message`.
4. REST: `GET /messages?blockId=`, `?tag=`, `?from=&to=` (ISO-8601). Return the enriched row, including both flags.
5. Replay the day-1 curl. Search by tag returns `solid=true` and `content_match=true`.

Shipped for the evidence layer (run notes in the README section "Day 2 — evidence ledger"):

- [x] `services/ledger` stores the app payload and independently GETs Hornet block + metadata
- [x] Flags: `solid`, `content_match`, `milestone_index`, status `VERIFIED|PENDING|PAYLOAD_MISMATCH|NOT_SOLID`. Also stored: `ledger_payload_json` (decoded from Hornet) and `verified_at`
- [x] `POST /ingest`, `GET /messages`, `GET /messages/{blockId}`, `POST .../reverify`, `POST .../tamper` (demo). Tamper overwrites only `payload_json`; the Hornet block stays original so reverify can show `PAYLOAD_MISMATCH`
- [x] `patches/iota-messages-api-send_data.py.diff` fans out to `LEDGER_URL` after a successful Hornet upload
- [x] Compose on port 8088, `scripts/demo_day2.sh` verify-then-tamper path

`content_match` compares tag plus semantic JSON (key order does not count). Hornet URL defaults to `http://127.0.0.1:14265` on the host and `http://iota-hornet:14265` when the ledger joins `iota-net` (`docker-compose.iotanet.yml`).

## Day 3 — explorer, freeze, pitch

Goal: the Incident Evidence Explorer on the day-2 checks, then stop changing the ledger.

1. `apps/explorer`: a timeline of evidence states (group by `flowId` when present). Trust checklist on each open incident: payload match, solid, milestone, tag. Filter by VERIFIED, PENDING, MISMATCH, and NOT SOLID. When the payload differs, label the row PAYLOAD MISMATCH and show the application-side payload and the decoded ledger payload side by side. Highlight `tag` prefix `incident.` or `kind=alarm`. State rules are in `docs/STRATEGY.md`.
2. Killer demo, one block id. Insert through the Messages API and show VERIFIED (fresh Hornet read matches the evidence DB). Deliberately mutate only the application-side payload. Re-run the content check and show PAYLOAD MISMATCH with both payloads side by side. The Hornet block stays as it was. The block id still opens on the Hornet dashboard.
3. Freeze in the early afternoon. README commands must match what you ran. Six-minute pitch: Prove What Happened (the application records the incident, the private Tangle keeps the block, Vickrey checks the two still agree) → VERIFIED insert → mutate the application-side row → PAYLOAD MISMATCH side by side → how private-Hornet reconciliation differs from IOTA Audit Trails, Notarization, and the stock dashboard. Next, if asked: MQTT, a second node.

## Cuts if behind

Cut in this order. Stop at the first cut that gets the demo honest.

1. MQTT (idea #1). Do not start it unless day 2 is done.
2. Alerts and `flowId` grouping. A flat verified table still meets the mandatory goal.
3. Explorer polish. One HTML page, or the JSON API plus the IOTA dashboard, is enough to pitch.

Keep through every cut: the Apache-2.0 `LICENSE`, a working insert, the parallel database, the solid check (block metadata), the content check (GET block), the PAYLOAD MISMATCH demo (both payloads side by side), and the 6-minute pitch.
