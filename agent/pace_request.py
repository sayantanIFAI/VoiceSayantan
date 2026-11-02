"""The caller asks the agent to speak slower, or with pauses ("স্লো বলুন", "একটু ধীরে বলুন", "থেমে থেমে বলুন", "speak slowly", "धीरे बोलिए").

Owner, 2026-11-03: three such requests in a row were each answered "হ্যাঁ, ঠিক ধরেছেন, কথা বলছেন" -- "কথা বলছেন" was found in the greeting and taken for a word asked back -- and the voice never got slower.
A request for a slower pace is its own thing: the agent says OK, says its last line again slowly, and every sentence after that is slower (each further request slows it more).
"""

from __future__ import annotations

import re
import unicodedata

_SLOW = re.compile(
    r"স্লো|সলো|ধীরে|ধীর\s*গতি|আস্তে|আস্তে|থেমে|ঠান্ডা মাথায়|\bslow(?:ly|er)?\b|धीरे|धीमे|स्लो|रुक\s*रुक|ठहर"
)
# a polite imperative / the verb "speak": "বলুন", "বলবেন", "কথা", "speak". NOT the first person ("বলছি" = I am saying).
_ASK = re.compile(r"বলুন|বলবেন|বলেন|বলো|বলছেন|কথা|পড়ুন|পড়ে|\bspeak\b|\bsay\b|\btalk\b|\bread\b|बोलिए|बोलिये|बोलो|बोलें|बताइए|कहिए|बोलिएगा")
# "faster" is the opposite request
_FASTER = re.compile(r"ফাস্ট|তাড়াতাড়ি|দ্রুত|জোরে|\bfast(?:er)?\b|\bquick(?:er|ly)?\b|तेज़|तेज|जल्दी")

FIRST_STEP = 0.72  # of the call's normal pace, on top of the senior / distressed policy rate
_FLOOR = 0.55  # the TTS accepts a rate of 0.5 at the lowest


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").lower()


def asks_slower(text: str) -> bool:
    t = _norm(text)
    if not t or len(t.split()) > 24 or not _SLOW.search(t) or _FASTER.search(t):
        return False
    return bool(_ASK.search(t)) or len(t.split()) <= 3


def next_factor(current: float) -> float:
    """The pace multiplier after one more request: 0.72 the first time, then 12% slower each time, never below the floor."""
    if current >= 1.0:
        return FIRST_STEP
    return max(_FLOOR, round(current * 0.88, 3))


_ACK = {
    "bn": "ঠিক আছে, আমি ধীরে ধীরে, থেমে থেমে বলছি।",
    "hi": "ठीक है, मैं धीरे-धीरे, रुक-रुक कर बोलती हूँ।",
    "en": "Sure, I will speak slowly, with pauses.",
}
_NOTHING_YET = {
    "bn": "ঠিক আছে, আমি ধীরে ধীরে বলছি। বলুন, কীভাবে সাহায্য করতে পারি?",
    "hi": "ठीक है, मैं धीरे-धीरे बोलती हूँ। बताइए, मैं कैसे मदद करूँ?",
    "en": "Sure, I will speak slowly. How can I help you?",
}


def ack(lang: str, have_last_line: bool) -> str:
    table = _ACK if have_last_line else _NOTHING_YET
    return table[lang if lang in ("bn", "hi") else "en"]
