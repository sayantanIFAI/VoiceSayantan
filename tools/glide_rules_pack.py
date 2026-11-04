"""Listening pack for the y-glide / flap shape rules (agent/bn_glide_rules.py). The rules are only hypotheses until a native listener has heard each class on MANY words.

    python tools/glide_rules_pack.py --list            the words of each class found in the bot's own text, and what each variant makes of them (no audio)
    python tools/glide_rules_pack.py                   (on the pod) one numbered audio file per word -> /tmp/glide_pack/, plus answer_sheet.md

In each file the voice says candidate 1 = the word as the bot sends it today, then candidate 2, 3 ... = each variant of that class, every one twice. The listener marks, per word, the best number
(or "none"). A class is turned on only when ONE variant wins on most of its words; then set BN_GLIDE_RULES="<class>=<variant>" (deploy/env.sh). The listener's ear decides, not a machine score.
"""

from __future__ import annotations

import argparse
import collections
import glob
import io
import json
import os
import re
import sys
import unicodedata
import urllib.request
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import bn_glide_rules, bn_respell  # noqa: E402

TTS = os.environ.get("TTS_URL", "http://localhost:8002/synthesize")
OUT = os.environ.get("GLIDE_PACK_DIR", "/tmp/glide_pack")
WORDS_PER_CLASS = int(os.environ.get("GLIDE_WORDS_PER_CLASS", "8"))
NUMBERS = ["এক", "দুই", "তিন", "চার", "পাঁচ", "ছয়"]
_WORD = re.compile(r"[ঀ-৿]+")
_SKIP_FILES = {"bn_respell.py", "bn_glide_rules.py"}


def vocabulary() -> collections.Counter:
    """Every Bengali word in the bot's own text (the same sources the respeller's audit uses), counted."""
    root = os.environ.get("GLIDE_VOCAB_ROOT") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )  # a checkout whose text to read (the pack can run from a scratch copy of this tool)
    counts: collections.Counter = collections.Counter()
    for path in glob.glob(f"{root}/agent/*.py") + glob.glob(f"{root}/clinic-api/*.py"):
        if os.path.basename(path) in _SKIP_FILES:
            continue
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for w in _WORD.findall(fh.read()):
                counts[unicodedata.normalize("NFC", w)] += 1
    return counts


def candidates_by_class(counts: collections.Counter) -> dict[str, list[str]]:
    """{class: the most frequent words of that class that no listener has decided yet}."""
    decided = set(bn_respell.table())
    out: dict[str, list[str]] = {c: [] for c in bn_glide_rules.classes()}
    for word, _n in counts.most_common():
        if word in decided or (bn_respell.respell(word) != word and word not in bn_respell._NATIVE_SH):  # noqa: SLF001
            continue
        for cls in bn_glide_rules.classify(word):
            if len(out[cls]) < WORDS_PER_CLASS:
                out[cls].append(word)
    return out


def spellings(word: str, cls: str) -> list[tuple[str, str]]:
    """[(label, spelling sent to the voice)]: today's spelling first, then each variant of `cls` on its own."""
    today = bn_respell.respell(word)
    rows = [("as sent today", today)]
    for name, fn in bn_glide_rules.VARIANTS[cls].items():
        rows.append((name, fn(today)))
    return rows


def synth(text: str):
    import numpy as np

    req = urllib.request.Request(
        TTS,
        data=json.dumps({"text": text, "lang": "bn", "pauses": False}).encode(),
        headers={"Content-Type": "application/json"},
    )
    raw = urllib.request.urlopen(req, timeout=60).read()
    with wave.open(io.BytesIO(raw)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16), w.getframerate()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="print the classes, words and spellings; make no audio")
    args = ap.parse_args()
    if os.environ.get("BN_GLIDE_RULES"):
        sys.exit(
            "unset BN_GLIDE_RULES first: the pack compares today's spelling with each variant, so no rule may be on"
        )
    by_class = candidates_by_class(vocabulary())
    sheet = [
        "# Glide-rule listening sheet",
        "",
        "For each file: the best number, or `none`. Candidate 1 is what the bot says today.",
        "",
    ]
    for cls, words in by_class.items():
        sheet += [f"## {cls}", ""]
        for word in words:
            rows = spellings(word, cls)
            line = (
                f"- `{cls}_{words.index(word) + 1}.wav` {word}: "
                + " | ".join(f"{i + 1} {lab}: {sp}" for i, (lab, sp) in enumerate(rows))
                + "  -> best: ___"
            )
            sheet.append(line)
            if args.list:
                print(f"{cls:13s} {word}: " + " | ".join(f"{lab}: {sp}" for lab, sp in rows))
        sheet.append("")
    if args.list:
        return
    import numpy as np

    os.makedirs(OUT, exist_ok=True)
    for cls, words in by_class.items():
        for i, word in enumerate(words, 1):
            pieces = []
            for n, (_lab, sp) in enumerate(spellings(word, cls)):
                number, rate = synth(NUMBERS[n])
                clip, _ = synth(sp)
                gap, long_gap = np.zeros(int(rate * 0.35), dtype=np.int16), np.zeros(int(rate * 0.9), dtype=np.int16)
                pieces += [number, gap, clip, gap, clip, long_gap]
            with wave.open(f"{OUT}/{cls}_{i}.wav", "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(np.concatenate(pieces).tobytes())
    with open(f"{OUT}/answer_sheet.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(sheet))
    print(f"wrote {sum(len(w) for w in by_class.values())} files and answer_sheet.md to {OUT}")


if __name__ == "__main__":
    main()
