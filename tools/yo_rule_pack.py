"""Listening pack for ONE rule for every য় (agent/bn_glide_rules.py), on the words the voice says worst: নয় / ছয় ("noyo", "chhoyo"), সময়ে ("somoyoje") and the same shapes in other words.

    python tools/yo_rule_pack.py --list        the words and the three spellings (no audio)
    python tools/yo_rule_pack.py               (on the pod) one numbered audio file per word -> /tmp/yo_pack/, plus answer_sheet.md

Candidate 1 = what the bot says today. 2 = rule set A: the y-glide is written as a vowel (নয় -> নই, সময়ে -> সমইয়ে, মাথায় -> মাথাই, নিয়ে -> নিইয়ে, দেওয়া -> দেওআ).
3 = rule set B: the vowel is written out in full (নয় -> নোই, সময়ে -> সময়এ). The listener picks A, B or neither for each word; if one set wins on most words it becomes BN_GLIDE_RULES for every word.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glide_rules_pack as pack  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import bn_glide_rules, bn_respell  # noqa: E402

OUT = os.environ.get("YO_PACK_DIR", "/tmp/yo_pack")
SETS = {
    "A (glide written as a vowel)": {
        "coda": "i",
        "before_vowel": "iy",
        "after_i": "iiy",
        "after_aa_o": "i",
        "owa": "oa",
    },
    "B (vowel written out)": {"coda": "oi", "before_vowel": "sep", "after_i": "iiy", "after_aa_o": "i", "owa": "oa"},
}
# the words the listener named first, then one or two of every shape
WORDS = [
    "নয়",
    "ছয়",
    "সময়ে",
    "সময়",
    "হয়",
    "ভয়",
    "বয়স",
    "কয়েক",
    "হয়েছে",
    "দয়া",
    "দিয়ে",
    "নিয়ে",
    "মাথায়",
    "যায়",
    "কোথায়",
    "মেয়ে",
    "পেয়েছি",
    "দেওয়া",
]
PHRASES = {"নয়": "নয় ছয় নয় ছয়", "ছয়": "ছয় নয় ছয় নয়"}  # a digit is judged in a phone number as well as alone


def spell(word: str, label: str | None) -> str:
    """The word as the bot sends it today (label None) or with one of the rule sets applied to it."""
    today = bn_respell.respell(word)
    return today if label is None else bn_glide_rules.rewrite(today, SETS[label], force=True)


def spellings(word: str) -> list[tuple[str | None, str]]:
    """[(rule set or None, spelling)]: today's first, then each rule set whose result is new."""
    rows: list[tuple[str | None, str]] = [(None, spell(word, None))]
    for label in SETS:
        out = spell(word, label)
        if out not in [sp for _l, sp in rows]:
            rows.append((label, out))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if os.environ.get("BN_GLIDE_RULES"):
        sys.exit("unset BN_GLIDE_RULES first: the pack compares today's spelling with each rule set")
    sheet = [
        "# One rule for every য়: listening sheet",
        "",
        "For each file: the best number, or `none`. Candidate 1 is what the bot says today.",
        "",
    ]
    for i, word in enumerate(WORDS, 1):
        rows = spellings(word)
        sheet.append(
            f"- `yo_{i}.wav` {word}: "
            + " | ".join(f"{n + 1}: {sp}" for n, (_l, sp) in enumerate(rows))
            + "  -> best: ___"
        )
        sheet.append("  - " + ", ".join(f"{n + 1} = {lab or 'as sent today'}" for n, (lab, _sp) in enumerate(rows)))
        if args.list:
            print(f"{word}: " + " | ".join(f"{(lab or 'today').split()[0]} {sp}" for lab, sp in rows))
    if args.list:
        return
    import wave

    import numpy as np

    os.makedirs(OUT, exist_ok=True)
    for i, word in enumerate(WORDS, 1):
        pieces, rate = [], 22050
        for n, (label, _sp) in enumerate(spellings(word)):
            number, rate = pack.synth(pack.NUMBERS[n])
            clip, _ = pack.synth(" ".join(spell(w, label) for w in PHRASES.get(word, word).split()))
            gap, long_gap = np.zeros(int(rate * 0.35), dtype=np.int16), np.zeros(int(rate * 0.9), dtype=np.int16)
            pieces += [number, gap, clip, gap, clip, long_gap]
        with wave.open(f"{OUT}/yo_{i}.wav", "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(np.concatenate(pieces).tobytes())
    with open(f"{OUT}/answer_sheet.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(sheet))
    print(f"wrote {len(WORDS)} files and answer_sheet.md to {OUT}")


if __name__ == "__main__":
    main()
