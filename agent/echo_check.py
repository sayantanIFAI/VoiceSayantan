"""The caller checks back something the agent SAID: "বেনিয়া পুকুর কেয়া?" ("Beniapukur, is it?") after hearing the address in Hindi.

Owner, 2026-10-18: anything spoken by the AI, the patient can ask back about -- and the answer is "yes, that is right" with the sentence again, or the correct answer. The caller's
word and the agent's word are written in different scripts (Bengali letters against Devanagari, or against Latin), so they are compared by SOUND: every word is reduced to its
consonant skeleton in one common alphabet, and two words that have the same skeleton are the same word. Nothing here invents an answer: it only finds the sentence the agent actually said.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

# consonants of Bengali and Devanagari -> a common Latin letter. Vowels, vowel signs, the nukta, the virama and h / y / w are dropped, so spelling variants collapse.
_MAP = {
    **{c: "k" for c in "কখक"}, **{c: "g" for c in "গঘगघ"}, **{c: "n" for c in "ঙঞণনङञणन"}, **{c: "c" for c in "চছचछ"}, **{c: "j" for c in "জঝजझ"},
    **{c: "t" for c in "টঠতথৎटठतथ"}, **{c: "d" for c in "ডঢদধडढदध"}, **{c: "p" for c in "পফपफ"}, **{c: "b" for c in "বভबभव"}, **{c: "m" for c in "মम"},
    **{c: "r" for c in "রर"}, **{c: "l" for c in "লल"}, **{c: "s" for c in "শষসशषस"}, "ক্ষ": "ks",
}
_LATIN = {"c": "k", "q": "k", "v": "b", "w": "", "z": "j", "f": "p", "x": "ks"}
_DROP_LATIN = set("aeiouyh")
_CUES = (
    "কেয়া", "কি", "কী", "ঠিক", "সঠিক", "ঠিকই", "তাই তো", "নাকি", "ना", "क्या", "सही", "ठीक", "ही", "right", "correct", "is it", "is that", "ki", "kya", "sahi", "thik", "theek", "?",
    # Owner, 2026-10-27: real call, 2026-10-26 -- "সিটি সেন্টার ২ বললেন?" (did you say City Centre 2?), echoing an
    # address back with a past/present-tense "say" verb instead of "কি/ঠিক", matched nothing (none of these verbs
    # were a cue) and the turn fell through unanswered. All are already in _STOP so they are never mistaken for the
    # word being asked back, only for the fact that something IS being asked back.
    "বললেন", "বলছেন", "বলেছেন", "বোলে", "बोले", "बोला", "बोली", "कहा", "कहे", "bolle", "bolchen", "bola", "bole", "kaha",
)


def skeleton(word: str) -> str:
    w = (word or "").lower()
    for rr in ("ড়", "ঢ়", "ड़", "ढ़"):  # ড় ঢ় ड़ ढ़ are an r (flap), not a d
        w = w.replace(rr, "r")
    w = unicodedata.normalize("NFD", w)  # precomposed nukta letters (ज़ फ़ ...) fall apart into the letter and the nukta; the nukta is dropped below
    w = w.replace("ক্ষ", "ks")
    out: list[str] = []
    if w.isascii():
        w = w.replace("ch", "c").replace("sh", "s").replace("ph", "p").replace("th", "t").replace("dh", "d").replace("kh", "k").replace("gh", "g").replace("bh", "b")
        for ch in w:
            if not ch.isalpha() or ch in _DROP_LATIN:
                continue
            out.append(_LATIN.get(ch, ch))
    else:
        for ch in w:
            if ch in _MAP:
                out.append(_MAP[ch])
            elif ch.isascii() and ch.isalpha() and ch not in _DROP_LATIN:
                out.append(_LATIN.get(ch, ch))
    s = "".join(out)
    return re.sub(r"(.)\1+", r"\1", s)  # a doubled consonant is one sound


# Owner, 2026-11-02: "c i d road" (spelled letters, the recogniser wrote them in Latin) asked back "সি আই টি রোড" (the same letters as the agent said them). A run of letters is one word, written the same
# way on both sides: "zq" + the letters (d and t are folded -- they are one sound on a telephone line).
_LETTER_NAMES = {
    "এ": "a", "বি": "b", "সি": "c", "ডি": "d", "ই": "e", "এফ": "f", "জি": "g", "এইচ": "h", "আই": "i", "জে": "j", "কে": "k", "এল": "l", "এম": "m", "এন": "n", "ও": "o", "পি": "p", "কিউ": "q",
    "আর": "r", "এস": "s", "টি": "t", "ইউ": "u", "ভি": "v", "ডাবলিউ": "w", "এক্স": "x", "ওয়াই": "y", "জেড": "z",
    "ए": "a", "बी": "b", "सी": "c", "डी": "d", "ई": "e", "एफ": "f", "जी": "g", "एच": "h", "आई": "i", "जे": "j", "के": "k", "एल": "l", "एम": "m", "एन": "n", "ओ": "o", "पी": "p", "क्यू": "q",
    "आर": "r", "एस": "s", "टी": "t", "यू": "u", "वी": "v", "डब्ल्यू": "w", "एक्स": "x", "वाई": "y", "ज़ेड": "z",
}


def _letter(tok: str) -> str | None:
    t = (tok or "").strip().lower()
    if len(t) == 1 and "a" <= t <= "z":
        return t
    return _LETTER_NAMES.get(unicodedata.normalize("NFC", tok or "").strip())


def fold_letter_runs(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    """Runs of single letters (three or more spoken names, or two or more Latin letters) become one token; `back` says what each stood for."""
    out: list[str] = []
    back: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        j = i
        letters: list[str] = []
        while j < len(tokens) and _letter(tokens[j]) is not None:
            letters.append(_letter(tokens[j]))  # type: ignore[arg-type]
            j += 1
        latin_run = all(len(tokens[k]) == 1 and tokens[k].isascii() for k in range(i, j))
        if letters and len(letters) >= (2 if latin_run else 3):
            tok = "zq" + "".join("t" if c == "d" else c for c in letters)
            back[tok] = " ".join(tokens[i:j])
            out.append(tok)
            i = j
        else:
            out.append(tokens[i])
            i += 1
    return out, back


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,।.?!;:\-()\"']+", unicodedata.normalize("NFC", text or "")) if t]


# Little words that answer or soften a sentence are never the thing asked back ("ঠিক আছে" is an answer, not a question about the words "ঠিক আছে" in the agent's last sentence).
_STOP = frozenset(
    "ঠিক আছে আছে হ্যাঁ হ্যা হাঁ না নাকি কি কী কেয়া তো ই জি ওকে এটা ওটা এই ওই সেই এ ও আর এবং তাই সঠিক বলুন বলবেন বললেন বলেছেন বলছেন বোলে "
    "ठीक है हाँ हां जी नहीं ना क्या ही तो यह वह ये वो और सही बताइए बोले बोला बोली कहा कहे "
    "ok okay yes no is it that the a an right correct ji haan han hai ki kya bolle bolchen bola bole kaha".split()
)


def _candidates(tokens: list[str]) -> list[tuple[str, str]]:
    """(the words as said, their skeleton) for every word and every run of two or three words joined: "বেনিয়া পুকুর" is the one word "বেনিয়াপুকুর" in the agent's sentence."""
    out = []
    for n in (1, 2, 3):
        for i in range(len(tokens) - n + 1):
            chunk = tokens[i : i + n]
            if all(t.lower() in _STOP for t in chunk):
                continue
            sk = skeleton("".join(chunk))
            if len(sk) >= 3:
                out.append((" ".join(chunk), sk))
    return out


def asks_back(text: str) -> bool:
    t = unicodedata.normalize("NFC", text or "").lower()
    words = set(_tokens(t))
    # a short cue ("কি", "ঠিক", "ki") counts only as a whole word: inside "বাকিটা" or "ঠিকানা" it is just letters (real call 2026-10-23: "বাকিটা হচ্ছে ফাইভ সিক্স…" was taken for a question)
    return any((c in words) if len(c) <= 3 and c != "?" else (c in t) for c in _CUES)


def find(user_text: str, last_spoken: str, bare: bool = False) -> tuple[str, str] | None:
    """(the caller's words that name something the agent said, the agent's sentence that holds it), or None. Only a short sentence that asks back is considered; the match is by
    sound, exact on the skeleton or a very close one for a longer word. The cue words themselves ("কেয়া", "ঠিক") are never the thing looked for."""
    if not user_text or not last_spoken:
        return None
    said, _back_user = fold_letter_runs(_tokens(user_text))
    # bare=True (owner, 2026-11-01): the caller just SAYS back a word or phrase of the agent's last reply, with no "কেয়া / ঠিক / did you say" -- "অরুণ কুমার", "ছয়শো টাকা". Only a short
    # sentence, and every content word of it must be found in what the agent said.
    if not 1 <= len(said) <= (5 if bare else 8) or (not bare and not asks_back(user_text)):
        return None
    cue_skeletons = {skeleton(c) for c in _CUES if c != "?"} | {""}
    spoken_sentences = [s.strip() for s in re.split(r"(?<=[।.?!])\s+", last_spoken) if s.strip()] or [last_spoken]
    best = None
    best_spoken_words = None
    _back_spoken: dict[str, str] = {}
    for words, sk in _candidates(said):
        if sk in cue_skeletons:
            continue
        for sentence in spoken_sentences:
            _stoks, _bk = fold_letter_runs(_tokens(sentence))
            _back_spoken.update(_bk)
            for _w, sk2 in _candidates(_stoks):
                ratio = 1.0 if sk == sk2 else difflib.SequenceMatcher(None, sk, sk2).ratio()
                need = 1.0 if min(len(sk), len(sk2)) <= 4 else 0.86
                if ratio >= need and (best is None or ratio > best[0] or (ratio == best[0] and len(sk) > len(best[3]))):
                    best = (ratio, words, sentence, sk)
                    best_spoken_words = _w
    if best is None:
        return None
    # the words asked back must be most of what was said: one matching word inside a long ordinary question ("… কি বাড়ি গিয়ে নমুনা সংগ্রহ করেন") is not it
    content = [t for t in said if t.lower() not in _STOP and skeleton(t) not in cue_skeletons]
    if len(best[1].split()) * 2 < len(content):
        return None
    if bare and len([t for t in best[1].split() if t.lower() not in _STOP]) < len(content):
        return None  # a bare repeat is ONLY the agent's own words: one matching word inside a different sentence is not an echo
    words_out = best[1]
    if "zq" in words_out and best_spoken_words:
        words_out = best_spoken_words
        for tok, original in _back_spoken.items():
            words_out = words_out.replace(tok, original)
    return words_out, best[2]
