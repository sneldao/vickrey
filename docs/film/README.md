# Launch film source (HyperFrames)

92-second, 16:9 narrated film. The rendered MP4 and media assets are **not** committed
(500 KB hook); the MP4 is delivered as a session artifact.

## Story (storyboard)

| Time    | Beat                                              | Visual                                                                         | Truth labels on screen                                                                                                         |
| ------- | ------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| 0–10 s  | Hook: a note can be changed later                 | Credited robin photo, handwritten note where "Robin" is struck out to "Magpie" | "Illustrative photo, not a field test" + Alexis LOURS, CC BY 2.0                                                               |
| 10–18 s | Value: a signed record anyone can check           | Wax seal + "Seal what you saw."                                                | —                                                                                                                              |
| 18–29 s | Photo → Gemma suggestion                          | Real app captures, zooms on the suggestion card                                | "Time compressed · real wait ≈ 20 s · Gemma 3 4B, server-hosted"; "Confidence is the model's own score, not measured accuracy" |
| 29–38 s | The model suggests, you decide                    | Confirm & seal highlighted                                                     | —                                                                                                                              |
| 38–44 s | Signed and chained                                | Seal press over the sealed capture                                             | —                                                                                                                              |
| 44–55 s | Tamper → crack → refusal                          | Cracked journal row, refusal banner                                            | "Edited after sealing → sync refused"                                                                                          |
| 55–68 s | Restore → sync → VERIFIED; what leaves the device | Anchored capture, proof details, privacy panel                                 | "A hosted model does receive the photo"                                                                                        |
| 18–68 s | (persistent)                                      | —                                                                              | "Real app capture · Ledger: mock Hornet demo"                                                                                  |
| 68–81 s | GBIF ecosystem scale                              | Typographic stat                                                               | Source line + "Context for scale only — not Vickrey users…"                                                                    |
| 81–92 s | Open source, early; not yet                       | Two columns + repo                                                             | On-phone model, public ledger, Darwin Core, outdoor use listed as not yet                                                      |

Narration script: `narration.json` (captions in `index.html` are timed to the generated takes).

## Rebuild

1. `python3 gen_audio.py vo|music|sfx` (needs `ELEVENLABS_API_KEY`; voice "George", `eleven_multilingual_v2`, Music `music_v1` instrumental, sound-generation SFX).
2. `python3 mix_audio.py` — places narration/SFX, ducks the music bed under the voice (sidechain), loudness-normalises to −16 LUFS → `assets/mix.m4a`.
3. Product captures: `scripts/demo_field.sh`, then a Playwright run at 1440×900 producing `assets/desk-0*.png`; `assets/robin.jpg` is the Wikimedia Commons file; `assets/caveat.ttf` is Caveat (OFL) from google/fonts.
4. `npx hyperframes@0.8.147 init`, drop in `index.html` + `assets/`, then `npx hyperframes lint && npx hyperframes render`.
