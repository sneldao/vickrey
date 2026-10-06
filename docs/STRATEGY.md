# Strategy — Verified Incident Evidence for Private IOTA

**Prove What Happened.** Systems record incidents. Ledgers preserve evidence. Vickrey proves the two still agree.

The primary framing is verified incident evidence for a private IOTA Tangle. The product surface is the Incident Evidence Explorer.

Source: O-CEI challenge introduction (IOTA, UPV). Stardust Hornet only.

## Positioning

Vickrey is an observability and evidence layer for a *private* IOTA Tangle. One path:

app event → upload → Hornet block → solid / milestone → payload integrity → Incident Evidence Explorer.

An application records an incident and uploads it through the Messages API. Hornet writes a block. Solidity and the coordinator milestone say how far that block has settled. Payload integrity is a second question: does the application record still match the block?

The check compares two sources. They are written and read on different paths.

| Source | How it is obtained | What it holds |
| --- | --- | --- |
| Application-side evidence DB | Stored when the Messages API reports a successful insert | tag, payload JSON, time, block id |
| Ledger-side block and metadata | Independent `GET /api/core/v2/blocks/<blockId>` and `GET .../metadata` | tagged-data tag and data, `isSolid`, `referencedByMilestoneIndex` |

The upload response supplies the block id. The ledger copy on screen comes from those later GETs.

On the challenge sheet this is idea **#4** (a receipt you can verify) drawn on the idea **#2** explorer. `flowId` is the idea **#3** grouping key. MQTT (idea **#1**) stays later.

## Competitors

IOTA Audit Trails and IOTA Notarization anchor data on a Tangle so a later reader can show that a hash was published. That is the generic audit-trail and supply-chain traceability layer. Generic explorers, including the INX dashboard on this private net, render blocks, tags, and milestones for a node.

Vickrey stays on private-Hornet incident evidence:

- **Block-level observability.** Follow one upload to one block id, then to `isSolid` and `referencedByMilestoneIndex`.
- **App↔ledger reconciliation.** Compare the application-side row with the block fetched again. The verdict is that comparison.
- **Incident investigation.** Timeline of evidence states, trust checklist, mismatch detection, and a filter for rows that are not cleanly verified.

## Mandatory goal

After a private Tangle is up (one Hornet plus the coordinator), ship two applications.

1. **Publisher.** Insert a message through the Eclipse aeriOS Messages API (`POST /upload?node=<hornet-host>`). Body is JSON with `tag` and `message`.
2. **Traceability service.** Relational database of every insert, with enriched fields (received time, tag, block id, payload, solid flag, content-match flag). It must:
   - Receive each insert from the Messages API. Patch the sibling `iota-messages-api` so a successful Hornet response is also POSTed here. Commit that patch under `patches/` in this repo. Leave the upstream tree uncommitted.
   - Search stored messages by block id, time range, and tag over REST.
   - For each `blockId`, `GET /api/core/v2/blocks/<blockId>/metadata` and record `isSolid`.
   - `GET /api/core/v2/blocks/<blockId>`, hex-decode the tagged-data tag and data, and record whether they equal the tag and JSON we stored.

A message counts as legit when metadata says the block is solid and the decoded body matches the stored copy. Store `referencedByMilestoneIndex` when Hornet returns it so the explorer can show milestone confirmation as well as solidity.

That service is the application-side evidence database. The four requirements above stay the floor. The explorer states are derived from them.

## Architecture

```
app event --> Messages API --> Hornet (+ coordinator) --> private Tangle
                  |
                  +--> Traceability API --> evidence DB (application-side)
                              |
                              +--> Hornet GET block + GET metadata (ledger-side)
                              |
                              +--> Incident Evidence Explorer (compares the two)
```

That is the challenge diagram: Messages API, Hornet, coordinator, traceability DB, traceability API, messages dashboard. Our dashboard is the Incident Evidence Explorer. The stock Hornet dashboard remains the place that opens a raw block id.

## Evidence states

The explorer filters every incident into one state. MISMATCH takes precedence when the content check has failed. Otherwise a finished `isSolid: false` is NOT SOLID.

| State | Rule |
| --- | --- |
| VERIFIED | `solid` and `content_match` are both true. This is the mandatory legit message. The checklist shows `referencedByMilestoneIndex` when Hornet returned one. |
| PENDING | The row is stored and the solid check or the content check has not finished. |
| MISMATCH | The content check ran and failed. When the payload differs, the row label is PAYLOAD MISMATCH and both payloads are shown. A tag-only miss stays in this filter and fails the tag item on the checklist. |
| NOT SOLID | Metadata says `isSolid` is false, and the content check did not fail. |

Milestone confirmation is a checklist field on the row. VERIFIED follows the mandatory legit rule: solid, and the decoded body matches the stored copy.

Trust checklist on the open incident: payload match, solid, milestone, tag.

The screen answers questions the stock IOTA dashboard does not:

- Timeline of evidence states, in time order, grouped by `flowId` when the payload has one. Each point carries its state.
- The trust checklist above.
- Mismatch detection, with the application-side payload and the decoded ledger payload side by side.
- Filter: VERIFIED / PENDING / MISMATCH / NOT SOLID, so MISMATCH and NOT SOLID come out of the verified set.

A highlight remains when `tag` starts with `incident.` or `kind` is `alarm`.

## Killer demo

The pitch shows the two sources disagree on purpose.

1. Insert one incident through the Messages API. The evidence DB stores the payload. A fresh Hornet read matches it. The explorer shows VERIFIED. The checklist is green on payload, solid, and tag, and it shows the milestone index once the coordinator has referenced the block.
2. Deliberately mutate the application-side payload in the evidence DB. Do not resubmit to Hornet and do not edit the block.
3. Re-run the content check: GET the block again, hex-decode, compare. The explorer shows PAYLOAD MISMATCH. The mutated application payload and the original payload still on the block sit side by side.

A VERIFIED row is the happy path. The mutated row is the product: the system and the ledger disagree, and the ledger copy is unchanged.

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
| `services/ledger` | Traceability API and relational schema (application-side evidence DB) |
| `apps/explorer` | Incident Evidence Explorer |
| `patches/` | Diff (or the patched `send_data.py`) for the Messages API fan-out |

Clone upstream next to this repo:

```
../iota-tangle
../iota-messages-api
```

## Leave for later

Helm, extra Hornet nodes, autopeering, and MQTT. One machine, one Hornet, the coordinator, and Docker is the whole network for v1.
