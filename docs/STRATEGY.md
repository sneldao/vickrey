# Strategy — Challenge 2 trust ledger

Source: O-CEI challenge introduction (IOTA, UPV). Stardust Hornet only.

## Mandatory goal

After a private Tangle is up (one Hornet plus the coordinator), ship two applications.

1. **Publisher.** Insert a message through the Eclipse aeriOS Messages API (`POST /upload?node=<hornet-host>`). Body is JSON with `tag` and `message`.
2. **Traceability service.** Relational database of every insert, with enriched fields (received time, tag, block id, payload, solid flag, content-match flag). It must:
   - Receive each insert from the Messages API. Patch the sibling `iota-messages-api` so a successful Hornet response is also POSTed here. Commit that patch under `patches/` in this repo. Leave the upstream tree uncommitted.
   - Search stored messages by block id, time range, and tag over REST.
   - For each `blockId`, `GET /api/core/v2/blocks/<blockId>/metadata` and record `isSolid`.
   - `GET /api/core/v2/blocks/<blockId>`, hex-decode the tagged-data tag and data, and record whether they equal the tag and JSON we stored.

A message counts as legit when metadata says the block is solid and the decoded body matches the stored copy. Store `referencedByMilestoneIndex` when Hornet returns it so the explorer can show milestone confirmation as well as solidity.

## Architecture

```
publisher --> Messages API --> Hornet (+ coordinator) --> Tangle
                  |
                  +--> Traceability API --> relational DB
                              |
                              +--> Hornet GET block + GET metadata
                              |
                              +--> Incident Explorer
```

That is the challenge diagram: Messages API, Hornet, coordinator, traceability DB, traceability API, messages dashboard. Our dashboard is the Incident Explorer.

## v1 thesis

Ship the mandatory loop, then one product: an **Incident Explorer**.

Operators insert trust events. The ledger stores them, checks solid and content against Hornet, groups rows that share a `flowId`, and shows one chronological timeline. Each row shows its `blockId` and the two check flags. A critical tag raises an alert on that same screen.

This is idea **#4** (verifiable receipts: timeline, per-block verification, alerts) drawn on the idea **#2** Explorer UI. Idea **#3** is the grouping key only: `flowId` (optional `sensorId` / user) inside the payload, so one IoT flow reconstructs as one timeline. Idea **#1** (MQTT) changes how the ledger hears about inserts. Start it only after REST fan-out and the timeline both work.

The Thursday pitch is one insert-to-alert loop. A verified timeline is what the jury can watch. The enriched table is the mandatory floor under that screen.

## Payload

`message` stays free-form JSON, as the sheet requires. v1 readers expect these fields:

```json
{
  "tag": "incident.critical",
  "message": {
    "flowId": "line-7",
    "kind": "alarm",
    "sensorId": "temp-12",
    "detail": "threshold exceeded"
  }
}
```

`tag` is the Hornet tagged-data tag. The explorer groups on `flowId`. An alert fires when `tag` starts with `incident.` or `kind` is `alarm`.

## Where code lives

| Path | Role |
| --- | --- |
| `apps/publisher` | Insert client. A curl is enough on day 1. |
| `services/ledger` | Traceability API and relational schema |
| `apps/explorer` | Incident Explorer UI |
| `patches/` | Diff (or the patched `send_data.py`) for the Messages API fan-out |

Clone upstream next to this repo:

```
../iota-tangle
../iota-messages-api
```

## Leave for later

Helm, extra Hornet nodes, autopeering, and MQTT. One machine, one Hornet, the coordinator, and Docker is the whole network for v1.
