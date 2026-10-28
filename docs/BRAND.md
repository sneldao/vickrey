# Brand — Vickrey, and the Seal

## The name is the metaphor

**Vickrey** is named for **William Vickrey**, the economist behind the
**sealed-bid auction** (second-price sealed-bid, Nobel Prize 1996). The seal was
never a design choice — it is the name's origin story.

- A **sealed bid** commits to a value **without revealing it**, cannot be changed
  after close, and is opened only under the rules.
- Vickrey's contribution was **mechanism design**: rules that make **truth the
  winning strategy**.
- Cryptography has the same primitive — a **commitment scheme**: commit now,
  reveal later, no cheating in between.

A sealed bid _is_ a commitment scheme. Our anchor _is_ a commitment scheme.
**The auction and the product are the same idea pointed at different problems:**

> Vickrey made **people** tell the truth by design. Vickrey makes **records** tell
> the truth by design. Both work by **sealing.**

## The mapping (nothing is decoration)

| Vickrey auction                   | Vickrey product                            |
| --------------------------------- | ------------------------------------------ |
| Sealed bid                        | Signed observation at capture              |
| Bid committed, value hidden       | Exact coordinates withheld, hash committed |
| Sealed until the rules open it    | Verified when solid + milestone            |
| Bids can't be altered after close | Tamper **cracks the seal**                 |
| Truth is the dominant strategy    | Integrity is the default                   |

Withheld here means **exact** coordinates: the anchor still publishes a coarse
location and a species summary — hiding those entirely is a policy choice,
not something the scheme guarantees.

## Narrative spine

1. **1961.** An economist proposes an auction where everyone seals their bid.
   Secrecy plus commitment makes honesty rational.
2. **The insight.** The sealed envelope is a commitment: bound to a value not yet
   shown.
3. **The turn.** We pointed that mechanism at the world. Your phone seals what you
   saw; the network countersigns; nobody can quietly rewrite it.
4. **The reveal.** The seal was never a design choice. **It's the name.**

## Taglines

**Canonical — one product name, one slogan. Every surface uses exactly this:**

- **Vickrey — A sealed bid on what you saw.** (`<title>`, hero, masthead,
  README). The other lines below are supporting copy, never a substitute title.
- **Sealed at capture. Countersigned by the network.** (supporting copy)
- **Truthful by design.** (supporting copy)
- Closing line: _"Vickrey proved that a sealed bid makes people honest. We just
  asked the same of a memory."_

## Colour — every hue is a role in the mechanism

| Name              | Hex       | Means                                    |
| ----------------- | --------- | ---------------------------------------- |
| **Bone**          | `#F4EFE3` | Paper; the field-journal ground          |
| **Iron-gall ink** | `#1C1A17` | Text, hand-drawn lines                   |
| **Wax crimson**   | `#A32020` | The seal itself — signature & anchor     |
| **Notary indigo** | `#1E2A4A` | The ledger's authority; the counterstamp |
| **Moss**          | `#3F5C3A` | VERIFIED — earned, organic               |
| **Pencil grey**   | `#8A8578` | PENDING — provisional, unfinished        |

**The one rule:** crimson is the seal. When a record is tampered, the crimson
**cracks**; when restored, it **re-forms**. Mismatch is not a bolted-on red
alert — it is _the seal breaking_, which the audience already understands.

Status mapping: `VERIFIED` → Moss · `PENDING` → Pencil grey ·
`PAYLOAD_MISMATCH` → cracked Wax crimson · `NOT_SOLID` → muted ink.

## Type — three voices

- **Display serif** (old-world, pressed-specimen energy) — species names, title
  cards, editorial headings.
- **Monospace** (the machine's voice) — hashes, timestamps, block ids, model ids.
- **Handwritten script** — field notes, annotations, the narrator's asides.

## Motion & sound principles

- **Seal press**: capture stamps with a slight overshoot and a haptic _thunk_.
- **Notary stamp**: a soft stamp-sound when a row reaches `VERIFIED`.
- **The crack**: a sharp snap when a seal is tampered; the crimson fractures.
- **Re-form**: the intact seal resolves underneath when a record is restored.
- Honour `prefers-reduced-motion`: replace stamps/cracks with instant state and a
  colour pulse.

## The signature moment

Three seconds, no words: a tampered record **cracks like ice**, and the original
seal **re-forms perfectly underneath**. That single shot explains the product.
