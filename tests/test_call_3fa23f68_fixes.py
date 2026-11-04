"""Call 3fa23f68: two faults that were not about names.

* "করুন" / "করেন" (Bengali "do") were flagged as Hindi because their sound matches Hindi करना, so "না বেস করুন" (no, book) was read by the Hindi recogniser as "मैं बिलकुल" and answered "yes, go ahead".
* The "did you say X?" handler fired on "আমি নাম বললাম শুভজিৎ বয়স বললাম ঊনত্রিশ" (its cue "বলল" is inside "বললাম", I said) and answered "না, আমি 29 বলিনি".

   python -m pytest tests/test_call_3fa23f68_fixes.py -v
"""

import asyncio
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_orchestrator_booking_flow import FakeWS, m  # noqa: F401,E402  (the harness: the real orchestrator with the pod-only libraries stubbed)

from agent import hindi_in_bengali as hib  # noqa: E402


@pytest.mark.parametrize(
    "said",
    [
        "না বেস করুন",
        "হ্যাঁ হ্যাঁ করুন",
        "আপনি করুন",
        "বুক করুন",
        "ওনারা কি বুক করেন",
        "আমি করিনি",
        "বাংলায় বলুন",
        "বাংলায় বলবেন",
        "আমি টেস্ট করানো",
        "কালকে সকালে বুক করুন",
    ],
)
def test_ordinary_bengali_is_not_taken_for_hindi(said):
    assert hib.looks_hindi(said) is False, said


@pytest.mark.parametrize("said", ["উধার", "আমি উধার যাব", "মুঝে চাহিয়ে", "হ্যাঁ উধার"])
def test_real_hindi_is_still_flagged(said):
    assert hib.looks_hindi(said) is True, said


def word_check(m, monkeypatch, said, last):  # noqa: F811
    spoken: list[str] = []

    async def speak(session, text, lang=None, **kw):
        spoken.append(text)
        return 0.0

    async def no_date(session, text, lang):
        return False

    async def no_echo(session, text, lang):
        return False

    monkeypatch.setattr(m, "_speak", speak)
    monkeypatch.setattr(m, "_answer_date_weekday", no_date)
    monkeypatch.setattr(m, "_answer_echo", no_echo)

    async def go():
        session = m.CallSession(FakeWS())
        session.last_spoken = last
        try:
            return await m._answer_word_check(session, said, "bn")
        finally:
            session.cleanup()

    return asyncio.run(go()), spoken


@pytest.mark.parametrize(
    "said",
    [
        "আমি নাম বললাম শুভজিৎ বয়স বললাম ঊনত্রিশ",
        "আমি বললাম আমার বয়স সাতাশ",
        "বললাম উনত্রিশ",
        "আমি বলেছি পঁচিশ",
        "আমি বলছি তিরিশ",
    ],
)
def test_i_said_is_not_a_question_about_what_the_agent_said(m, monkeypatch, said):  # noqa: F811
    handled, spoken = word_check(m, monkeypatch, said, "আমি নামটা শুনেছি নলতির। রোগীর বয়স কত?")
    assert handled is False and spoken == []


def test_a_real_check_of_a_number_is_still_answered(m, monkeypatch):  # noqa: F811
    handled, spoken = word_check(m, monkeypatch, "পঁয়তাল্লিশ বললেন", "আপনার টেস্টের রেট 45 টাকা।")
    assert handled is True and spoken and "45" in spoken[0]
    handled, spoken = word_check(m, monkeypatch, "চল্লিশ বললেন", "আপনার টেস্টের রেট 45 টাকা।")
    assert handled is True and "40" in spoken[0]
