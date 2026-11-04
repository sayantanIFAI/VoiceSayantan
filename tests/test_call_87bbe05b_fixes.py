"""Call 87bbe05b: "বুক" (book / chest), a booking that had a doctor and a day but no time and asked "shall I book that day?" three times, and a name taken by the model although the name rule could have had it.

python -m pytest tests/test_call_87bbe05b_fixes.py -v
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

from agent import book_words, off_topic  # noqa: E402
from agent import booking_capture as bc  # noqa: E402
from agent import booking_carryover as bco  # noqa: E402
from agent.booking_flow import new_state  # noqa: E402

# ------------------------------------------------------------------------------------------------ বুক: book or chest


@pytest.mark.parametrize(
    "said", ["হ্যাঁ কালকের জন্য বুক করুন", "বুক করুন", "কালকে বুক করে দিন", "ওনার সাথে বুক করব", "বুক দিন", "বুক কর দো", "বুক তো করিনি", "হ্যাঁ বুক তো করিনি", "বুক ই করব"]
)
def test_the_verb_book_is_not_the_chest(said):
    assert book_words.has_book_verb(said) is True
    assert off_topic.has_health_word(said) is False, said
    assert bco.asks_to_book(said) is True, said
    assert "বুক" not in book_words.strip_book_verb(said)


@pytest.mark.parametrize("said", ["বুকে ব্যথা", "আমার বুক ব্যথা করছে", "বুক ধড়ফড় করছে", "আমার বুকের ব্যথা", "বুকে চাপ লাগছে"])
def test_the_chest_is_still_the_chest(said):
    assert book_words.has_book_verb(said) is False
    assert off_topic.has_health_word(said) is True, said
    assert bco.asks_to_book(said) is False, said
    assert book_words.strip_book_verb(said) == said


def test_a_chest_complaint_and_a_booking_in_one_sentence():
    said = "বুকে ব্যথা, ডাক্তার বুক করে দিন"
    assert off_topic.has_health_word(said) is True and bco.asks_to_book(said) is True


def test_the_department_route_never_sees_the_book_verb_as_the_chest(m, monkeypatch):  # noqa: F811
    seen = []

    class Tools:
        async def route_department(self, text, lang="bn", **kw):
            seen.append(text)
            return {"matched": False}

    monkeypatch.setattr(m, "_tools", Tools())
    asyncio.run(m._route_dept("হ্যাঁ কালকের জন্য বুক করুন", "bn"))
    asyncio.run(m._route_dept("বুকে ব্যথা", "bn"))
    assert "বুক" not in seen[0] and seen[1] == "বুকে ব্যথা"


# ------------------------------------------------------------------------------------------------ a time for the booking


def doctor_booking(**extra):
    st = new_state("book_appointment")
    st.stage = "collecting"
    st.slots.update({"doctor_name": "Tanmoy Ghoshal", "date": "2026-11-05", **extra})
    return st


class FreeSlots:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    async def free_slots(self, doctor, date):
        self.asked.append((doctor, date))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


GOOD = {
    "found": True,
    "sits": True,
    "valid_slots": ["11:00", "11:10", "11:20"],
    "free_slots": ["11:20", "11:00", "11:10"],
}


def fill(m, monkeypatch, st, answer):  # noqa: F811
    tools = FreeSlots(answer)
    monkeypatch.setattr(m, "_tools", tools)

    async def go():
        session = m.CallSession(FakeWS())
        try:
            return await m._fill_time_slot(session, st, "bn")
        finally:
            session.cleanup()

    return asyncio.run(go()), tools


def test_a_booking_with_a_doctor_and_a_day_but_no_time_takes_the_first_free_slot(m, monkeypatch):  # noqa: F811
    st = doctor_booking()
    done, tools = fill(m, monkeypatch, st, GOOD)
    assert done is True and st.slots["time_slot"] == "11:00" and tools.asked == [("Tanmoy Ghoshal", "2026-11-05")]


def test_nothing_is_filled_when_there_is_nothing_to_fill_or_nothing_free(m, monkeypatch):  # noqa: F811
    already = doctor_booking(time_slot="11:30")
    assert fill(m, monkeypatch, already, GOOD)[0] is False and already.slots["time_slot"] == "11:30"
    no_day = new_state("book_appointment")
    no_day.slots.update({"doctor_name": "Tanmoy Ghoshal"})
    assert fill(m, monkeypatch, no_day, GOOD)[0] is False
    assert fill(m, monkeypatch, doctor_booking(), {**GOOD, "free_slots": []})[0] is False
    assert fill(m, monkeypatch, doctor_booking(), {**GOOD, "sits": False})[0] is False
    assert fill(m, monkeypatch, doctor_booking(), {"found": False})[0] is False
    assert (
        fill(m, monkeypatch, doctor_booking(), RuntimeError("clinic api down"))[0] is False
    )  # a failure leaves the booking as it was
    skipped = doctor_booking(_time_skip=["11:00"])
    assert fill(m, monkeypatch, skipped, GOOD)[0] is True and skipped.slots["time_slot"] == "11:10"


# ------------------------------------------------------------------------------------------------ the same question a third time

QUESTION = "ডাক্তার যে সময়ে বসেন, সেই সময়েই আপনার অ্যাপয়েন্টমেন্ট করে দেব। আগামীকাল, পাঁচ তারিখে অ্যাপয়েন্টমেন্ট করব?"


def repeat(m, earlier_turns, turn_count=9, booking=True, text=QUESTION):  # noqa: F811
    async def go():
        session = m.CallSession(FakeWS())
        session.turn_count = turn_count
        session.booking = doctor_booking() if booking else None
        session.recent_spoken = [(m._same_line_key(text), t) for t in earlier_turns]
        try:
            out = await m._never_the_same_question_twice(session, text, "bn", False)
            return out, session.awaiting_handoff_offer
        finally:
            session.cleanup()

    return asyncio.run(go())


def test_a_booking_question_is_left_alone_the_first_and_second_time(m):  # noqa: F811
    assert repeat(m, []) == (QUESTION, False)
    assert repeat(m, [8]) == (QUESTION, False)  # asked once before: the caller may simply not have been heard


def test_the_third_time_a_person_is_offered_and_a_yes_is_taken_by_the_offer(m):  # noqa: F811
    out, awaiting = repeat(m, [7, 8])
    assert out != QUESTION and "কাউন্টার" in out and awaiting is True
    out, awaiting = repeat(m, [6, 7, 8])
    assert out != QUESTION and awaiting is True


def test_a_different_question_or_one_said_in_this_same_turn_is_not_a_loop(m):  # noqa: F811
    assert repeat(m, [9, 9])[0] == QUESTION  # said in this same turn: not a repeat
    assert (
        repeat(m, [8], text="আপনার বয়সটা আবার একবার বলবেন, একটু স্পষ্ট করে?")[0] == "আপনার বয়সটা আবার একবার বলবেন, একটু স্পষ্ট করে?"
    )
    other = "আপনার বয়সটা আবার একবার বলবেন, একটু স্পষ্ট করে?"
    assert repeat(m, [7, 8], text=other)[1] is True  # the same rule for every booking question


# ------------------------------------------------------------------------------------------------ the name, with the time listed first


def only_time_and_name_missing():
    st = new_state("book_appointment")
    st.stage = "collecting"
    st.slots.update(
        {"doctor_name": "Tanmoy Ghoshal", "date": "2026-11-05", "phone": "9876543210", "_phone_ok": "9876543210"}
    )
    st.asked_fields.add("patient_name")
    return st


def test_the_name_rule_applies_when_the_never_asked_time_is_listed_first():
    st = only_time_and_name_missing()
    plan = bc.before_model(st, "শুভজিৎ", "bn", agreement=1.0)
    assert plan.speak and st.pending_name == "শুভজিৎ"


def test_the_name_rule_still_waits_when_something_else_is_missing():
    st = only_time_and_name_missing()
    st.slots.pop("phone")
    st.slots.pop("_phone_ok")
    st.asked_fields.discard("phone")
    assert bc.before_model(st, "শুভজিৎ", "bn", agreement=1.0).speak is None  # the number is what is waited for


def test_the_never_asked_time_does_not_name_the_kind_of_answer_waited_for(m):  # noqa: F811
    session = m.CallSession(FakeWS())
    session.booking = only_time_and_name_missing()
    session.last_spoken = "আপনার নামটা বলবেন প্লিজ?"
    try:
        assert m._expected_answer_kind(session) == "name"  # not "day"
    finally:
        session.cleanup()
