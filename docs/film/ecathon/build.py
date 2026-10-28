"""Build the ECATHON film inputs.

  python3 build.py         -> assets/mix.m4a + index.html (from index.src.tpl)

Reads: narration.json, audio/*.mp3, SEAL.json. Needs ffmpeg/ffprobe.
Run `python3 gen_audio.py vo|sfx|music` and `python3 seal.py` first.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

DUR = 92.0
VO_START = {
    "00": 0.35,
    "01": 11.80,
    "02": 22.20,
    "03": 32.40,
    "04": 41.40,
    "05": 59.00,
    "06": 68.40,
    "07": 78.20,
}
# (sfx name, time, gain)
SFX = [
    ("shutter", 0.15, 0.85),
    ("pin", 1.55, 0.65),
    ("shutter", 2.60, 0.85),
    ("pin", 3.85, 0.65),
    ("shutter", 5.00, 0.85),
    ("pin", 6.10, 0.65),
    ("verify", 13.10, 0.75),
    ("pin", 16.3, 0.7),
    ("pin", 16.6, 0.6),
    ("pin", 16.9, 0.6),
    ("pin", 17.2, 0.6),
    ("verify", 19.1, 0.8),
    ("seal", 22.35, 0.8),
    ("seal", 28.95, 1.0),
    ("crack", 35.65, 1.2),
    ("dissolve", 45.4, 0.9),
    ("verify", 61.8, 0.6),
    ("verify", 65.5, 0.6),
    ("verify", 66.5, 0.6),
    ("seal", 73.95, 1.0),
    ("seal", 78.45, 0.9),
]

CACHE = Path("audio/durs.json")


def have_ffmpeg():
    return shutil.which("ffmpeg") and shutil.which("ffprobe")


def dur(path):
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return float(out.strip())


narr = dict((n, t) for n, t in json.load(open("narration.json")))
if have_ffmpeg():
    durs = {n: dur(f"audio/vo-{n}.mp3") for n in narr}
    CACHE.write_text(json.dumps(durs))
else:
    print("ffmpeg missing: using cached VO durations, keeping existing mix")
    durs = json.load(open(CACHE))

for n, s in VO_START.items():
    print(f"vo-{n}: {s:6.2f} -> {s + durs[n]:6.2f}")

# overlaps are a bug, not a style
order = sorted(VO_START)
for a, b in zip(order, order[1:]):
    assert VO_START[a] + durs[a] < VO_START[b] - 0.15, f"vo-{a} runs into vo-{b}"

# ---- captions: split at phrase punctuation, time by character share
caps = []
for n in order:
    text = narr[n]
    parts = [p.strip() for p in re.findall(r"[^.,:?;]+[.,:?;]?", text) if p.strip()]
    # merge very short parts forward
    merged = []
    for p in parts:
        if merged and len(merged[-1]) < 14:
            merged[-1] += " " + p
        else:
            merged.append(p)
    total = sum(len(p) for p in merged)
    t = VO_START[n] + 0.05
    span = durs[n] - 0.25
    for p in merged:
        d = span * len(p) / total
        caps.append([round(t, 2), round(t + d, 2), p.rstrip(",")])
        t += d
Path("captions.json").write_text(json.dumps(caps, indent=1))

# ---- index.html
seal = json.load(open("SEAL.json"))
html = Path("index.src.tpl").read_text()
html = html.replace("/*@SEAL@*/ null", json.dumps(seal))
html = html.replace("/*@CAPS@*/ []", json.dumps(caps, ensure_ascii=False))
Path("index.html").write_text(html)
print("wrote index.html,", len(caps), "captions")

# ---- audio mix
if not have_ffmpeg():
    raise SystemExit(0)

inputs = ["-i", "audio/bed.mp3"]
for n in order:
    inputs += ["-i", f"audio/vo-{n}.mp3"]
for name, _, _ in SFX:
    inputs += ["-i", f"audio/sfx-{name}.mp3"]
f = [
    f"[0:a]volume=0.22,afade=t=in:d=2,afade=t=out:st={DUR - 4}:d=4,aformat=channel_layouts=stereo[bed]"
]
labels = []
for i, n in enumerate(order):
    ms = int(VO_START[n] * 1000)
    f.append(f"[{1 + i}:a]aformat=channel_layouts=stereo,adelay={ms}|{ms}[v{i}]")
    labels.append(f"[v{i}]")
f.append("".join(labels) + f"amix=inputs={len(order)}:normalize=0,asplit=2[vo][vosc]")
f.append("[vosc]apad=whole_dur=96[vosc2]")
f.append(
    "[bed][vosc2]sidechaincompress=threshold=0.03:ratio=6:attack=80:release=600[bedd]"
)
sl = []
for j, (name, t, g) in enumerate(SFX):
    ms = int(t * 1000)
    k = 1 + len(order) + j
    f.append(f"[{k}:a]volume={g},aformat=channel_layouts=stereo,adelay={ms}|{ms}[s{j}]")
    sl.append(f"[s{j}]")
f.append(
    "[vo][bedd]"
    + "".join(sl)
    + f"amix=inputs={2 + len(SFX)}:normalize=0,atrim=0:{DUR},loudnorm=I=-16:TP=-1.5:LRA=11[out]"
)
Path("assets").mkdir(exist_ok=True)
subprocess.run(
    ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    + inputs
    + [
        "-filter_complex",
        ";".join(f),
        "-map",
        "[out]",
        "-ar",
        "48000",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "assets/mix.m4a",
    ],
    check=True,
)
print("wrote assets/mix.m4a", round(dur("assets/mix.m4a"), 2), "s")
