"""Is the doctor from Kolkata? (owner, 2026-10-29)

The doctor table has a "From Kolkata?" column ("yes" / "no"). A caller who asks "উনি কি কলকাতার লোক?", "डॉक्टर कोलकाता के हैं?", "is the doctor from Kolkata?" is answered from it, in one fixed sentence, about the doctor
named in the sentence or just discussed. A doctor whose column is empty is not guessed about. Pure functions, no I/O.
"""

from __future__ import annotations

import re
import unicodedata

_KOLKATA = r"(?:কলকাতা|কোলকাতা|কলিকাতা|कोलकाता|कलकत्ता|कोलकता|kolkata|calcutta|kolkota|kolkatar|kolkatay|kolkata theke|kolkatar lok)"
_BN_Q = re.compile(rf"{_KOLKATA}\S*\s*(?:লোক|বাসিন্দা|থেকে|ই|কি|কী|না|নাকি|ডাক্তার)?|(?:কোথাকার|কোথা থেকে এসেছেন|কোথায় বাড়ি|বাড়ি কোথায়|কোন জেলার|কোন শহরের)")
_HI_Q = re.compile(r"कोलकाता\S*|कलकत्ता\S*|कोलकता\S*|(?:कहाँ के|कहां के|कहाँ से|कहां से|किस शहर)")
_EN_Q = re.compile(rf"\b{_KOLKATA}\b|\b(?:where is (?:he|she|the doctor) from|where (?:does|do) (?:he|she|the doctor) (?:come|live)|local doctor|from (?:this )?city)\b", re.I)
# a question about the PERSON, not about the clinic's address ("ক্লিনিক কলকাতার কোথায়?")
_NOT_ABOUT_DOCTOR = re.compile(r"ক্লিনিক|হাসপাতাল|ঠিকানা|কোথায় আপনারা|आपका (?:पता|क्लिनिक)|\b(?:clinic|hospital|address|located|location)\b", re.I)
_DOCTOR_WORD = re.compile(r"ডাক্তার|ডক্টর|ডাঃ|উনি|ওনার|ওনি|তিনি|डॉक्टर|डॉ\b|वे\b|उनका|उनके|\b(?:doctor|dr\b|he|she|him|her)\b", re.I)


def asks_doctor_origin(text: str, has_context: bool = False) -> bool:
    """`has_context`: a doctor (or a department's doctors) is the subject of the conversation -- then a Kolkata word alone is the question, whatever else the recogniser made of the sentence."""
    t = unicodedata.normalize("NFC", text or "").strip()
    if not t or len(t.split()) > 30 or _NOT_ABOUT_DOCTOR.search(t):
        return False
    hit = _BN_Q.search(t) or _HI_Q.search(t) or _EN_Q.search(t)
    if not hit:
        return False
    if has_context:
        return True
    # "কোথাকার" / "where from" needs no city word; a city word needs a doctor (or he / she) beside it
    return bool(re.search(r"কোথাকার|কোথা থেকে|কহाँ|कहाँ के|कहां के|where is|where does", t, re.I)) or bool(_DOCTOR_WORD.search(t))


_YES = {
    "bn": "হ্যাঁ, {who} কলকাতার।",
    "hi": "जी हाँ, {who} कोलकाता से हैं।",
    "en": "Yes, {who} is from Kolkata.",
}
_NO = {
    "bn": "না, {who} কলকাতার নন।",
    "hi": "नहीं, {who} कोलकाता से नहीं हैं।",
    "en": "No, {who} is not from Kolkata.",
}
_UNKNOWN = {
    "bn": "{who} কোথাকার, সেই তথ্য আমার কাছে নেই। কাউন্টারে জিজ্ঞেস করতে পারেন।",
    "hi": "{who} कहाँ के हैं, यह जानकारी मेरे पास नहीं है। काउंटर पर पूछ सकते हैं।",
    "en": "I do not have that information about {who}. You can ask at the counter.",
}


def reply(value: str | None, who: str, lang: str) -> str:
    lg = lang if lang in ("bn", "hi", "en") else "en"
    table = _YES if (value or "").strip().lower() == "yes" else _NO if (value or "").strip().lower() == "no" else _UNKNOWN
    return table[lg].format(who=who)


_MANY = {
    "bn": "কলকাতা থেকে অনেক ডাক্তার আছেন।",
    "hi": "कोलकाता के कई डॉक्टर हैं।",
    "en": "Many of our doctors are from Kolkata.",
}
_ONE = {
    "bn": "কলকাতার একজন ডাক্তার আছেন।",
    "hi": "कोलकाता के एक डॉक्टर हैं।",
    "en": "One of our doctors is from Kolkata.",
}


def how_many_lead(count: int, lang: str) -> str:
    """Owner, 2026-11-02 ("কোন ডাক্তার আরে ওই কলকাতা থেকে কে আছে"): no doctor is named, so the answer is how many are from Kolkata (counted from the table's own column), then the question stays open."""
    lg = lang if lang in ("bn", "hi", "en") else "en"
    if count >= 2:
        return _MANY[lg]
    if count == 1:
        return _ONE[lg]
    return ""


_KOLKATA_FILTER = re.compile(rf"{_KOLKATA}\S*\s*(?:থেকে|থেকেই|এর|র|ের|লোক|ডাক্তার|কি|के|से)?", re.I)


def asks_kolkata_doctors(text: str) -> bool:
    """A sentence about WHO sits (a department, a day) that also asks for the Kolkata ones: "বুকের ডাক্তার কেউ আছে কলকাতা থেকে"."""
    t = unicodedata.normalize("NFC", text or "")
    return bool(_KOLKATA_FILTER.search(t)) and not _NOT_ABOUT_DOCTOR.search(t)


_FILTER_YES = {
    "bn": "হ্যাঁ, কলকাতার ডাক্তার আছেন।",
    "hi": "जी हाँ, कोलकाता के डॉक्टर हैं।",
    "en": "Yes, there are doctors from Kolkata.",
}
_FILTER_NO = {
    "bn": "না, {label} বিভাগের কেউ কলকাতার নন।",
    "hi": "नहीं, {label} विभाग का कोई डॉक्टर कोलकाता से नहीं है।",
    "en": "No, nobody in {label} is from Kolkata.",
}


def filter_lead(found: bool, label: str, lang: str) -> str:
    lg = lang if lang in ("bn", "hi", "en") else "en"
    return _FILTER_YES[lg] if found else _FILTER_NO[lg].format(label=label)
