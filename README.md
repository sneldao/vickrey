# Vickrey — Verified Incident Evidence for Private IOTA

**Prove What Happened.** Systems record incidents. Ledgers preserve evidence. Vickrey proves the two still agree.

Veles Hack **Challenge 2** (O-CEI). Vickrey is the observability and evidence layer for a _private_ IOTA Tangle:

app event → upload → Hornet block → solid / milestone → payload integrity → Incident Evidence Explorer.

Hornet nodes replicate blocks in a DAG. A coordinator plugin confirms them with signed milestones. Vickrey stores the incident in an application-side evidence database and compares that row with the block and metadata read back independently from Hornet. The Incident Evidence Explorer shows whether the two copies still agree.

The product is verified incident evidence on that private network. IOTA Audit Trails and Notarization anchor data for audit use cases. The stock IOTA dashboard lists blocks, tags, and milestones. The explorer adds the investigation workflow: a timeline of evidence states, a trust checklist (payload match, solid, milestone, tag), mismatch detection, and filters for VERIFIED, PENDING, MISMATCH, and NOT SOLID.

The repository name is historical. The work here is Challenge 2.

- **Hack:** 6–8 October 2026. Fresh code in this public repo, Apache-2.0, 6-minute pitch.
- **Mentors:** Rafa Vaño (`ravagar2@upv.es`) and Salvador Cuñat (`salcuane@upv.es`), Universitat Politècnica de València.
- **License:** [Apache-2.0](LICENSE) (`SPDX-License-Identifier: Apache-2.0`). Copyright 2026 Vickrey contributors.

Use the **Stardust** Hornet builds shipped by the aeriOS images. Later IOTA documentation describes a different API.

## Stack

- Docker and Docker Compose on Linux (WSL if the host is Windows).
- Private Tangle: [eclipse-aerios/iota-tangle](https://github.com/eclipse-aerios/iota-tangle) — Hornet 2.0, INX coordinator, INX dashboard.
- Insert path: [eclipse-aerios/iota-messages-api](https://github.com/eclipse-aerios/iota-messages-api) — `POST /upload?node=<hornet-host>`.
- Our applications live in this repo (`apps/`, `services/`). Clone the two upstream trees **beside** the repo. Do not copy them in.

## What we build

The mandatory loop stays: Messages API insert, a parallel evidence database, a solid check, and a content check. The product on that loop is the **Incident Evidence Explorer**.

The demo the pitch repeats: one insert lands as VERIFIED, then a deliberate edit of the application-side payload makes the explorer show PAYLOAD MISMATCH with both payloads side by side.

Day 2 is that evidence database: `services/ledger` on port 8088. Run, the Messages API fan-out, and the tamper path are in [Day 2 — evidence ledger](#day-2--evidence-ledger). Day 3 is the Incident Evidence Explorer: `apps/explorer` on port 8090. Run notes are in [Day 3 — explorer](#day-3--explorer).

Positioning, the two-source rules, and competitors: [`docs/STRATEGY.md`](docs/STRATEGY.md). Build log: [`docs/BUILD.md`](docs/BUILD.md). Six-minute pitch run of show: [`docs/PITCH.md`](docs/PITCH.md).

## Endpoints

| Surface                                 | URL                                               |
| --------------------------------------- | ------------------------------------------------- |
| Dashboard (Advanced Explorer)           | http://localhost:31011 (login `admin` / `admin`)  |
| Hornet REST, challenge sheet            | http://localhost:14625                            |
| Hornet REST, stock `iota-tangle` docker | http://localhost:14265                            |
| Messages API                            | http://localhost:5555/upload?node=\<hornet-host\> |
| Evidence ledger                         | http://localhost:8088                             |
| Incident Evidence Explorer              | http://localhost:8090                             |

`docker/main/hornet-main.yaml` publishes the dashboard on **31011** and Hornet REST on **14265**. The challenge sheet asks for Hornet on **14625**. Day 1 probes both and, if 14625 is closed, adds the host mapping `14625:14265`. Keep 14265: `send_data.py` posts to `http://<node>:14265/api/core/v2/blocks`.

Hornet checks (Stardust core API v2; the sheet's `/api/core/v2/<block-id>` shorthand is this path):

- `GET /api/core/v2/blocks/<blockId>` — block body (tag + payload).
- `GET /api/core/v2/blocks/<blockId>/metadata` — `isSolid` and milestone reference.

Upload body:

```json
{
  "tag": "incident.demo",
  "message": { "format": "any JSON object", "be_creative": true }
}
```

## Day 2 — evidence ledger

The ledger stores the application copy of one incident, then independently reads that Hornet block and sets `solid` and `content_match`. The Incident Evidence Explorer reads this API. The mismatch demo mutates only the application copy.

| Piece                   | Where                                         |
| ----------------------- | --------------------------------------------- |
| Ledger API + SQLite     | `services/ledger` (port 8088)                 |
| Messages API fan-out    | `patches/iota-messages-api-send_data.py.diff` |
| Verify then tamper demo | `scripts/demo_day2.sh`                        |

Status is one of `VERIFIED`, `PENDING`, `PAYLOAD_MISMATCH`, `NOT_SOLID`.

| Last Hornet read                             | Payload | Solidity          | Status             |
| -------------------------------------------- | ------- | ----------------- | ------------------ |
| Unreachable, or block missing                | unknown | unknown           | `PENDING`          |
| Tagged data differs from the app copy        | no      | any               | `PAYLOAD_MISMATCH` |
| Tagged data matches                          | yes     | not solid         | `NOT_SOLID`        |
| Tagged data matches, solid, no milestone yet | yes     | solid             | `PENDING`          |
| Tagged data matches, solid, milestone set    | yes     | solid + milestone | `VERIFIED`         |

`content_match` is semantic JSON equality plus an exact tag match. Key order does not matter. `PAYLOAD_MISMATCH` wins over solidity, so a later tamper of the application copy flips the flag while the Hornet payload stays the original.

`POST /messages/{blockId}/tamper` is demo-only. It overwrites `payload_json` (or just `temperature`) and reverifies. It does not submit a block.

### Run the ledger

Host process, Hornet on localhost:

```bash
python3 -m venv services/ledger/.venv
services/ledger/.venv/bin/pip install -r services/ledger/requirements.txt
cd services/ledger
HORNET_URL=http://127.0.0.1:14265 DATABASE_PATH=./data/ledger.db \
  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8088
```

Docker, Hornet port published on the host:

```bash
docker compose up -d --build
# HORNET_URL defaults to http://host.docker.internal:14265
```

Docker on the Day 1 `iota-net` (Hornet DNS name `iota-hornet`):

```bash
docker compose -f docker-compose.yml -f docker-compose.iotanet.yml up -d --build
# HORNET_URL defaults to http://iota-hornet:14265
```

`HORNET_URL` is the Hornet root, for example `http://127.0.0.1:14265`. The ledger appends `/api/core/v2/blocks/...`. Optional `HORNET_TIMEOUT` seconds (default 5) and `DATABASE_PATH`.

`LEDGER_CORS_ORIGINS` defaults to `*`, so the explorer on another port can call this API from a browser. Set it to `http://localhost:8090` to narrow that. The verify and tamper JSON is unchanged.

### Messages API sibling

Keep `iota-messages-api` as a sibling clone. Apply `patches/iota-messages-api-send_data.py.diff` there and rebuild the image. Steps, `LEDGER_URL`, and the Apache-2.0 upstream commit are in `patches/README.md`.

### Verify, then tamper

`./scripts/demo_day2.sh` starts a mock Hornet and the ledger, then runs this flow. Against a ledger that is already up, the same curls are:

```bash
# Application copy. The real insert is the patched Messages API; this mocks that POST.
curl -sS -X POST http://127.0.0.1:8088/ingest \
  -H 'content-type: application/json' \
  -d '{"blockId":"0x…","tag":"veles.evidence.temperature","message":{"flow_id":"flow-1","temperature":21.5},"hornetStatus":201}'

curl -sS 'http://127.0.0.1:8088/messages?flowId=flow-1&status=VERIFIED'
curl -sS http://127.0.0.1:8088/messages/0x…
curl -sS -X POST http://127.0.0.1:8088/messages/0x…/reverify

# Demo only. Application temperature changes; the Hornet block does not.
curl -sS -X POST http://127.0.0.1:8088/messages/0x…/tamper \
  -H 'content-type: application/json' \
  -d '{"temperature":999.9}'
```

A matching solid, milestone-referenced block returns `status=VERIFIED` and `content_match=true`. After tamper, the same block returns `status=PAYLOAD_MISMATCH`, `content_match=false`, `payload_json.temperature=999.9`, and `ledger_payload_json` still holding the original tagged data.

Ingest again with the original message to put the application copy back.

### Tests

```bash
services/ledger/.venv/bin/pip install -r services/ledger/requirements-dev.txt
(cd services/ledger && .venv/bin/python -m pytest)
```

## Day 3 — explorer

`apps/explorer` is a static page on the Day 2 ledger. It does not submit blocks and it does not change verify or tamper. The browser reads `GET /messages`, opens one incident, and the pitch buttons call the existing reverify and tamper routes.

The timeline groups rows by `flow_id` (the stored `flowId`). Each open incident has a trust checklist: payload match, solid, milestone, tag. Filters are Verified, Pending, Mismatch (`PAYLOAD_MISMATCH`, also accepted as `MISMATCH`), and Not solid. A row whose tag starts with `incident.` or whose payload `kind` is `alarm` is marked on the timeline.

When the application payload and the decoded Hornet payload differ, the incident is labeled **PAYLOAD MISMATCH** and the two documents sit side by side, with the changed fields called out. Tamper still changes only `payload_json`. The Hornet block stays the original. **Open on Hornet dashboard** goes to `http://localhost:31011/explorer/block/<blockId>` (INX dashboard 1.0). **Hornet block JSON** is `GET /api/core/v2/blocks/<blockId>` on the public Hornet URL.

### Run the explorer

Ledger already on port 8088:

```bash
python3 -m http.server 8090 --bind 127.0.0.1 --directory apps/explorer
```

Open http://localhost:8090 . The page calls http://localhost:8088 unless you change it under Endpoints.

Docker, beside the ledger:

```bash
docker compose up -d --build
# explorer http://localhost:8090
# ledger   http://localhost:8088
```

The Day 1 `iota-net` overlay starts the explorer too. The browser still uses the published host ports.

`./scripts/demo_day3.sh` starts a mock Hornet, the ledger, and the explorer, and inserts one VERIFIED `incident.critical` alarm (`0xda720001`, flow `line-7`) plus neighboring states for the filters. Leave it running, open the printed URL, and use **Tamper application copy**. The stamp becomes PAYLOAD MISMATCH and `999.9` sits beside the Hornet value `21.5`. Ctrl-C stops the three processes.

### Explorer configuration

These are URLs the **browser** calls. Docker DNS names such as `http://ledger:8088` or `http://iota-hornet:14265` do not resolve in the browser.

| Variable              | Default                  | Meaning                                                                                                                |
| --------------------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| `EXPLORER_LEDGER_URL` | `http://localhost:8088`  | Ledger origin. Docker writes it into `config.js`. This is not the messages-api `LEDGER_URL`, which includes `/ingest`. |
| `DASHBOARD_URL`       | `http://localhost:31011` | INX dashboard origin                                                                                                   |
| `HORNET_PUBLIC_URL`   | `http://localhost:14265` | Browser link to the raw block                                                                                          |

On a laptop pointed at the tangle host, set the three variables to that host before `docker compose up`, or type them into Endpoints and press Apply. Apply stores them in `localStorage`.

The page also reads `?ledger=`, `?dashboard=`, and `?hornet=` (those win over a saved value). A block id in the hash (`http://localhost:8090/#0xda720001`) opens that incident. `?status=MISMATCH` selects the mismatch filter.

`config.js` holds the same defaults when you serve the directory yourself. The container entrypoint rewrites that file from the variables above.

## References

- https://github.com/eclipse-aerios/iota-tangle
- https://github.com/eclipse-aerios/iota-messages-api
- https://github.com/iotaledger/hornet
- https://github.com/iotaledger/hornet/tree/develop/private_tangle
- https://github.com/iotaledger/inx-dashboard
- https://github.com/iotaledger/iota-sdk
- https://legacy.wiki.iota.org/iota-sdk/welcome
