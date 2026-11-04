"""Listening pack for English-origin words the bot speaks in Bengali (পেমেন্ট, অনলাইন, রিপোর্ট ...), the same method as tools/respell_listening_pack.py: the voice says each candidate spelling, numbered, and a native
listener picks the best. A winner goes into agent/bn_respell.py's _RESPELL table (and REVIEWED); the listener's ear decides, not a machine score.

    python tools/loanword_pack.py --list     the words and candidate spellings (no audio)
    python tools/loanword_pack.py            (on the pod) one numbered audio file per word -> /tmp/loan_pack/, plus answer_sheet.md

Candidate 1 is always what the bot sends today. The others are hypotheses built from what listeners have chosen before: a word split in two (ওয়াটস অ্যাপ, ডায়া বেটিস), a closing consonant held with a hasanta
(গুগল্, আট্), a vowel changed (অমীত, তীন). The words are the English-origin ones the bot says most (its own replies and the pod's call logs).
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glide_rules_pack as pack  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import bn_respell, whatsapp_tts  # noqa: E402

OUT = os.environ.get("LOAN_PACK_DIR", "/tmp/loan_pack")

# word as the bot writes it -> the other spellings to hear (today's spelling is added first)
CANDIDATES: dict[str, list[str]] = {
    "পেমেন্ট": ["পে মেন্ট", "পেইমেন্ট", "পেমেন্ট্", "পেমেণ্ট"],
    "অনলাইন": ["অন লাইন", "অনলাইন্", "অনলাইণ"],
    "লিংক": ["লিঙ্ক", "লিঙ্ক্", "লিংক্"],
    "কনফার্মেশন": ["কন ফার্মেশন", "কনফারমেশন", "কনফার্মেশান", "কনফার্মেশণ"],
    "রিপোর্ট": ["রিপোট", "রিপোর্ট্", "রি পোর্ট"],
    "টেস্ট": ["টেষ্ট", "টেস্ট্", "টেসট"],
    "রেট": ["রেট্", "রেইট"],
    "সিরিয়াল": ["সিরিআল", "সিরিয়াল্", "সিরীয়াল"],
    "মেডিসিন": ["মেডিশিন", "মেডিসিন্", "মেডি সিন", "মেডিসীন"],
    "জেনারেল": ["জেনেরাল", "জেনারেল্", "জেনা রেল"],
    "অর্থোপেডিক্স": ["অর্থো পেডিক্স", "অর্থোপিডিক্স", "অর্থোপেডিক্স্", "অর্থপেডিক্স"],
    "কার্ডিওলজি": ["কার্ডিও লজি", "কারডিওলজি", "কার্ডিওলোজি"],
    "সোনোস্ক্যান": ["সোনো স্ক্যান", "সোনোস্কান", "সোনোস্ক্যান্", "সোনস্ক্যান"],
    "ডাঃ": ["ডাক্তার", "ডক্টর"],
    "চেকআপ": ["চেক আপ", "চেকাপ", "চেকআপ্"],
    "ফাস্টিং": ["ফাস্ টিং", "ফাস্টিঙ", "ফাষ্টিং"],
    "প্রেসক্রিপশন": ["প্রেস ক্রিপশন", "প্রেসক্রিপশান", "প্রেসক্রিপ্শন"],
    "মোবাইল": ["মোবাইল্", "মোবাইল"],
    "ক্যাশ": ["ক্যাশ্", "ক্যাস"],
    "কল": ["কল্", "কোল"],
    # Today the bot sends this through the English voice's recording (agent/whatsapp_tts.py cuts a recording of the English voice saying "WhatsApp" into the Bengali audio). The other candidates are Bengali-voice
    # spellings written so the recording is NOT used (each is checked below), so the listener can compare the recording with the Bengali voice itself.
    "হোয়াটসঅ্যাপ": ["ওয়াৎস অ্যাপ", "হোয়াট স অ্যাপ", "ওয়াটস্ অ্যাপ", "ওয়াৎসঅ্যাপ", "হোয়ট্স অ্যাপ"],
}

# a word that is judged in a sentence, not alone: the splice of the recording only happens inside a sentence, and the word's neighbours change how it sounds
FRAMES: dict[str, str] = {"হোয়াটসঅ্যাপ": "এই নম্বরে কি {} আছে?"}


def text_for(word: str, spelling: str) -> str:
    return FRAMES[word].format(spelling) if word in FRAMES else spelling


def uses_recording(word: str, spelling: str) -> bool:
    """True when the TTS server would play the English recording for this spelling instead of the Bengali voice."""
    return any(kind == "wa" for kind, _ in whatsapp_tts.split(text_for(word, spelling), "bn"))


def rows(word: str) -> list[tuple[str, str]]:
    today = bn_respell.respell(word)
    out = [("as sent today", today)]
    for sp in CANDIDATES[word]:
        if sp != today:
            out.append(("candidate", sp))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="print the words and spellings; make no audio")
    args = ap.parse_args()
    sheet = [
        "# English-origin words: listening sheet",
        "",
        "For each file: the best number, or `none`. Candidate 1 is what the bot says today.",
        "",
    ]
    for i, word in enumerate(CANDIDATES, 1):
        r = rows(word)
        sheet.append(
            f"- `loan_{i}.wav` {word}: "
            + " | ".join(f"{n + 1}: {sp}" for n, (_l, sp) in enumerate(r))
            + "  -> best: ___"
        )
        if args.list:
            print(f"{word}: " + " | ".join(sp for _l, sp in r))
    if args.list:
        return
    import wave

    import numpy as np

    os.makedirs(OUT, exist_ok=True)
    for i, word in enumerate(CANDIDATES, 1):
        pieces = []
        for n, (_lab, sp) in enumerate(rows(word)):
            number, rate = pack.synth(pack.NUMBERS[n])
            clip, _ = pack.synth(text_for(word, sp))
            gap, long_gap = np.zeros(int(rate * 0.35), dtype=np.int16), np.zeros(int(rate * 0.9), dtype=np.int16)
            pieces += [number, gap, clip, gap, clip, long_gap]
        with wave.open(f"{OUT}/loan_{i}.wav", "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(np.concatenate(pieces).tobytes())
    with open(f"{OUT}/answer_sheet.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(sheet))
    print(f"wrote {len(CANDIDATES)} files and answer_sheet.md to {OUT}")


if __name__ == "__main__":
    main()
