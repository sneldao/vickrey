import json
import os
import sys
import urllib.request

KEY = os.environ["ELEVENLABS_API_KEY"]


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


what = sys.argv[1]
if what == "vo":
    prev = None
    lines = json.load(open("lines.json"))
    for i, (n, t) in enumerate(lines):
        post(
            "https://api.elevenlabs.io/v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb?output_format=mp3_44100_128",
            {
                "text": t,
                "model_id": "eleven_multilingual_v2",
                "previous_text": lines[i - 1][1] if i else None,
                "next_text": lines[i + 1][1] if i + 1 < len(lines) else None,
                "voice_settings": {
                    "stability": 0.6,
                    "similarity_boost": 0.75,
                    "style": 0.1,
                    "use_speaker_boost": True,
                    "speed": 0.95,
                },
            },
            f"audio/vo-{n}.mp3",
        )
elif what == "music":
    post(
        "https://api.elevenlabs.io/v1/music",
        {
            "prompt": "Quiet, intimate instrumental for a nature documentary short: solo fingerpicked acoustic guitar and soft felt piano, warm cello pad entering midway, gentle and unhurried, 72 bpm, morning woodland mood, no drums, no vocals, no build-up drops, sparse enough to sit under narration, soft resolved ending.",
            "music_length_ms": 92000,
            "model_id": "music_v1",
            "force_instrumental": True,
        },
        "audio/bed.mp3",
    )
elif what == "sfx":
    for name, text, d in [
        (
            "ambience",
            "Early morning English woodland ambience, distant songbirds, soft breeze in leaves, no voices, no traffic",
            22,
        ),
        (
            "seal",
            "A single soft wax seal stamp pressed onto thick paper, warm low thunk, short",
            1.5,
        ),
        (
            "crack",
            "A brittle dry wax seal cracking once, sharp small crack, close-up, short",
            1.5,
        ),
        ("shutter", "A single quiet camera shutter click", 1),
        ("verify", "A soft rubber notary stamp on paper, gentle and satisfying", 1.2),
    ]:
        post(
            "https://api.elevenlabs.io/v1/sound-generation",
            {"text": text, "duration_seconds": d, "prompt_influence": 0.5},
            f"audio/sfx-{name}.mp3",
        )
