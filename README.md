# Vickrey — Verified Incident Evidence for Private IOTA

**Prove What Happened.** Systems record incidents. Ledgers preserve evidence. Vickrey proves the two still agree.

Veles Hack **Challenge 2** (O-CEI). Vickrey is the observability and evidence layer for a *private* IOTA Tangle:

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

Positioning, the two-source rules, and competitors: [`docs/STRATEGY.md`](docs/STRATEGY.md). Three-day plan: [`docs/BUILD.md`](docs/BUILD.md).

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
