# ECATHON film — "Which one is yours?"

_Date: 2026-10-28 · Status: **built** — source in [`ecathon/`](ecathon/), 92 s,
16:9, narrated, captions burned in · This file is the concept; the shipped
scene-by-scene truth table and rebuild steps live in
[`ecathon/README.md`](ecathon/README.md), and the shipped VO script is
`ecathon/narration.json` (it differs from the draft below)._

**TL;DR.** The Week 1 film was a tidy explainer on paper. This one has one
image and one stunt:

1. **The image:** a map of pins (who saw which rare bird, where, when) that
   _dissolves into a field of identical dots_. One of them is yours. Nobody,
   including us, can point at it.
2. **The stunt:** the film seals itself. We hash the finished picture, anchor
   that hash through zanchor, and bake the receipt into the final card. The
   video is a Vickrey record, and anyone can check it.

## Look

Night, not paper. Near-black field (`#0e0f0c`), bone type, wax red only where a
seal is made or broken, one cold gold for "shielded". Real app captures sit in
a thin glass frame with the truth badge always on. Caveat handwriting only for
the human (the correction). Everything the system says is mono.

## Beats

| Time  | Beat                        | What happens on screen                                                                                                                                                             |
| ----- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0–10  | **The poacher's map**       | Dark map. Pins land one by one, each with a label: `observer · species · area · time`. A line traces observer → rare bird → place → time. Stamp: "PUBLIC LEDGER".                  |
| 10–20 | **Seal**                    | Cut to the phone-sized field app. The model says blackbird; a hand-lettered correction to robin; wax press. "The model suggests. You decide. Both are sealed."                     |
| 20–36 | **The crack**               | Tamper with the queued copy. The seal fractures across the whole frame, sync refuses. Restore, re-seal, sync, three `Anchored · VERIFIED`.                                         |
| 36–56 | **The crowd** (centrepiece) | Back to the map. Pins lose their labels, then their shape, then migrate into a dense grid of identical gold dots. Your three pulse once, then are indistinguishable from the rest. |
| 56–70 | **A stranger tries**        | Terminal beat from `demo_zcash.sh`: look up a tx (exists at height H, nothing else), `GET /receipts` → 404, replay → 409. Each line lands as a verdict stamp.                      |
| 70–84 | **The film seals itself**   | The render's SHA-256 types out; commitment goes to zanchor; receipt, txid and height resolve on screen. Label: regtest / mock exactly as true.                                     |
| 84–90 | **Close**                   | "Vickrey proved a sealed bid makes people honest. We asked the same of a memory." Repo + live URLs. Small honest line: what is not built (rewards, on-phone model).                |

## Voice-over (George, ~190 words) — draft; shipped script is `ecathon/narration.json`

01 Every sighting you log is a pin. Who saw it. What. Roughly where. When. Put that on a public ledger and you haven't made a field record. You've made a map for poachers.

02 Vickrey starts with the seal. The phone names the bird, but only suggests. You decide, and your decision is signed on the device and chained to the last entry.

03 Edit a copy waiting to sync, and the seal cracks. Sync refuses to send it. Put it back, and it verifies.

04 But proof still left a trail. So we moved the anchor into Zcash's shielded pool. Same transaction, same amount, every time. No name. No species. No place. Which one is yours? Only the verifier knows, and only if you hand over the receipt.

05 A stranger can ask one thing: does this transaction exist at this height? There is no list to read. Nothing to enumerate.

06 This film is sealed the same way. Its hash, anchored. Check it.

07 Vickrey proved that a sealed bid makes people honest. We asked the same of a memory. Without telling anyone where the bird was.

## Truth labels (non-negotiable, on screen when relevant)

- Field captures: "Real app capture · sample walk".
- Model: "Gemma 3 4B, server-hosted · it received the photo" wherever the model appears.
- Chain: "regtest, private chain we mine" — or "mock zanchor" if that's what ran.
- Close: rewards design-only, on-phone model unmeasured (from `STATUS.md`).
- Never say the photo "never leaves"; say the photo never reaches the **ledger**.

## Build plan

1. Captures: `scripts/demo_field.sh` + Playwright 1440×900 (field flow, crack); `scripts/demo_zcash.sh` terminal capture.
2. Hero scenes are authored (map, crowd, crack fracture, self-seal), not screen-recorded.
3. VO via `gen_audio.py` with the new `narration.json`; mix via `mix_audio.py`.
4. Render body → sha256 → zanchor `/anchor` → read receipt → bake into end card → final render.
5. Lint, frame-check each beat, upload unlisted, update README + SUBMISSION links.

## Resolved at build

- The seal ran against the **mock** zanchor and is labelled as such on screen
  (`SEAL.json` → `is_mock: true`, badge "the txid is a hash and the height a
  counter — not a Zcash transaction"). The live-node walk stays in
  `scripts/demo_zcash.sh` and STATUS.md.
- Shipped length: **92 s**.
