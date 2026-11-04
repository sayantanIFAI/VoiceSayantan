"""Second listening pack for য়: the Bengali voice cannot say a final য় (it adds a vowel: "noyo", "chhoyo", "somoyoje"), and one spelling per word has not worked. This pack puts four different KINDS of answer side by side.

    python tools/yo_pack_round2.py        (on the pod) -> /tmp/yo2_pack/*.wav and answer_sheet.md

 words    nine / six / hoy / somoye, each in a frame ("সাত _ আট"), candidate 1 = today's spelling. The others are (a) the spellings the recogniser finds most likely to be the intended word (agent search, 2026-11-04:
          log P of the intended text under the Bengali CTC head), (b) the diphthong written as a vowel sign (নৈ), which gave one clean vowel peak with a high end formant, and (c) for the two digits the English voice
          saying "nine" / "six" (the same kind of splice as the WhatsApp recording).
 phone    a whole phone number read five ways: today; only 6 and 9 by the English voice; every digit by the English voice; the English digit words written in Bengali letters (নাইন সিক্স ...) said by the Bengali voice.
The listener marks the best number per file. Nothing in the agent changes until a pick comes back.
"""

from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.request
import wave

import numpy as np

TTS = os.environ.get("TTS_URL", "http://localhost:8002/synthesize")
OUT = os.environ.get("YO2_PACK_DIR", "/tmp/yo2_pack")
NUMBERS = ["এক", "দুই", "তিন", "চার", "পাঁচ", "ছয়"]
GAP = 0.06

# word -> (frame left, frame right, [(label, spelling or "EN:<english word>")])
WORDS = {
    "nine": (
        "সাত",
        "আট",
        [
            ("today", "নয়"),
            ("diphthong", "নৈ"),
            ("vowels", "নঅই"),
            ("search 1", "নোয়"),
            ("search 2", "নইয়্"),
            ("English voice", "EN:nine"),
        ],
    ),
    "six": (
        "আট",
        "সাত",
        [
            ("today", "ছয়"),
            ("diphthong", "ছৈ"),
            ("search 1", "ছএ"),
            ("search 2", "ছঅঅ"),
            ("search 3", "ছো"),
            ("English voice", "EN:six"),
        ],
    ),
    "hoy": (
        "এটা",
        "না",
        [
            ("today", "হয়"),
            ("diphthong", "হৈ"),
            ("search 1", "হঅই"),
            ("search 2", "হোএ"),
            ("search 3", "হএ"),
            ("search 4", "হই"),
        ],
    ),
    "somoye": (
        "ওই",
        "আসুন",
        [
            ("today", "শময়ে"),
            ("search 1", "শময়এ"),
            ("search 2", "শময়্এ"),
            ("diphthong", "শমৈ"),
            ("search 3", "শমইয়ে"),
            ("search 4", "শমইএ"),
        ],
    ),
}
PHONE = [
    ("today", "bn", ["নয়", "আট", "সাত", "ছয়", "পাঁচ", "চার", "তিন", "দুই", "এক", "শূন্য"]),
    (
        "only 6 and 9 by the English voice",
        "mix",
        ["EN:nine", "আট", "সাত", "EN:six", "পাঁচ", "চার", "তিন", "দুই", "এক", "শূন্য"],
    ),
    (
        "every digit by the English voice",
        "en",
        ["EN:nine", "EN:eight", "EN:seven", "EN:six", "EN:five", "EN:four", "EN:three", "EN:two", "EN:one", "EN:zero"],
    ),
    (
        "English digit words in Bengali letters",
        "bn",
        ["নাইন", "এইট", "সেভেন", "সিক্স", "ফাইভ", "ফোর", "থ্রি", "টু", "ওয়ান", "জিরো"],
    ),
    (
        "Bengali digits, 6 and 9 as English words in Bengali letters",
        "bn",
        ["নাইন", "আট", "সাত", "সিক্স", "পাঁচ", "চার", "তিন", "দুই", "এক", "শূন্য"],
    ),
]


def synth(text: str, lang: str = "bn") -> tuple[np.ndarray, int]:
    """One word through the voice. The voice fails outright on a very short text ("টু"): it is asked again with a danda / full stop after it, as tts_server does."""
    last: Exception | None = None
    for attempt in (text, text + ("।" if lang == "bn" else ".")):
        req = urllib.request.Request(
            TTS,
            data=json.dumps({"text": attempt, "lang": lang, "pauses": False}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with wave.open(io.BytesIO(urllib.request.urlopen(req, timeout=60).read())) as w:
                return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(
                    np.float32
                ) / 32768, w.getframerate()
        except urllib.error.HTTPError as e:
            last = e
    raise RuntimeError(f"the voice could not say {text!r}") from last


def rms(a: np.ndarray) -> float:
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def piece(spec: str, reference: float) -> tuple[np.ndarray, int]:
    """One word as audio: "EN:nine" is the English voice, matched in loudness to the Bengali voice around it; anything else is the Bengali voice."""
    if spec.startswith("EN:"):
        wav, sr = synth(spec[3:], "en")
        r = rms(wav)
        return (np.clip(wav * min(max(reference / r, 0.25), 4.0), -1, 1) if r > 0 and reference > 0 else wav), sr
    return synth(spec, "bn")


def join(parts: list[np.ndarray], sr: int) -> np.ndarray:
    gap = np.zeros(int(GAP * sr), dtype=np.float32)
    out: list[np.ndarray] = []
    for p in parts:
        out += [p, gap]
    return np.concatenate(out)


def trim(a: np.ndarray, thr: float = 0.01) -> np.ndarray:
    loud = np.where(np.abs(a) > thr)[0]
    return a[loud[0] : loud[-1] + 1] if loud.size else a


def write(path: str, audio: np.ndarray, sr: int) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    sheet = [
        "# য়: second listening sheet",
        "",
        "For each file: the best number, or `none`. Candidate 1 is what the bot says today.",
        "",
    ]
    long_gap_s = 0.9
    for key, (left, right, cands) in WORDS.items():
        l_wav, sr = synth(left)
        r_wav, _ = synth(right)
        reference = rms(np.concatenate([l_wav, r_wav]))
        pieces: list[np.ndarray] = []
        for n, (_label, spec) in enumerate(cands):
            num, _ = synth(NUMBERS[n])
            cand, csr = piece(spec, reference)
            if csr != sr:  # the English voice runs at the same rate here; resample plainly if it ever does not
                cand = np.interp(
                    np.linspace(0, len(cand) - 1, int(len(cand) * sr / csr)), np.arange(len(cand)), cand
                ).astype(np.float32)
            phrase = join([trim(l_wav), trim(cand), trim(r_wav)], sr)
            pieces += [
                num,
                np.zeros(int(0.35 * sr), dtype=np.float32),
                phrase,
                np.zeros(int(0.3 * sr), dtype=np.float32),
                phrase,
                np.zeros(int(long_gap_s * sr), dtype=np.float32),
            ]
        write(f"{OUT}/{key}.wav", np.concatenate(pieces), sr)
        sheet.append(
            f"- `{key}.wav` {left} _ {right}: "
            + " | ".join(f"{n + 1}: {sp} ({lab})" for n, (lab, sp) in enumerate(cands))
            + "  -> best: ___"
        )
    reference = rms(synth("আট সাত পাঁচ")[0])
    pieces = []
    for n, (label, _mode, words) in enumerate(PHONE):
        num, sr = synth(NUMBERS[n])
        audio = join([trim(piece(w, reference)[0]) for w in words], sr)
        pieces += [
            num,
            np.zeros(int(0.35 * sr), dtype=np.float32),
            audio,
            np.zeros(int(long_gap_s * sr), dtype=np.float32),
        ]
    write(f"{OUT}/phone.wav", np.concatenate(pieces), sr)
    sheet.append(
        "- `phone.wav` a whole number (9 8 7 6 5 4 3 2 1 0): "
        + " | ".join(f"{n + 1}: {lab}" for n, (lab, _m, _w) in enumerate(PHONE))
        + "  -> best: ___"
    )
    with open(f"{OUT}/answer_sheet.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(sheet))
    print(f"wrote {len(WORDS) + 1} files and answer_sheet.md to {OUT}")


if __name__ == "__main__":
    main()
