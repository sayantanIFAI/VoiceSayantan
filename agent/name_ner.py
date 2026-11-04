"""A very basic name recogniser for the patient's name (call 3fa23f68: a correction, a mumble and an English misreading were each read back as "the name").

It answers one question about a caller's words: IS THERE A PERSON'S NAME IN THEM, and which words are it? Rule based, no model, nothing is invented: the name returned is always the caller's own words, with the words
around it removed.

 1. CUE. "আমার নাম X", "নামটা X", "my name is X", "मेरा नाम X", "naam X": the words after the last name-cue are the name ("আমি বললাম আমার নাম শুভজিৎ" -> "শুভজিৎ").
 2. BARE. With no cue, what is left after the filler words (pronouns, "is", "said", "yes", "ok", titles ...) are removed is the name ("হ্যাঁ সায়ন দাস" -> "সায়ন দাস").
 3. NOT A NAME. The sentence says something else -- it holds a digit or a number word, a question, a detail word (age, address, phone), a booking / doctor / day / health word -- or nothing is left after the fillers
    ("আমি নাম বললাম শুভজিৎ বয়স বললাম ঊনত্রিশ", "who was"). Then there is no name, and the caller is asked again rather than a guess being read back.
 4. CONFIDENCE. "high" when a cue introduced the name or a word is a known first name / surname (agent/common_surnames.py, FIRST_NAMES below); "medium" otherwise. A name is an open class, so an unknown word is
    still a name; the confidence only decides how much recogniser agreement the caller must have (see agent/booking_capture.py).
 5. SPEAKABLE. The reply voice reads one script: a Latin name inside a Bengali reply is blocked as unspeakable. `speakable_in(name, lang)` says whether the voice can say the name back.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from agent import common_surnames

_SPLIT = re.compile(r"[\s,।|!?.;:()\"“”‘’/]+")


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _set(text: str) -> frozenset[str]:
    return frozenset(_nfc(w).lower() for w in text.split())


# Words that introduce the name: the name is what comes after the LAST one.
_CUES = _set("নাম নামটা নামটি নামে নামের নেম name naam nam नाम नामः")

# Words that are never part of a name and say nothing else: dropped (Bengali, Hindi, English, and the Latin spellings of both).
_FILLERS = _set(
    """
    আমি আমার আমাকে আমরা আমাদের আপনি আপনার আপনাকে তুমি তোমার তোমাকে হচ্ছে হলো হল হয় হই হবে আছে আছি আছেন বলছি বললাম বলেছি বলেছিলাম বলব বলবো বলি বলুন বলল বললেন বলেছেন বলছেন বলতে বলে
    মানে তো ই ও এই ওই এটা ওটা সেটা না নয় নেই নাই হ্যাঁ হ্যা হাঁ হা জি জী ঠিক ঠিকাছে আচ্ছা ওকে একটু শুনুন শুনতে শুনেছেন আবার দয়া করে করুন প্লিজ ধন্যবাদ আর আরও কিন্তু তাহলে যে কি কী কে কার
    এখন তখন তাই বলে নিন দিন লিখুন লিখে এটি এখানে ওখানে এখানকার ইনি উনি চাঞ্জ চেঞ্জ বদল ভুল এটাই ওটাই এগুলো ওগুলো এইগুলো আপনারা
    मैं मेरा मेरी मेरे मुझे मुझको नाम है हैं हूँ हूं हो था थी बोला बोली कहा कहा बोल बोलो बोलिए रहा रही रहे हाँ हां जी ठीक अच्छा तो भी और कृपया धन्यवाद
    i am i'm is was were be been who what my me mine name's the this that it its it's said say says called call sir madam please yes yeah yep no nope ok okay hi hello thanks thank you and
    a an of to for here there
    ami amar amake bolchi bollam bolchhi bolechi naam nam mera main mai hai hain hu hoon boleche ache achhe holo hocche theek thik accha
    """
)

# Titles: not part of the name, dropped silently.
_TITLES = _set(
    "শ্রী শ্রীমতি শ্রীমতী মিস্টার মিসেস মিস মিঃ মিসটার জনাব স্যার ম্যাডাম বাবু মহাশয় श्री श्रीमती मिस्टर मिसेस mr mrs ms miss shri smt sri"
)

# Words that say the sentence is about something ELSE: a detail, a booking, a doctor, a day, a question, a health problem.
_NOT_NAME = _set(
    """
    ডাক্তার ডাঃ ডক্টর অ্যাপয়েন্টমেন্ট অ্যাপয়ন্টমেন্ট বুক বুকিং কাল কালকে আজ আজকে আজই কালই পরশু পরশুদিন আগামীকাল পরশুদিনের সকাল সকালে দুপুর দুপুরে বিকাল বিকেল সন্ধ্যা সন্ধ্যায় রাত রাতে
    ফোন ফোনের নম্বর নম্বরটা নাম্বার নাম্বরটা ঠিকানা ঠিকানাটা বয়স বয়সটা বছর বছরের মাস দিন সময় টেস্ট রেট টাকা চেম্বার চেম্বারে বসেন বসে বসবে বসবেন কখন কোথায় কত কেন কোন কীভাবে কোনটা
    হোয়াটসঅ্যাপ ফি চার্জ রিপোর্ট ক্লিনিক হয়েছে হয়েছিল লাগছে করছে যাচ্ছে যাব যাবো আসছি আসব পারব পারবো পারি পারবেন চাই লাগবে কেমন কাছে কথা জন্য সাথে পুলিশ স্টেশন থানা এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ শূন্য
    one two three four five six seven eight nine ten zero
    डॉक्टर अपॉइंटमेंट कल आज परसों नंबर फोन पता उम्र साल टेस्ट रेट रुपये कब कहाँ कितना क्यों कौन
    doctor dr appointment book booking today tomorrow phone number address age years test rate rupees when where how much why which clinic time date
    """
)

# Everyday first names and surnames, only to raise the confidence (a name is an open class: a word that is not here can still be a name).
FIRST_NAMES = _set(
    """
    শুভজিৎ শুভঙ্কর শুভ শুভদীপ সায়ন সায়ন্তন সায়ন্তনী সৌরভ সুব্রত সুদীপ সুদীপ্ত সুমন সুজিত সুশান্ত সঞ্জয় সন্দীপ সমীর সমর সৌমিত্র সৌম্য অমিত অমিতাভ অনির্বাণ অনিমেষ অনুপ অরুণ অরিজিৎ অরূপ অভিজিৎ
    অভিষেক অর্ণব আশিস আকাশ আবির আরিফ আব্দুল আলি আহমেদ কৌশিক কিশোর গৌতম গোপাল চন্দন চিরঞ্জিৎ জয়ন্ত জয়ন্তী জয়দীপ জয় তপন তন্ময় তনুশ্রী দেবাশিস দেবাশীষ দীপক দীপ্ত দিলীপ দেবজিৎ নির্মল
    নীলাদ্রি নিখিল নন্দিনী পার্থ প্রদীপ প্রবীর প্রসেনজিৎ প্রিয়াঙ্কা প্রিয়া পূজা পিয়া বিশ্বজিৎ বিজয় বিকাশ বিমল বাপি মৌসুমী মোহাম্মদ মহম্মদ মনোজ মানস মিতা রাজীব রাজেশ রাহুল রাজু রণজিৎ রবি
    রুবি রীতা রিয়া রুমা রমা রঞ্জিত রফিক রহিম রহমান সাগর সুনীতা সুচিত্রা সুপর্ণা স্বপন সুকান্ত শঙ্কর শংকর শ্যামল শিউলি শর্মিষ্ঠা শাহরুখ শারুখ সালমান ইমরান ইরফান ফারুক ফাতিমা আয়েশা সাবিনা
    সুলতানা নাসরিন নাজমা হাসান হোসেন করিম কবীর কাজল কণিকা কৃষ্ণ গীতা শ্রাবণী শ্রেয়া সৃজন সোহম ঋতব্রত ঋষি ঋতুপর্ণা মধুমিতা মহুয়া
    राहुल अमित सौरभ सुब्रत संजय प्रिया पूजा रवि रीता रिया सुमन दीपक
    rahul amit saurav sourav subrata sanjay priya puja ravi rita riya suman deepak arun tapan partha rajib rajesh
    """
)
_SURNAMES = common_surnames.SURNAMES | _set(
    "দাস দত্ত ঘোষ বসু বোস সেন রায় রায়চৌধুরী চৌধুরী সরকার মিত্র সাহা কর পাল ভট্টাচার্য বন্দ্যোপাধ্যায় ব্যানার্জী মুখার্জী চ্যাটার্জী গাঙ্গুলী ভদ্র নন্দী মন্ডল মণ্ডল বিশ্বাস দে মজুমদার চক্রবর্তী আনসারি খাতুন বেগম শেখ খান পাণ্ডে দাশগুপ্ত সেনগুপ্ত ঠাকুর হালদার দাশ"
)


@dataclass(frozen=True)
class NameSpan:
    name: str  # the caller's own words for the name, joined by one space
    words: tuple[str, ...]
    confidence: str  # "high" | "medium"
    evidence: str  # "cue" (introduced as the name) | "known" (a known name word) | "bare" (what was left)


_ENDINGS = ("ই", "ও", "টা", "টি", "র", "ের", "কে", "তে", "রা", "গুলো", "গুলি", "দের")


def _in(word: str, stop: frozenset[str]) -> bool:
    """Is the word, or the word without one common Bengali ending (নামটা, ডাক্তারের, এটাই), in a stop set?"""
    w = _nfc(word).lower()
    if w in stop:
        return True
    return any(w.endswith(e) and len(w) > len(e) + 1 and w[: -len(e)] in stop for e in _ENDINGS)


def _letters_only(word: str) -> bool:
    return bool(word) and all(unicodedata.category(c)[0] in ("L", "M") or c in "'.-’" for c in word)


def _is_number_word(word: str) -> bool:
    from agent import number_words

    try:
        return number_words.digits_of(word) is not None
    except Exception:  # noqa: BLE001 - a missing helper is never a reason to take a number for a name
        return False


def _script(word: str) -> str:
    for c in word:
        cp = ord(c)
        if 0x0980 <= cp <= 0x09FF:
            return "bn"
        if 0x0900 <= cp <= 0x097F:
            return "hi"
        if c.isascii() and c.isalpha():
            return "en"
    return "?"


def extract_name(text: str) -> NameSpan | None:
    """The name in the caller's words, or None when the words are not (only) a name."""
    raw = _nfc(text or "").strip()
    if not raw or "?" in raw or "؟" in raw or any(ch.isdigit() for ch in raw):
        return None
    tokens = [t.strip("-'’") for t in _SPLIT.split(raw) if t.strip("-'’")]
    if not tokens:
        return None
    low = [t.lower() for t in tokens]
    if any(_in(w, _NOT_NAME) or _is_number_word(w) for w in low):
        return None  # it says something else, or it holds an age / number: not a name answer
    cue_at = max((i for i, w in enumerate(low) if w in _CUES), default=-1)
    evidence = "cue" if cue_at >= 0 else "bare"
    pool = tokens[cue_at + 1 :] if cue_at >= 0 else tokens
    words = [t for t in pool if not _in(t, _FILLERS) and t.lower() not in _TITLES and t.lower() not in _CUES]
    dropped_fillers = len(words) < len(pool) and any(_in(t, _FILLERS) for t in pool)
    if not 1 <= len(words) <= 4 or not all(_letters_only(w) for w in words):
        return None
    if any(sum(1 for c in w if c.isalpha()) < 2 for w in words):
        return None  # one letter is a clipped "yes" or an initial, never a name on its own
    if len({_script(w) for w in words}) > 1:
        return None  # a mixture of scripts is a misreading ("জয় kumar"), not something to read back
    from agent import off_topic  # local import: off_topic is a larger module this one does not otherwise need

    if off_topic.has_health_word(
        raw
    ):  # a symptom said at the name question ("আমার ডেঙ্গু হয়েছে") is an answer to something else, whatever is left of it
        return None
    known = any(w.lower() in FIRST_NAMES or _nfc(w) in _SURNAMES for w in words)
    if evidence == "bare" and dropped_fillers and not known:
        return None  # "হ্যাঁ পারবো", "এই সেদিনেরই করুন": filler words and one word nothing vouches for is a sentence, not a name (a name said with "yes" in front is vouched for by a name word or a cue)
    name = " ".join(w.title() if w.isascii() else w for w in words)
    return NameSpan(
        name=name,
        words=tuple(words),
        confidence="high" if evidence == "cue" or known else "medium",
        evidence="cue" if evidence == "cue" else ("known" if known else "bare"),
    )


def speakable_in(name: str, lang: str) -> bool:
    """Can the voice of a reply in `lang` say this name back? It reads one script: Bengali letters in a Bengali reply, Devanagari in a Hindi one, Latin in an English one."""
    scripts = {_script(w) for w in (name or "").split()} - {"?"}
    if not scripts:
        return False
    want = lang if lang in ("bn", "hi", "en") else "en"
    return scripts == {want}
