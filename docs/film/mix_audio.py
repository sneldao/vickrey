import subprocess
from pathlib import Path

vo = [
    ("01", 0.8),
    ("02", 10.3),
    ("03", 18.4),
    ("04", 29.0),
    ("05", 38.4),
    ("06", 44.2),
    ("07", 55.0),
    ("08", 68.8),
    ("09", 81.3),
]
sfx = [
    ("sfx-shutter", 18.6, 1.6),
    ("sfx-seal", 38.7, 10.0),
    ("sfx-crack", 47.7, 2.2),
    ("sfx-verify", 60.6, 0.9),
]
inputs = [
    "-i",
    "audio/bed.mp3",
    "-i",
    "audio/sfx-ambience.mp3",
    "-i",
    "audio/sfx-ambience.mp3",
]
for n, _ in vo:
    inputs += ["-i", f"audio/vo-{n}.mp3"]
for n, _, _ in sfx:
    inputs += ["-i", f"audio/{n}.mp3"]
f = []
f.append(
    "[0:a]volume=0.20,afade=t=in:d=2,afade=t=out:st=88:d=4,aformat=channel_layouts=stereo[bed]"
)
f.append(
    "[1:a]volume=1.6,afade=t=in:d=1.5,afade=t=out:st=11:d=4,aformat=channel_layouts=stereo[amb1]"
)
f.append(
    "[2:a]volume=1.0,afade=t=in:d=3,afade=t=out:st=8:d=3,adelay=81000|81000,aformat=channel_layouts=stereo[amb2]"
)
labels = []
for i, (n, t) in enumerate(vo):
    ms = int(t * 1000)
    f.append(f"[{3 + i}:a]aformat=channel_layouts=stereo,adelay={ms}|{ms}[v{i}]")
    labels.append(f"[v{i}]")
f.append(
    "".join(labels) + f"amix=inputs={len(vo)}:normalize=0,volume=1.0,asplit=2[vo][vosc]"
)
f.append(
    "[bed][vosc]sidechaincompress=threshold=0.03:ratio=6:attack=80:release=600[bedd]"
)
sl = []
for j, (n, t, g) in enumerate(sfx):
    ms = int(t * 1000)
    k = 3 + len(vo) + j
    f.append(f"[{k}:a]volume={g},aformat=channel_layouts=stereo,adelay={ms}|{ms}[s{j}]")
    sl.append(f"[s{j}]")
f.append(
    "[vo][bedd][amb1][amb2]"
    + "".join(sl)
    + f"amix=inputs={4 + len(sfx)}:normalize=0,atrim=0:92,loudnorm=I=-16:TP=-1.5:LRA=11[out]"
)
cmd = (
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
    ]
)
Path("assets").mkdir(exist_ok=True)
subprocess.run(cmd, check=True)
