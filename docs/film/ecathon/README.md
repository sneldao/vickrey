# ECATHON film — "Which one is yours?"

92 s, 16:9, narrated, captions burned in. Concept and beats: [`../ECATHON_FILM.md`](../ECATHON_FILM.md).

## What is real, what is authored

| Scene                                 | Source                                                                                                                                                                                                                          |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0 · the double crime (0–12 s)         | Authored telemetry viewfinders across three edge domains (emissions/grid, biologics cold-chain, ecological survey); badge notes they are illustrative edge logs framing the horizontal primitive.                               |
| A · 3B-record wedge & map (12–22 s)   | Cites GBIF (2025, 3B+ records across 2,300+ institutions; labelled "context for scale — not Vickrey users") and Lindenmayer & Scheele, _Science_ 356 (2017) ("Do not publish"), then dissolves into the authored poacher's map. |
| B · seal (22–32 s)                    | Real field-app capture (sample walk). The suggestion is the app's labelled sample; no model ran.                                                                                                                                |
| C · the crack (32–41 s)               | Real field-app capture, shielded mode, mock zanchor. The full-frame fracture is authored over the real UI.                                                                                                                      |
| D · the crowd (41–59 s)               | Authored visualisation, badge says "not chain data". It illustrates the anchor shape, it is not a block explorer.                                                                                                               |
| E · a stranger tries (59–68 s)        | Real output of `scripts/demo_zcash.sh` against the **mock** zanchor (31 checks), `assets/zcash_walk.txt`.                                                                                                                       |
| F · the script seals itself (68–78 s) | Real: `seal.py` hashes `narration.json` and anchors it. Receipt is from the **mock** (hash + counter, not a tx).                                                                                                                |
| G · close (78–92 s)                   | Claims copied from `docs/STATUS.md`. The 33/33 live-node run is cited, not shown.                                                                                                                                               |

What the film does **not** claim: that the footage is from a live Zcash node, that the
photo never reaches the model (a hosted model does receive it), or that rewards / an
on-phone model exist.

## Check the seal (scene F)

```bash
shasum -a 256 docs/film/ecathon/narration.json   # must equal SEAL.json → sha256
```

`SEAL.json` holds the receipt. Changing a word in `narration.json` changes the hash:
re-run `seal.py` (against a fresh service; a replayed commitment is refused with 409)
and rebuild.

## Rebuild

From `docs/film/ecathon/`, with `ELEVENLABS_API_KEY` set (on macOS with the python.org
build, also `export SSL_CERT_FILE=$(python3 -c "import certifi;print(certifi.where())")`):

1. `python3 gen_audio.py vo && python3 gen_audio.py sfx && python3 gen_audio.py music`
2. Mock services: `python3 ../../../scripts/mock_zanchor.py --port 8801 --notes 20`,
   `python3 -m http.server 8802 --directory ../../../apps/explorer`,
   `python3 -m http.server 8803 --directory ../../../apps/field`
3. `python3 capture_field.py` (Playwright, 1440×900 @2×) → `assets/field-*.png`, `assets/el-*.png`
4. `bash ../../../scripts/demo_zcash.sh --zanchor http://127.0.0.1:8801 > assets/zcash_walk.txt`
5. `python3 seal.py`
6. `python3 build.py` → `index.html` (from `index.src.tpl`), captions, `assets/mix.m4a`
7. `npx hyperframes check && npx hyperframes render`

`audio/`, `assets/` and renders are not committed.
