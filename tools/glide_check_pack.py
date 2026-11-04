"""Listening check for the glide rule on REAL sentences: each sentence is said as the bot sends it today (rules off) and with the rule on (agent/bn_glide_rules.py), numbered, so a listener can confirm the change before it goes live.

    python tools/glide_check_pack.py       (on the pod, from a copy of this repo) -> /tmp/glide_check/*.wav and answer_sheet.md

The text goes through the same steps as a reply (verbalize, then bn_respell.apply); only the glide rules differ between candidate 1 and candidate 2.
"""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.request
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import bn_glide_rules, bn_respell  # noqa: E402
from agent.speech_norm import verbalize  # noqa: E402

TTS = os.environ.get("TTS_URL", "http://localhost:8002/synthesize")
OUT = os.environ.get("GLIDE_CHECK_DIR", "/tmp/glide_check")
RULES = {"coda": "e", "before_vowel": "e", "after_aa_o": "e"}
SENTENCES = [
    "আমি নম্বরটা শুনেছি 9 8 7 6 5 , 4 3 2 1 0। এটা কি ঠিক?",
    "আমি নম্বরটা শুনেছি 6 9 6 9 6 6 9 9 6 9। এটা কি ঠিক?",
    "ওই সময়ে চলে আসুন, হাতে এক থেকে দুই ঘণ্টা সময় নিয়ে আসবেন।",
    "ডাক্তার বসেন না। সব কিছু ঠিক হয়েছে, দয়া করে অপেক্ষা করুন।",
    "রোগীর বয়স কত? মাথায় ব্যথা হয় কি?",
    "আপনার মেয়ের নাম বলবেন? পেয়েছি, ভয় নেই।",
]


def synth(text: str) -> tuple[np.ndarray, int]:
    req = urllib.request.Request(
        TTS, data=json.dumps({"text": text, "lang": "bn"}).encode(), headers={"Content-Type": "application/json"}
    )
    with wave.open(io.BytesIO(urllib.request.urlopen(req, timeout=60).read())) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768, w.getframerate()


def spoken(sentence: str, rules_on: bool) -> str:
    """The text the voice receives: the reply's own steps, with the glide rules on or off (the listener-override file is left out of both)."""
    saved = (os.environ.get("BN_GLIDE_RULES"), bn_respell.OVERRIDES_FILE)
    os.environ["BN_GLIDE_RULES"] = ",".join(f"{c}={v}" for c, v in RULES.items()) if rules_on else ""
    bn_respell.OVERRIDES_FILE = "/nonexistent"
    bn_respell._OVERRIDES_CACHE.update(mtime=None, data={})  # noqa: SLF001
    bn_glide_rules.RULES_FILE = "/nonexistent"
    bn_glide_rules._FILE_CACHE.update(mtime=None, data={})  # noqa: SLF001
    try:
        return bn_respell.apply(verbalize(sentence, "bn"), "bn")
    finally:
        if saved[0] is None:
            os.environ.pop("BN_GLIDE_RULES", None)
        else:
            os.environ["BN_GLIDE_RULES"] = saved[0]
        bn_respell.OVERRIDES_FILE = saved[1]


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    numbers = ["এক", "দুই"]
    sheet = [
        "# Glide rule on real sentences: listening sheet",
        "",
        "For each file: 1 (today), 2 (the rule on: নয়->নএ, ছয়->ছএ, সময়ে->শমএ, ...), or `none`.",
        "",
    ]
    for i, sentence in enumerate(SENTENCES, 1):
        pieces, rate = [], 22050
        texts = [spoken(sentence, False), spoken(sentence, True)]
        for n, text in enumerate(texts):
            num, rate = synth(numbers[n])
            wav, _ = synth(text)
            pieces += [
                num,
                np.zeros(int(rate * 0.35), dtype=np.float32),
                wav,
                np.zeros(int(rate * 0.9), dtype=np.float32),
            ]
        with wave.open(f"{OUT}/check_{i}.wav", "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((np.clip(np.concatenate(pieces), -1, 1) * 32767).astype(np.int16).tobytes())
        sheet.append(f"- `check_{i}.wav` {sentence}\n  - 1: {texts[0]}\n  - 2: {texts[1]}\n  -> best: ___")
    with open(f"{OUT}/answer_sheet.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(sheet))
    print(f"wrote {len(SENTENCES)} files and answer_sheet.md to {OUT}")


if __name__ == "__main__":
    main()
