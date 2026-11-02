"""Which doctors of the clinic's own list does a spoken name stand for? (owner, 2026-11-03)

Why: "ডাক্তার শায়ক" (nobody of that name) was answered "নির্মল রায় নাকি পার্থ রায়?": the clinic lookup scores alike every doctor whose name ends the same way and calls that "ambiguous", and the agent read the guess
out. A name said differently from how it is written ("রয়" for "রায়", "দত্ত" for "দত্ত", ন for ণ) must still be found, so the match is by SOUND, but never by a loose likeness. Two levels, in this order:

  A. SAME SOUND  the two names have the same phonetic key (vowel length, the inherent vowel, য়-spelling, ন/ণ, শ/ষ/স, aspirated / unaspirated and dental / retroflex pairs, doubled letters are all
                 forgotten). That is one name spelt two ways.
  B. CLOSE SOUND the keys differ by at most a third (weighted edit distance: look-alike sounds cost little, any other letter costs a whole one), the FIRST sound is the same (a caller changes vowels, not
                 the opening consonant), and the key is at least three sounds long. Only ever the subject of a QUESTION to the caller ("আপনি কি … বলতে চাইছেন?"), never an answer.

Only doctors of the clinic's list are candidates, so nothing outside it is ever offered. A name that reaches neither level is nobody's. Pure functions, no I/O.
"""

from __future__ import annotations

import re
import unicodedata

from agent import name_script

SAME, CLOSE = "same", "close"
CLOSE_MAX = 0.34  # of the longer key
MIN_CLOSE_LEN = 3

_BN_MERGE = str.maketrans(
    {
        "ণ": "ন", "শ": "স", "ষ": "স", "ৎ": "ত", "ঞ": "ন", "ঙ": "ন",
        "খ": "ক", "ঘ": "গ", "ছ": "চ", "ঝ": "জ",
        "ঠ": "ত", "ট": "ত", "থ": "ত", "ঢ": "দ", "ড": "দ", "ধ": "দ",
        "ফ": "প", "ভ": "ব",
    }
)  # fmt: skip
_LOOKALIKE = [frozenset(p) for p in ("কগ", "চজ", "তদ", "পব", "মন", "রল", "সজ", "কচ", "কত")]
_LATIN_DIGRAPH = (("sh", "s"), ("ch", "c"), ("th", "t"), ("dh", "d"), ("kh", "k"), ("gh", "g"), ("bh", "b"), ("ph", "p"), ("jh", "j"))
_LATIN_ONE = str.maketrans({"z": "j", "w": "b", "v": "b", "q": "k", "c": "k", "x": "k", "e": "", "a": "", "i": "", "o": "", "u": "", "y": "", "h": ""})
_TITLES = name_script._TITLES  # noqa: SLF001


def _collapse(s: str) -> str:
    return re.sub(r"(.)\1+", r"\1", s)


def key(word: str) -> str:
    """The phonetic key of one name word (Bengali, Devanagari or Latin letters)."""
    w = unicodedata.normalize("NFC", word or "").lower().strip(".,?!।")
    if not w:
        return ""
    if w.isascii():
        for a, b in _LATIN_DIGRAPH:
            w = w.replace(a, b)
        return _collapse(re.sub(r"[^a-z]", "", w.translate(_LATIN_ONE)))
    w = unicodedata.normalize("NFC", name_script._deva_to_bn(w))  # noqa: SLF001
    w = "".join(c for c in w if "ক" <= c <= "হ" or c == "ৎ")
    return _collapse(w.translate(_BN_MERGE))


def _cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    return 0.4 if any(a in p and b in p for p in _LOOKALIKE) else 1.0


def distance(a: str, b: str) -> float:
    """Weighted edit distance of two keys; a missing য costs half (রায় / রা)."""
    prev = [0.0]
    for ch in a:
        prev.append(prev[-1] + (0.5 if ch == "য" else 1.0))
    for cb in b:
        cur = [prev[0] + (0.5 if cb == "য" else 1.0)]
        for i, ca in enumerate(a):
            cur.append(min(prev[i + 1] + (0.5 if cb == "য" else 1.0), cur[i] + (0.5 if ca == "য" else 1.0), prev[i] + _cost(ca, cb)))
        prev = cur
    return prev[-1]


def word_level(said: str, own: str) -> str | None:
    """SAME, CLOSE or None for one spoken word against one word of a doctor's name."""
    if said.isascii() != own.isascii():
        return None
    ks, ko = key(said), key(own)
    if not ks or not ko:
        return None
    if ks == ko:
        return SAME if len(ks) >= 2 or said.lower() == own.lower() else None
    if len(ks) < MIN_CLOSE_LEN or len(ko) < MIN_CLOSE_LEN or ks[0] != ko[0]:
        return None
    return CLOSE if distance(ks, ko) / max(len(ks), len(ko)) <= CLOSE_MAX else None


def _words(text: str) -> list[str]:
    titles = {name_script.bare(t) for t in _TITLES}
    out = []
    for t in (text or "").replace(".", " ").split():
        t = t.strip(".,?!।")
        if t and name_script.bare(t) not in titles:
            out.append(t)
    return out


def _own_words(info: dict) -> list[str]:
    words: list[str] = []
    for k in ("full_name_bn", "full_name_hi", "full_name", "name"):
        words += [w for w in _words(info.get(k) or "") if len(w) > 1]
    for k in ("aliases_bn", "aliases_hi", "aliases_en"):  # the spellings the clinic lists for him (মুখোপাধ্যায় for Mukherjee)
        for alias in info.get(k) or []:
            words += [w for w in _words(str(alias)) if len(w) > 1]
    return words


def level(said: str, info: dict) -> str | None:
    """SAME when every word said is the same sound as a different word of this doctor's name, CLOSE when each is at least close, None otherwise."""
    heard = [w for w in _words(said) if len(key(w)) >= 1]
    own = _own_words(info)
    if not heard or not own:
        return None
    used: set[int] = set()
    worst = SAME
    for w in heard:
        best, best_i = None, -1
        for i, o in enumerate(own):
            if i in used:
                continue
            lv = word_level(w, o)
            if lv == SAME or (lv == CLOSE and best is None):
                best, best_i = lv, i
                if lv == SAME:
                    break
        if best is None:
            return None
        used.add(best_i)
        if best == CLOSE:
            worst = CLOSE
    return worst


def candidates(said: str, infos: list[dict]) -> list[dict]:
    """The doctors this name stands for: those with the same sound; when there are none, those with a close sound. Empty when it is nobody's."""
    seen, uniq = set(), []
    for i in infos:
        if id(i) not in seen:
            seen.add(id(i))
            uniq.append(i)
    graded = [(level(said, i), i) for i in uniq]
    same = [i for lv, i in graded if lv == SAME]
    return same or [i for lv, i in graded if lv == CLOSE]
