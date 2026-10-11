# Partner stack — maximising Hacktoberfest prize categories

Week 1 offers one $250 overall prize, six $200 featured partner prizes, and ten $100 partner prizes. A participant may win **only one prize per challenge**: the amounts cannot be added together for a single entry. Every eligible entry is automatically considered for the overall prize and each partner category it meaningfully uses. Writing quality is weighted most heavily. See the [Week 1 rules](https://dev.to/page/hacktoberfest-week1-2026-10-05-contest-rules) and [challenge categories](https://dev.to/challenges/hacktoberfest-week1-2026-10-05).

## The target stack

The roles below are the **plan** unless noted otherwise. Verified today:
the field client signs, seals, verifies, and syncs locally against a mock
Hornet via the anchor relay, and real server-hosted Gemma 3 4B inference ran
through the field client over a private SSH tunnel (not on-device/offline).
The Atlas observation store is unit-tested against
a fake store (`MONGODB_URI` was unset in the demo). Temporal is scaffold only.
The remaining partners are unintegrated targets.

| #   | Partner            | Category                   | Prize | Target role in Vickrey                                             |
| --- | ------------------ | -------------------------- | ----- | ------------------------------------------------------------------ |
| 1   | **Gemma**          | Best Use of Gemma          | $200  | Real server-hosted Gemma 3 4B vision ID; on-device remains planned |
| 2   | **Render**         | Best Use of Render         | $200  | Host the commons API, the explorer, and the agent front end        |
| 3   | **Temporal**       | Best Use of Temporal       | $100  | Durable sync/anchor workflow that survives the offline gap         |
| 4   | **MongoDB Atlas**  | Best Use of MongoDB Atlas  | $100  | Observation store + vector search for similar sightings            |
| 5   | **Mastra**         | Best Use of Mastra         | $100  | Agent runtime: tools that structure and drive an observation       |
| 6   | **Backboard**      | Best Use of Backboard      | $100  | Memory + RAG (and open-model comparison) for the logbook assistant |
| 7   | **ElevenLabs**     | Best Use of ElevenLabs     | $100  | Voice narration for the demo; transcribe field audio               |
| 8   | **Sentry**         | Best Use of Sentry         | $100  | Trace the ID→sign→sync agent (latency, tokens, cost)               |
| 9   | **GitHub Copilot** | Best Use of GitHub Copilot | $100  | Build the project; automate with Actions                           |
| 10  | **Entire**         | Best Use of Entire         | $100  | Share the agent sessions behind the build in the post              |

**Verified partner use:** Gemma 3 4B vision performed real server-hosted inference through the field client on a credited robin photo, and the resulting signed observation reached `VERIFIED` on mock Hornet. This supports consideration for Best Use of Gemma ($200); it does not prove on-device/offline use. Atlas remains fake-store-tested, Temporal a scaffold, Render undeployed; no other partner qualification is verified.

## Distinct roles (avoid "three orchestrators")

These overlap if left vague. Keep them clearly separated:

- **Temporal** — _durability_. Wraps `sync → POST /upload → poll solid/milestone
→ anchor` so a dropped signal retries and resumes. Not an agent; a workflow.
- **Mastra** — _reasoning + tools_. The agent that turns a raw observation into a
  structured, tagged record and drives the pipeline (tool calls, no retry logic).
- **Backboard** — _memory + retrieval_. Long-term memory and RAG for the logbook
  assistant, and/or comparing open-weight models through one API key.

## Why each fits (what to actually build)

- **Gemma** — verified: Gemma 3 4B ran on our server and classified a [Wikimedia Commons European robin photo](https://commons.wikimedia.org/wiki/File:European_robin_on_a_branch.jpg) (Alexis LOURS, CC BY 2.0) as "Robin" through the field client, before sealing and mock-ledger verification. The photo travelled to the server over an SSH tunnel. On-device/offline operation remains a goal, not a claim.
- **Render** — deploy `services/ledger` (web service) and `apps/explorer`
  (static site) from Git. Free tier is enough for hosting.
  - **Free-tier caveats:** web services sleep after ~15 min idle (cold start on
    wake), and persistent disks need a paid service → **persistence lives in
    MongoDB Atlas, not SQLite on Render's disk.**
  - The Temporal worker sleeps too on free, so **run the worker locally** for the
    demo and let Render host the API + explorer.
- **Temporal** — theme-perfect durability: signal drops mid-upload, the workflow
  retries and picks up where it left off.
- **MongoDB Atlas** — the commons data layer: store observations, use Atlas Vector
  Search to surface similar sightings ("others saw this near you"). Also solves
  Render's no-persistent-disk limitation.
- **Mastra** — orchestrate the ID→sign→sync agent over the open model; add tools
  (query commons, vector search, Darwin Core export).
- **Backboard** — give the logbook assistant memory/RAG; optionally compare
  open-weight models for species ID through a single Backboard API key.
- **ElevenLabs** — TTS narration for the demo video; optional transcription of
  field audio for the local model.
- **Sentry** — instrument the pipeline; show latency, tokens, cost and one real
  debug story in the write-up.
- **GitHub Copilot** — build with the coding agent / CLI and mention it.
- **Entire** — share the agent sessions that produced the project (also suggested:
  DevRelay, per the challenge template).

## Not used

- **DigitalOcean** — Render is the planned host instead; avoids buying
  credits. Nothing is deployed yet.
- **Qualcomm / Arduino (UNO Q)** — needs the board.
- **SerpApi** — online search conflicts with the offline, data-stays-local theme.

## Stretch (only if time remains)

| Partner                      | Prize | When it fits                                                     |
| ---------------------------- | ----- | ---------------------------------------------------------------- |
| **Thinking Machines Tinker** | $200  | Fine-tune a species model; show a clear gain over baseline       |
| **Prior Labs TabPFN**        | $200  | Anomaly detection on observations (flag odd or tampered records) |
| **Tiger Data**               | $100  | pgvector store for species similarity                            |

## Prize-priority gates

1. **Eligibility and complete entry first.** The repo's initial commit is October 6, inside the October 5–11 window, but the entrant must honestly explain reused Veles work. Submit one English-language post using the template and required tags, with a repository link and a demo URL or video by October 11 at 11:59 PM PDT. The organizer decides eligibility.
2. **Show the real Gemma proof clearly.** The field client now uses server-hosted open-weight Gemma 3 4B to classify a photo and seal it into a mock-ledger VERIFIED entry. Credit the image, show the real model ID and distinguish that result from the labelled sample path. Best Use of Gemma is a defensible category to list; do not claim offline/on-device identification.
3. **Outdoor proof and strong writing.** Capture a genuine field use if possible, keep the screen interaction short, and explain what worked and failed. Clearly separate the mock-ledger proof from live network anchoring and distinguish integrity from identification accuracy.
4. **Add at most one independently demonstrable partner integration if it improves the experience.** Render requires a reachable deployed service or front end; Atlas requires a live Atlas store and actual query; Temporal requires a running workflow with observable retry/resume. A configured endpoint, local fake, or scaffold alone does not qualify. Do not spend writing time on integrations that cannot be demonstrated before the cutoff.
5. **Optional evidence-based categories.** Entire applies if a real session is shared in the entry; GitHub Copilot applies only if that tool actually built/reviewed this project; ElevenLabs, Sentry, Backboard, Mastra and other partners require meaningful, demonstrated use. No unverified logo list.

Only one prize can be awarded to a participant in Week 1. Quality and eligibility outrank the number of categories named.
