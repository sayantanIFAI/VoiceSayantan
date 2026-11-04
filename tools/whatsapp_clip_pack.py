"""Listening pack for the recorded "WhatsApp" clip: the same sentence with the recording as it was, and with its top end cut at several frequencies (agent/clip_conditioning.py).

    python tools/whatsapp_clip_pack.py        (on the pod) -> /tmp/wa_pack/wa_*.wav and answer_sheet.md

Each file is one sentence said once per variant, numbered. Candidate 1 is the recording exactly as it was (the hiss and crackle you reported); 2.. cut more and more of the top end, every one with the 8 ms edge fade.
The listener marks the best number; set TTS_WHATSAPP_LOWPASS_HZ to that cutoff (deploy/env.sh) and restart the voice server. The sentence is rebuilt here from the voice's own pieces and the same splice rules as
tts_server.py (agent/whatsapp_tts.py, the loudness match, agent/prosody.assemble), so it is a faithful comparison of the clip's treatment, not a recording of the live server.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import wave

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import clip_conditioning, whatsapp_tts  # noqa: E402
from agent.prosody import ProsodyParams, assemble  # noqa: E402

TTS = os.environ.get("TTS_URL", "http://localhost:8002/synthesize")
OUT = os.environ.get("WA_PACK_DIR", "/tmp/wa_pack")
CLIP = os.environ.get(
    "TTS_WHATSAPP_CLIP_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "whatsapp_en.wav"),
)
SENTENCES = [
    "এই নম্বরে কি হোয়াটসঅ্যাপ আছে, অনলাইন পেমেন্ট করতে পারবেন?",
    "আপনার হোয়াটসঅ্যাপে একটা পেমেন্ট লিংক পাঠানো হবে।",
]
VARIANTS = [
    ("as it was", 0.0, 0.0),
    ("cut at 6500 Hz", 6500.0, 0.008),
    ("cut at 5000 Hz", 5000.0, 0.008),
    ("cut at 4500 Hz (the new default)", 4500.0, 0.008),
    ("cut at 3800 Hz", 3800.0, 0.008),
    ("cut at 3200 Hz", 3200.0, 0.008),
]
NUMBERS = ["এক", "দুই", "তিন", "চার", "পাঁচ", "ছয়"]


def synth(text: str) -> tuple[np.ndarray, int]:
    req = urllib.request.Request(
        TTS,
        data=json.dumps({"text": text, "lang": "bn", "pauses": False}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with wave.open(__import__("io").BytesIO(urllib.request.urlopen(req, timeout=60).read())) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768, w.getframerate()


def rms(a: np.ndarray) -> float:
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def build(sentence: str, clip: np.ndarray, sr: int, lowpass_hz: float, fade_s: float, voice_cache: dict) -> np.ndarray:
    """The sentence as tts_server._render builds it: voice pieces, the recording matched to their loudness, the same assembly."""
    clip = clip_conditioning.condition(clip, sr, lowpass_hz, fade_s)
    rendered: list[tuple[np.ndarray, str]] = []
    slots: list[int] = []
    parts = whatsapp_tts.split(sentence, "bn")
    for idx, (kind, value) in enumerate(parts):
        if kind == "wa":
            slots.append(len(rendered))
            rendered.append((clip, "none"))
            if value:
                rendered.append((voice_cache.setdefault(value, synth(value))[0], "none"))
            continue
        before_wa = idx + 1 < len(parts) and parts[idx + 1][0] == "wa"
        rendered.append((voice_cache.setdefault(value, synth(value))[0], "none" if before_wa else "sentence"))
    others = [r for i, (r, _k) in enumerate(rendered) if i not in slots and len(r)]
    target = float(np.median([rms(r) for r in others]))
    for i in slots:
        r = rms(rendered[i][0])
        if r > 0 and target > 0:
            rendered[i] = (np.clip(rendered[i][0] * min(max(target / r, 0.25), 4.0), -1.0, 1.0), rendered[i][1])
    return assemble(rendered, sr, ProsodyParams(), True)


def main() -> None:
    clip, csr = sf.read(CLIP, dtype="float32")
    if clip.ndim > 1:
        clip = clip.mean(axis=1)
    os.makedirs(OUT, exist_ok=True)
    sheet = [
        "# WhatsApp clip: listening sheet",
        "",
        "For each file: the best number (the clearest 'WhatsApp' with no hiss or crackle), or `none`. Candidate 1 is the recording as it was.",
        "",
    ]
    voice_cache: dict = {}
    for n, sentence in enumerate(SENTENCES, 1):
        pieces, rate = [], csr
        for k, (_label, hz, fade) in enumerate(VARIANTS):
            wav = build(sentence, clip, csr, hz, fade, voice_cache)
            number, rate = synth(NUMBERS[k])
            gap, long_gap = np.zeros(int(rate * 0.35), dtype=np.float32), np.zeros(int(rate * 0.9), dtype=np.float32)
            pieces += [number, gap, wav, long_gap]
        with wave.open(f"{OUT}/wa_{n}.wav", "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((np.clip(np.concatenate(pieces), -1, 1) * 32767).astype(np.int16).tobytes())
        sheet.append(
            f"- `wa_{n}.wav` {sentence}: "
            + " | ".join(f"{k + 1}: {v[0]}" for k, v in enumerate(VARIANTS))
            + "  -> best: ___"
        )
    with open(f"{OUT}/answer_sheet.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(sheet))
    print(f"wrote {len(SENTENCES)} files and answer_sheet.md to {OUT}")


if __name__ == "__main__":
    main()
