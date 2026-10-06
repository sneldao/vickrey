# Vickrey — IOTA Trust Ledger Traceability

Veles Hack **Challenge 2** (O-CEI): a private IOTA Tangle as a trust ledger. Hornet nodes replicate blocks in a DAG; a coordinator plugin confirms them with signed milestones. This repo adds the missing observability layer: insert a message, keep an enriched copy in our own database, and prove the block is solid and that its payload matches the Tangle.

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

Mandatory insert-and-verify loop, then one product: an **Incident Explorer** (challenge ideas #4 and #2). Thesis and payload shape: [`docs/STRATEGY.md`](docs/STRATEGY.md). Three-day plan: [`docs/BUILD.md`](docs/BUILD.md).

## Endpoints

| Surface | URL |
| --- | --- |
| Dashboard (Advanced Explorer) | http://localhost:31011 (login `admin` / `admin`) |
| Hornet REST, challenge sheet | http://localhost:14625 |
| Hornet REST, stock `iota-tangle` docker | http://localhost:14265 |
| Messages API | http://localhost:5555/upload?node=\<hornet-host\> |

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

## References

- https://github.com/eclipse-aerios/iota-tangle
- https://github.com/eclipse-aerios/iota-messages-api
- https://github.com/iotaledger/hornet
- https://github.com/iotaledger/hornet/tree/develop/private_tangle
- https://github.com/iotaledger/inx-dashboard
- https://github.com/iotaledger/iota-sdk
- https://legacy.wiki.iota.org/iota-sdk/welcome
