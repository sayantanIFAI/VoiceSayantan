"""Shape rules for the words the Bengali voice says badly because of their য় (y-glide) and ড়/ঢ় (flap): one rule per CLASS of word, not one table entry per word.

The Bengali voice is a character-level FastPitch (no pronunciation layer), so the only lever is the spelling it is sent (agent/bn_respell.py). About forty words have been fixed one at a time by native
listeners; the same few shapes keep coming back (সময়টা, কয়েক, নিয়ে, নেওয়া, সাড়া). A rule here rewrites every word of a shape at once, so a new word needs no new listener round.

NOTHING IS ON BY DEFAULT. Each class has candidate rewrites (VARIANTS) taken from what listeners chose word by word, but a class is only a hypothesis until a native listener has heard it on MANY
words of that class (tools/glide_rules_pack.py builds the numbered audio). Turn a class on in /workspace/glide_rules.json ({"coda": "e"}; read again whenever it changes) or with BN_GLIDE_RULES, e.g. "coda=oi,owa=oa,ra=nasal";
neither set = this module changes nothing. Owner, 2026-11-04: the glide is written as the independent vowel এ ("e" in coda, before_vowel and after_aa_o: নয়->নএ, ছয়->ছএ, সময়ে->শমএ, মাথায়->মাথাএ). Words a
listener already decided (the explicit table in bn_respell, and the "leave alone" list below: some number words, loanwords, গিয়ে) are never touched.

The classes are decided from the NFC spelling, where য় is য + nukta (the voice reads both Unicode forms the same; measured on the pod, 2026-11-04).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections.abc import Callable

_Y = "য়"  # য়, decomposed: the form unicodedata.normalize("NFC", ...) always yields
_NUKTA = "়"
_VIRAMA = "্"
_CONSONANT = "[ক-হৎ]"  # ক..হ and ৎ; ড/ঢ/য are followed by the nukta when they are ড় / ঢ় / য়, which the patterns below look at explicitly
_SIGN = "[ািীুূেৈোৌ]"
_NOT_FIRST = "(?<=[\u0995-\u09b9\u09be-\u09cc])"  # a ওয়া inside a word (নেওয়া, খাওয়া), not one that starts it (ওয়ার্ড, ওয়াট: loanwords with a different sound)
_VOWEL_NEXT = "[\u0985-\u0994\u09be\u09bf\u09c0\u09c1\u09c2\u09c7\u09c8\u09cb\u09cc]"  # a vowel sign or an independent vowel directly after the য়: it is not at the end of a syllable
_INDEPENDENT = {"া": "আ", "ি": "ই", "ী": "ঈ", "ু": "উ", "ূ": "ঊ", "ে": "এ", "ৈ": "ঐ", "ো": "ও", "ৌ": "ঔ"}

# Whole words never touched: a listener decided them (hয়, গিয়ে and the digits were kept as written), or they are loanwords / number words the rules were not drawn from.
LEAVE_ALONE = frozenset(
    unicodedata.normalize("NFC", w)
    for w in """
    গিয়ে দুয় পঁয়ত্রিশ পঁয়তাল্লিশ চুয়াল্লিশ বিয়াল্লিশ ছিয়ানব্বই ছিয়াশি ছিয়াত্তর ছিয়াত্তর পঁয়ষট্টি সাতচল্লিশ
    থাইরয়েড থাইরোয়েড টাইফয়েড হোয়াটসঅ্যাপ হোয়াটসঅ্যাপে হোয়াট ওয়ান ওয়াই হ্যায় হ্যায় সিরিয়াল ম্যালেরিয়া ক্রিয়েটিনিন ক্যালসিয়াম ফিজিশিয়ান ফিজিসিয়ান পেডিয়াট্রিক্স পিরিয়ড
    জয়েন্ট কেয়ার কেয়া অ্যাপয়েন্টমেন্ট অ্যাপয়েন্টমেন্টটা অ্যাপয়েন্টমেন্টের ডায়াবেটিস ডায়াবিটিস
    """.split()
)

_RULE_ENV = "BN_GLIDE_RULES"


def _glide_vowel(sign: str) -> str:
    """The vowel that follows a glide written as the independent vowel এ: the vowel sign said out in full, except ে, which এ already is (সময়ে -> সমএ, not সমএএ)."""
    return "" if sign == "\u09c7" else _INDEPENDENT[sign]


def _swap(pattern: str, repl: str | Callable) -> Callable[[str], str]:
    rx = re.compile(pattern)
    return lambda w: rx.sub(repl, w)


# class -> the pattern that finds it, and the candidate rewrites (name -> function). The first line of each is what the class IS; the listener hears "as written" first, then each variant.
#  coda          য় at the end of a syllable, after a consonant: হয়-like সময়, বয়স, পয়সা, জয়, রায়-less.   "oi": C+ো+ই (the listener's সময়টা -> শমোইটা)   "i": C+ই
#  before_vowel  য় between a consonant and a vowel sign: কয়েক, দয়া, হয়েছে.                                "sep": the vowel written out (listener's কয়এক)   "iy": ইয় (কইয়েক)
#  after_i       য় after ি / ী: নিয়ে, দিয়ে, পিছিয়ে.                                                        "iiy": an ই before it (the listener's নিইয়ে)
#  after_aa_o    য় after া / ো / ে: যায়, মাথায়, গায়ে, মেয়ে, দেয়.                                                 "i": য়->ই, or an ই before the য় when a vowel sign follows
#  owa           ওয়া: নেওয়া, যাওয়া, পাওয়া, দেওয়া.                                                          "oa": ওআ (the listener's নেওআ)   "waa": ওয়াা (the listener's যাওয়াা)
#  ra            ড়/ঢ় after া: সাড়া, বাড়ি, গাড়ি, ছাড়া.                                                      "nasal": ঁ after the া (the listener's শাঁড়া)   "r": ড়->র
VARIANTS: dict[str, dict[str, Callable[[str], str]]] = {
    "owa": {
        "oa": _swap(_NOT_FIRST + "ও" + _Y + "া", "ওআ"),
        "waa": _swap(_NOT_FIRST + "(ও" + _Y + "া)", r"\1া"),
    },
    "after_i": {
        "iiy": _swap("([িী])" + _Y, r"\1ই" + _Y),
    },
    "after_aa_o": {
        "i": _swap(
            "([াোে])" + _Y + "(" + _SIGN + ")?", lambda m: m.group(1) + "ই" + (_Y + m.group(2) if m.group(2) else "")
        ),
        "e": _swap(
            "([াোে])" + _Y + "(" + _SIGN + ")?",
            lambda m: m.group(1) + "এ" + (_glide_vowel(m.group(2)) if m.group(2) else ""),
        ),
    },
    "before_vowel": {
        "sep": _swap(
            "(" + _CONSONANT + ")" + _Y + "(" + _SIGN + ")", lambda m: m.group(1) + _Y + _INDEPENDENT[m.group(2)]
        ),
        "iy": _swap("(" + _CONSONANT + ")" + _Y + "(?=" + _SIGN + ")", r"\1ই" + _Y),
        "e": _swap(
            "(" + _CONSONANT + ")" + _Y + "(" + _SIGN + ")", lambda m: m.group(1) + "এ" + _glide_vowel(m.group(2))
        ),
    },
    "coda": {
        "oi": _swap("(" + _CONSONANT + ")" + _Y + "(?!" + _VOWEL_NEXT + ")", lambda m: m.group(1) + "ো" + "ই"),
        "i": _swap("(" + _CONSONANT + ")" + _Y + "(?!" + _VOWEL_NEXT + ")", lambda m: m.group(1) + "ই"),
        "e": _swap("(" + _CONSONANT + ")" + _Y + "(?!" + _VOWEL_NEXT + ")", lambda m: m.group(1) + "এ"),
    },
    "ra": {
        "nasal": _swap("(া)(?=[ডঢ]" + _NUKTA + ")", "াঁ"),
        "r": _swap("[ডঢ]" + _NUKTA, "র"),
    },
}

# Which class a word belongs to is decided per occurrence by the pattern each variant uses, so one word can be touched by two classes (a word with both ওয়া and ড়). The ORDER matters: the specific
# classes first, the general consonant+য় ones last, and a class that already rewrote its য় leaves nothing for a later one to find (the rewritten text no longer contains the য় + nukta).
_ORDER = ("owa", "after_i", "after_aa_o", "before_vowel", "coda", "ra")


def classes() -> tuple[str, ...]:
    return _ORDER


RULES_FILE = os.environ.get("BN_GLIDE_FILE", "/workspace/glide_rules.json")
_FILE_CACHE: dict = {"mtime": None, "data": {}}


def _from_file() -> dict[str, str]:
    """{class: variant} from the data file (read again whenever it changes), so a listener's choice takes effect without a restart or a change to the environment the services were started with."""
    try:
        mtime = os.path.getmtime(RULES_FILE) if os.path.exists(RULES_FILE) else None
    except OSError:
        mtime = None
    if _FILE_CACHE["mtime"] == mtime:
        return _FILE_CACHE["data"]
    data: dict[str, str] = {}
    if mtime is not None:
        try:
            with open(RULES_FILE, encoding="utf-8") as fh:
                for cls, variant in (json.load(fh) or {}).items():
                    if cls in VARIANTS and variant in VARIANTS[cls]:
                        data[cls] = variant
        except (OSError, ValueError, AttributeError, TypeError):
            data = {}
    _FILE_CACHE["mtime"], _FILE_CACHE["data"] = mtime, data
    return data


def active() -> dict[str, str]:
    """{class: variant}: the data file (/workspace/glide_rules.json, {"coda": "e", ...}) with BN_GLIDE_RULES ("coda=e,owa=oa") on top; an unknown class or variant is ignored (a typo turns a rule off, never breaks a reply)."""
    chosen: dict[str, str] = dict(_from_file())
    for part in os.environ.get(_RULE_ENV, "").split(","):
        cls, _, variant = part.strip().partition("=")
        if cls in VARIANTS and variant in VARIANTS[cls]:
            chosen[cls] = variant
    return chosen


def rewrite(word: str, rules: dict[str, str] | None = None, force: bool = False) -> str:
    """The word with the chosen variant of every class applied (the word itself when none is chosen or it must be left alone)."""
    rules = active() if rules is None else rules
    if not rules:
        return word
    w = unicodedata.normalize("NFC", word)
    if w in LEAVE_ALONE and not force:  # force: for a listening pack that must hear the rule on a protected word too
        return word
    out = w
    for cls in _ORDER:
        variant = rules.get(cls)
        if variant:
            out = VARIANTS[cls][variant](out)
    return out if out != w else word


def classify(word: str) -> list[str]:
    """Which classes find something to rewrite in this word (for the audit and the listening pack): a class is listed when its first variant changes the word."""
    w = unicodedata.normalize("NFC", word)
    if w in LEAVE_ALONE:
        return []
    found = []
    for cls in _ORDER:
        first = next(iter(VARIANTS[cls].values()))
        if first(w) != w:
            found.append(cls)
    return found
