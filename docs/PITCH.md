# Pitch — 6 minutes, live demo

**One line:** Systems record incidents. Ledgers preserve evidence. Vickrey proves the two still agree.

**Demo URLs (open in tabs before starting):**

- Explorer: <http://45.76.242.245> (same as `http://45.76.242.245:8090`)
- Ledger API: <http://45.76.242.245:8088/docs>
- Hornet dashboard: <http://45.76.242.245:31011> (admin / admin)
- Panic restore if a row was touched early: `./scripts/restore_demo.sh`

## 0:00–0:45 — Problem

Incident pipelines write events into an application database and anchor them on a ledger. Two copies, written once, compared never. If the application row drifts — a bad migration, a bug, a deliberate edit — nothing notices. On a private IOTA Tangle the stock dashboard proves the _block_ exists; it never asks whether the block still says what the app _thinks_ it says.

## 0:45–1:30 — What we built

Vickrey is the observability and evidence layer for a private Tangle:

```
app event → Messages API /upload → Hornet block → solid / milestone
                                              ↘ independent read-back
app event → evidence ledger (SQLite) ────────→ compare → status
```

The ledger stores the application copy at ingest, then _independently_ GETs the block and metadata from Hornet. Two reads, two sources. Status is a truth table over `isSolid`, milestone reference, tag, and payload equality: `VERIFIED / PENDING / NOT_SOLID / PAYLOAD_MISMATCH`.

## 1:30–4:00 — Live demo (~2.5 min)

1. **Timeline.** Open the explorer. Rows group by `flow_id`; filters on top (VERIFIED / PENDING / MISMATCH / NOT SOLID). Real rows on a real Hornet, not fixtures.
2. **Trust checklist.** Open the `incident.critical` alarm `0x6d90d792…5313f5` (flow `line-7`). Green checks: payload match, solid, milestone `749`, tag. Show **Hornet block JSON** — the raw `GET /api/core/v2/blocks/<id>` — and **Open on Hornet dashboard** for the same block in the stock INX explorer.
3. **The mismatch.** Hit **Tamper application copy**. Only the application row changes — the Hornet block is untouched and unreadable as a write path. The stamp flips to **PAYLOAD MISMATCH**; `92.0` sits beside the original `82.0` side by side, changed fields called out.
4. **Recovery.** Re-ingest the original message — the row goes back to VERIFIED because the block never changed. That _is_ the product: the ledger copy is the ground truth the app copy is measured against.

Fallback if live dies: `./scripts/demo_day3.sh` runs the same flow against a mock Hornet locally.

## 4:00–4:45 — What it took

- Patched the upstream Messages API (`patches/`) to fan every insert into the ledger — no changes to the write path contract.
- Semantic JSON equality, not byte equality — key order doesn't matter, content does.
- `PAYLOAD_MISMATCH` outranks solidity on purpose: a solid block can still be a lying copy.
- 28 ledger tests + 12 explorer tests; verify/tamper API unchanged since Day 2.

## 4:45–5:30 — Next

- Webhook alerts on status flip (mismatch → page, not poll).
- Signed evidence rows; anchor audit summaries back onto the tangle.
- Same pattern on mainnet anchoring or non-IOTA stores — the two-source check is ledger-agnostic.

## 5:30–6:00 — Close

"Your app already stores what happened. Your ledger already proves a block exists. Vickrey is the missing proof that they're the same sentence."

## If judges ask

- **"Isn't tampering cheating?"** — The tamper endpoint mutates only the application copy and is labeled demo-only. It's how we show detection, not a feature we'd ship unauthenticated.
- **"Why not just trust Hornet?"** — We do trust it. That's the point: the block is the reference. The failure mode is in the application's own copy, which is what operators actually read.
- **"Private tangle only?"** — The challenge targets private deployments, but the check needs only `GET /blocks` + `/metadata` — any Stardust API works.
