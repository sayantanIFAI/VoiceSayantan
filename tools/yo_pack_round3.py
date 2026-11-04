"""Third য় pack: the rule writes the glide as the vowel এ (নয় -> নএ) and a listener hears "ne", not "no-e": a consonant followed directly by an independent vowel letter loses its own vowel in the voice. So this pack
puts the vowel back, in the few ways it can be written, for nine, six, hoy and somoye in their frames (the same frames as tools/yo_pack_round2.py), with the length of each rendering (a one-syllable "ne" is short).

    python tools/yo_pack_round3.py        (on the pod) -> /tmp/yo3_pack/*.wav and answer_sheet.md

Candidate 1 is what the bot says today (the glide written as এ). The others write the vowel after the consonant: অ (the open "o" of নয়), ো (the closed "o"), া (an "a"), or the diphthong ৈ.
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yo_pack_round2 as base  # noqa: E402

OUT = os.environ.get("YO3_PACK_DIR", "/tmp/yo3_pack")
WORDS = {
    "nine": ("সাত", "আট", ["নএ", "নঅএ", "নোএ", "নাএ", "নৈ", "নঅই"]),
    "six": ("আট", "সাত", ["ছএ", "ছঅএ", "ছোএ", "ছাএ", "ছৈ", "ছঅই"]),
    "hoy": ("এটা", "না", ["হএ", "হঅএ", "হোএ", "হাএ", "হৈ", "হঅই"]),
    "somoye": ("ওই", "আসুন", ["শমএ", "শমঅএ", "শমোএ", "শমাএ", "শমৈ", "শমঅই"]),
}


def seconds(wav: np.ndarray, sr: int) -> float:
    return round(len(base.trim(wav)) / sr, 2)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    sheet = [
        "# য়: third listening sheet (the vowel put back)",
        "",
        "For each file: the best number, or `none`. Candidate 1 is what the bot says today. The length of each word is in brackets.",
        "",
    ]
    for key, (left, right, cands) in WORDS.items():
        l_wav, sr = base.synth(left)
        r_wav, _ = base.synth(right)
        pieces, lengths = [], []
        for n, spec in enumerate(cands):
            num, _ = base.synth(base.NUMBERS[n])
            cand, _ = base.synth(spec)
            lengths.append(seconds(cand, sr))
            phrase = base.join([base.trim(l_wav), base.trim(cand), base.trim(r_wav)], sr)
            pieces += [
                num,
                np.zeros(int(0.35 * sr), dtype=np.float32),
                phrase,
                np.zeros(int(0.3 * sr), dtype=np.float32),
                phrase,
                np.zeros(int(0.9 * sr), dtype=np.float32),
            ]
        base.write(f"{OUT}/{key}.wav", np.concatenate(pieces), sr)
        sheet.append(
            f"- `{key}.wav` {left} _ {right}: "
            + " | ".join(f"{n + 1}: {sp} ({lengths[n]} s)" for n, sp in enumerate(cands))
            + "  -> best: ___"
        )
    with open(f"{OUT}/answer_sheet.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(sheet))
    print(f"wrote {len(WORDS)} files and answer_sheet.md to {OUT}")


if __name__ == "__main__":
    main()
