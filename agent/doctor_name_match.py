"""Which doctors of the clinic's own list does a spoken name stand for? (owner, 2026-11-03)

Why: "ডাক্তার শায়ক" (nobody of that name) was answered "নির্মল রায় নাকি পার্থ রায়?": the clinic lookup scores alike every doctor whose name ends the same way and calls that "ambiguous", and the agent read the guess
out. A name said differently from how it is written ("রয়" for "রায়", ন for ণ) must still be found, so the match is by SOUND -- but exact spelling always comes first. Four levels, tried in this order, and the
first level that has any doctor is the whole answer (a looser level is never added to a stricter one):

  EXACT    every word said is spelt exactly as a word of the doctor's name ("অমিত" is Dr. Amit Kar; "রায়" is both Roy and Ray). Nothing else is offered beside it.
  SAME     the same phonetic key (vowel length, the inherent vowel, য়-spelling, ন/ণ, শ/ষ/স, aspirated / unaspirated and dental / retroflex pairs, doubled letters are forgotten) AND spelt alike (a spelling ratio
           of 0.7 or more). "রয়" for "রায়". Two names that only share their consonants ("অমিত" / "মৌমিতা", both ম-ত) are NOT the same.
  CLOSE    the keys differ by at most a third (weighted edit distance), the FIRST sound is the same, and the key is at least three sounds long.
  PARTIAL  the word said is the beginning or the end of a longer name word of a doctor ("গুপ্তা" is the end of "সেনগুপ্ত" and "দাশগুপ্ত"). Only ever a QUESTION to the caller ("which one?"), never an answer.

Only doctors of the clinic's list are candidates, so nothing outside it is ever offered. A name that reaches no level is nobody's. Pure functions, no I/O.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

from agent import name_script

EXACT, SAME, CLOSE, PARTIAL = "exact", "same", "close", "partial"
_ORDER = {EXACT: 0, SAME: 1, CLOSE: 2, PARTIAL: 3}
CLOSE_MAX = 0.34  # of the longer key
MIN_CLOSE_LEN = 3
MIN_PARTIAL_LEN = 3
SPELL_MIN = 0.7  # a same-sound match must also be spelt alike

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


def plain(word: str) -> str:
    """The word as written, without case, punctuation or the nukta, Devanagari turned into Bengali letters: what 'spelt exactly' compares."""
    w = unicodedata.normalize("NFC", word or "").lower().strip(".,?!।")
    return name_script._deva_to_bn(w).replace("়", "")  # noqa: SLF001


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
    """EXACT, SAME, CLOSE or None for one spoken word against one word of a doctor's name."""
    if said.isascii() != own.isascii():
        return None
    ps, po = plain(said), plain(own)
    if not ps or not po:
        return None
    if ps == po:
        return EXACT if len(ps) >= 2 else None
    ks, ko = key(said), key(own)
    if not ks or not ko:
        return None
    if ks == ko:
        # the same consonants are not enough ("অমিত" / "মৌমিতা"): the words must also be spelt alike
        return SAME if len(ks) >= 2 and difflib.SequenceMatcher(None, ps, po).ratio() >= SPELL_MIN else None
    if len(ks) < MIN_CLOSE_LEN or len(ko) < MIN_CLOSE_LEN or ks[0] != ko[0]:
        return None
    return CLOSE if distance(ks, ko) / max(len(ks), len(ko)) <= CLOSE_MAX else None


def is_partial(said: str, own: str) -> bool:
    """The word said is the beginning or the end of a longer name word ("গুপ্তা" ... "সেনগুপ্ত"). Compared by sound, never shorter than three sounds."""
    if said.isascii() != own.isascii():
        return False
    ks, ko = key(said), key(own)
    return len(ks) >= MIN_PARTIAL_LEN and len(ko) > len(ks) and (ko.endswith(ks) or ko.startswith(ks))


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
    """The level at which this doctor matches what was said: the loosest level any word needed (EXACT only when every word is spelt exactly), or None."""
    heard = [w for w in _words(said) if len(key(w)) >= 1]
    own = _own_words(info)
    if not heard or not own:
        return None
    used: set[int] = set()
    worst = EXACT
    for w in heard:
        best, best_i = None, -1
        for i, o in enumerate(own):
            if i in used:
                continue
            lv = word_level(w, o) or (PARTIAL if is_partial(w, o) else None)
            if lv is None:
                continue
            if best is None or _ORDER[lv] < _ORDER[best]:
                best, best_i = lv, i
                if lv == EXACT:
                    break
        if best is None:
            return None
        used.add(best_i)
        if _ORDER[best] > _ORDER[worst]:
            worst = best
    return worst


def candidates_with_level(said: str, infos: list[dict]) -> tuple[list[dict], str | None]:
    """(the doctors this name stands for, the level they matched at). The strictest level that has any doctor is the whole answer; ([], None) when the name is nobody's."""
    seen, uniq = set(), []
    for i in infos:
        if id(i) not in seen:
            seen.add(id(i))
            uniq.append(i)
    graded = [(level(said, i), i) for i in uniq]
    for lv in (EXACT, SAME, CLOSE, PARTIAL):
        hit = [i for g, i in graded if g == lv]
        if hit:
            return hit, lv
    return [], None


def candidates(said: str, infos: list[dict]) -> list[dict]:
    return candidates_with_level(said, infos)[0]
