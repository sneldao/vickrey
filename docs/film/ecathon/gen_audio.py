"""ECATHON film audio. Usage: python3 gen_audio.py vo|music|sfx  (needs ELEVENLABS_API_KEY)."""

import json
import os
import sys
import urllib.error
import urllib.request

KEY = os.environ["ELEVENLABS_API_KEY"]
VOICE = "JBFqnCBsd6RMkjVDRZzb"  # George


def post(url, body, out):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "xi-api-key": KEY,
            "content-type": "application/json",
            "accept": "audio/mpeg",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            open(out, "wb").write(r.read())
            print("ok", out)
    except urllib.error.HTTPError as e:
        print("ERR", out, e.code, e.read()[:300])


os.makedirs("audio", exist_ok=True)
what = sys.argv[1]
if what == "vo":
    lines = json.load(open("narration.json"))
    for i, (n, t) in enumerate(lines):
        post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_128",
            {
                "text": t,
                "model_id": "eleven_multilingual_v2",
                "previous_text": lines[i - 1][1] if i else None,
                "next_text": lines[i + 1][1] if i + 1 < len(lines) else None,
                "voice_settings": {
                    "stability": 0.55,
                    "similarity_boost": 0.75,
                    "style": 0.15,
                    "use_speaker_boost": True,
                    "speed": 0.97,
                },
            },
            f"audio/vo-{n}.mp3",
        )
elif what == "music":
    post(
        "https://api.elevenlabs.io/v1/music",
        {
            "prompt": "Dark, minimal, tense-then-resolving cinematic electronic underscore for a privacy-tech film: low sub pulse like a slow heartbeat, sparse glassy plucks and a soft analog pad, a subtle rising texture that thins into many tiny identical clicks (a crowd of dots), then a warm resolved final chord. 70 bpm, no drums, no vocals, sits under narration.",
            "music_length_ms": 92000,
            "model_id": "music_v1",
            "force_instrumental": True,
        },
        "audio/bed.mp3",
    )
elif what == "sfx":
    for name, text, d in [
        (
            "seal",
            "A single soft wax seal stamp pressed onto thick paper, warm low thunk, short",
            1.5,
        ),
        (
            "crack",
            "A brittle glass-like fracture spreading across a pane, one sharp crack with a short ringing tail, cinematic",
            2.0,
        ),
        (
            "pin",
            "A tiny soft tick, like a pin dropped onto a wooden map, very short",
            0.5,
        ),
        (
            "dissolve",
            "A shimmering granular whoosh of many tiny glassy particles dissolving and rearranging, 3 seconds",
            3.0,
        ),
        ("verify", "A soft rubber notary stamp on paper, gentle and satisfying", 1.2),
        ("key", "A single soft mechanical keyboard keystroke, close and quiet", 0.4),
    ]:
        post(
            "https://api.elevenlabs.io/v1/sound-generation",
            {"text": text, "duration_seconds": d, "prompt_influence": 0.5},
            f"audio/sfx-{name}.mp3",
        )
