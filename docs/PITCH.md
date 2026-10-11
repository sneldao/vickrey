# Submission plan — Hacktoberfest 2026, Week 1: Touch Grass

**Project:** Vickrey — a sealed bid on what you saw. Offline, open-source AI field
identification with a tamper-evident ecological logbook. The name is the metaphor:
William Vickrey's sealed-bid auction (see [`BRAND.md`](BRAND.md)).

**Entry period:** October 5, 2026, 9:00 AM PDT – October 11, 2026, 11:59 PM PDT ([Week 1 rules](https://dev.to/page/hacktoberfest-week1-2026-10-05-contest-rules)). Publish one DEV post with the official [challenge template](https://dev.to/challenges/hacktoberfest-week1-2026-10-05) and tags `#devchallenge` and `#hf26challenge`. Include a demo URL or video, repository link, and why open innovation matters. One entry only; if more than one is submitted, only the first is judged.

## Judging criteria → what to optimise

Ranked by weight, highest first:

1. **Writing quality (heaviest).** This is a DEV writing challenge. Budget real
   time for the post. Clear structure, concrete build detail, honest trade-offs.
2. **Relevance to the prompt and theme.** Open-source AI is the core; it gets
   people outside; the screen is the shortest part.
3. **Creativity.** The trust/verification twist no one else has.
4. **Technical execution.** It runs, and the demo works. (Verified so far: the
   local queue + seal + anchor loop against a mock Hornet — not yet a full
   offline phone/model run.)
5. **Partner technology (optional).** An entry is automatically considered for every category whose technology it meaningfully uses, but a participant may win only one prize in this contest. Claim only demonstrated use (see [`SPONSORS.md`](SPONSORS.md)).

## Post outline — use the official template

- **What I Built:** Identify the person who uses it, the outdoor situation, the tested field loop, and the boundary between the sample/demo and the planned on-device model.
- **Demo:** Link to a video or working deployed demo. Show sample seal → verify → mock-ledger VERIFIED → edit a second queued entry → cracked seal → refused sync. If showing the separate real Gemma robin run, credit the photo and state that inference was server-hosted.
- **Code:** Link to the repository. State that its first commit was October 6, 2026 and clearly credit the Veles ledger/explorer reuse. The organizer decides whether the new field-client work qualifies under the new-project rule.
- **How I Built It:** Show signed payload, chain verification and relay path; label mock Hornet, local sample, Atlas fake-store tests, Temporal scaffold and any unrun partner integrations accurately. Name the verified server-hosted Gemma run, not an offline/on-device result.
- **Why Does Open Innovation Matter?:** Explain how a locally runnable, swappable open model would let field identification work without sending a photo to a hosted model; the real demonstration used a self-hosted model on our server, and the offline-phone design remains untested.
- **My Agent Session:** Optional DevRelay embed or link if genuinely saved.
- **Prize Categories:** List only partners demonstrably used in the submitted build, or remove this section. The one-prize-per-challenge rule makes ten speculative categories less valuable than one strong, evidenced entry.

The [Week 1 FAQ](https://dev.to/challenges/hacktoberfest-week1-2026-10-05) says the project and repository must be started and completed in the challenge window. Existing open-source code may be borrowed when the change is significant, and non-trivial prior work must be credited. Do not claim that the repository date alone guarantees eligibility. The DEV post has not been verified as published.

## Demo run of show (~3 min, verified local path)

`bash scripts/demo_field.sh` starts a mock Hornet, the ledger, the anchor
relay (Messages API stand-in), and serves the field client on printed ports.

1. **Suggest.** Open the field URL, choose a photo, and **Ask the model for a
   suggestion** (or **Try a labelled sample suggestion** with no model). The
   suggestion card names the model and its self-reported confidence — not
   measured accuracy.
2. **Decide and seal.** **Confirm & seal**, or **Correct it** and seal your
   own name. The decision is signed with the device key and hash-chained; the
   record lands in the field journal and the outbox.
3. **The crack.** Open **Demo: tamper with a queued copy** → **Edit the queued
   copy**. The journal row shows a cracked seal and the edited text;
   **Sync to the ledger** is refused — the tampered copy never leaves the
   device.
4. **Restore and anchor.** **Put the sealed copy back**, then sync. The relay
   writes to the mock Hornet; the ledger returns **VERIFIED** (solid,
   milestone, commitment match). The outbox empties; the journal keeps the
   sighting, now `Anchored · VERIFIED`, with model, hash, signature and block
   under **Proof**.

**Hosted film:** the 92-second demo is on YouTube (unlisted):
<https://youtu.be/9BmpLblSHUM>. It shows the same server-hosted Gemma + mock
Hornet path; a hosted video is not proof of outdoor, on-phone, or
public-ledger deployment.

**Real-model evidence, separate from the sample run:** A browser test uploaded a [Wikimedia Commons European robin photo](https://commons.wikimedia.org/wiki/File:European_robin_on_a_branch.jpg) (Alexis LOURS, CC BY 2.0) to server-hosted Gemma 3 4B over a private SSH tunnel; it returned "Robin" and the signed entry reached `VERIFIED` on the mock Hornet. This is a real open-weight model run, not an offline/on-phone field test. The photo was sent to the model server for inference, but not anchored.

Conditional extras, only if they land before the deadline — do not present as
working today:

- **Offline phone model.** Run a vision model on the capture device itself; the existing real Gemma run was server-hosted over a private tunnel, not offline or outdoors.
- **Real commons.** Export `MONGODB_URI` so the Atlas observation store fills
  in similar-sightings search; the demo currently reports "no observation
  store configured".
- **Explorer mismatch.** The reused ledger/explorer tamper + restore routes
  (demo-only) show `PAYLOAD_MISMATCH` side by side.
- **Darwin Core export.** Not implemented.

## Honest talking points (if judges ask)

- **"Isn't tampering cheating?"** Two different things: in the field client,
  editing a queued entry is a _pre-sync_ event — the seal cracks and sync
  refuses to send it. Separately, the reused ledger's demo-only tamper
  endpoint mutates the application copy _after_ anchoring to show
  `PAYLOAD_MISMATCH` detection. Neither is a shipped feature; both demonstrate
  detection.
- **"Why not just trust the ledger?"** We do — the block is the reference. The
  failure mode is the application's own copy, the thing operators actually read.
- **"Doesn't a ledger make a bad ID true?"** No. Integrity ≠ accuracy. The model
  carries accuracy; the ledger carries provenance.
- **"Why a public ledger at all?"** Attribution, citability, and an open commons
  that no platform owns — plus cross-institution trust without a middleman.
- **"How big is the space?"** For scale only: GBIF's 2025 guide to publishing
  survey data reports more than 3 billion occurrence records from about 2,300
  institutions ([source](https://docs.gbif.org/guide-publishing-survey-data/en/)).
  That is the biodiversity-data ecosystem, not Vickrey's users or market, and
  it is not evidence that those records lack provenance.
- **"Doesn't the observer just rubber-stamp the model?"** They can, and the
  record says so: the sealed payload keeps both the model's suggestion and
  whether the person confirmed or corrected it.
- **"Endangered species?"** Precise location, photos, and notes never go
  on-chain. The anchor carries the commitment hash, device signature,
  timestamp, a coarse (rounded) location, and a species summary — obscuring
  further is a deliberate policy choice, not a claim of secrecy.
