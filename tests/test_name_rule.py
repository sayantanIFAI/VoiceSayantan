"""The patient's name, answered with a plain name, is read back without asking the intent model, and the saved-answer cache is not used while a booking waits for a detail (call 99e76cf7: a name heard right three
times was asked for four times because the model never returned patient_name and the cache repeated its miss).

    python -m pytest tests/test_name_rule.py -v
"""

import asyncio
import os
import sys
import types

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_orchestrator_booking_flow import FakeWS, m  # noqa: F401,E402  (the harness: the real orchestrator with the pod-only libraries stubbed)

from agent import booking_capture as bc
from agent.booking_flow import new_state


def waiting_for_name(**extra):
    st = new_state("book_appointment")
    st.stage = "collecting"
    st.slots.update(
        {
            "doctor_name": "Debasish Das",
            "date": "2026-11-06",
            "time_slot": "10:00",
            "phone": "9876543210",
            "_phone_ok": "9876543210",
            **extra,
        }
    )
    st.asked_fields.add("patient_name")
    return st


@pytest.mark.parametrize(
    "said, lang",
    [
        ("গায়ন্ত", "bn"),
        ("জয়ন্তী", "bn"),
        ("জয়ন্ত", "bn"),
        ("আমার নাম জয়ন্ত", "bn"),
        ("সুব্রত কুমার দাস", "bn"),
        ("Rahul Das", "en"),
    ],
)
def test_a_plain_name_is_read_back_for_a_yes(said, lang):
    st = waiting_for_name()
    plan = bc.before_model(st, said, lang, agreement=1.0)
    assert plan.speak and st.pending_name, said
    assert st.pending_name.split()[-1].lower() in plan.speak.lower()  # the read-back carries the name as heard
    assert "patient_name" not in st.slots  # nothing is stored before the yes


@pytest.mark.parametrize(
    "said",
    [
        "আচ্ছা",
        "হ্যাঁ",
        "না",
        "কখন বসবে",
        "ডাক্তার সেন",
        "আবার বলুন",
        "ঠিক আছে",
        "9876543210",
        "আমার ফোন নম্বর",
        "জয়ন্ত?",
        "hello please wait",
        "আমার ডেঙ্গু হয়েছে",
        "পেটে ব্যথা",
        "আর রবিবারে বসে",
    ],
)
def test_something_else_is_left_to_the_model(said):
    st = waiting_for_name()
    plan = bc.before_model(st, said, "bn", agreement=1.0)
    assert st.pending_name is None and not plan.speak, said


def test_it_only_applies_when_the_name_is_the_next_thing_asked():
    never_asked = waiting_for_name()
    never_asked.asked_fields.discard("patient_name")
    assert bc.before_model(never_asked, "জয়ন্ত", "bn", agreement=1.0).speak is None
    no_phone_yet = waiting_for_name()
    no_phone_yet.slots.pop("phone")
    no_phone_yet.slots.pop("_phone_ok")
    assert bc.before_model(no_phone_yet, "জয়ন্ত", "bn", agreement=1.0).speak is None
    other_action = new_state("cancel_appointment")
    assert bc.before_model(other_action, "জয়ন্ত", "bn", agreement=1.0).speak is None


def test_poor_recognition_is_asked_again_but_the_second_try_is_let_through_on_less():
    st = waiting_for_name()
    assert (
        bc.before_model(st, "নলতির", "bn", agreement=0.0).speak is None
    )  # first try, nothing usable (a name no list vouches for)
    assert st.slots["_name_tries"] == 1
    assert bc.before_model(st, "নলতির", "bn", agreement=0.3).speak is None  # still too little
    assert bc.before_model(
        st, "নলতির", "bn", agreement=0.6
    ).speak  # a repeated answer heard at 0.6 is read back, not asked a third time
    assert "_name_tries" not in st.slots and st.pending_name == "নলতির"
    first_try = waiting_for_name()
    assert (
        bc.before_model(first_try, "নলতির", "bn", agreement=0.6).speak is None
    )  # 0.6 is not enough on the first try for an unknown name


def test_a_known_name_or_one_introduced_as_a_name_needs_less_agreement():
    known = waiting_for_name()
    assert bc.before_model(
        known, "জয়ন্ত", "bn", agreement=0.6
    ).speak  # a known first name: 0.6 is enough even on the first try
    assert bc.before_model(waiting_for_name(), "জয়ন্ত", "bn", agreement=0.5).speak is None
    cued = waiting_for_name()
    assert bc.before_model(cued, "আমার নাম নলতির", "bn", agreement=0.6).speak  # introduced as the name


def test_an_unknown_agreement_does_not_block_the_rule():
    st = waiting_for_name()
    assert bc.before_model(st, "জয়ন্ত", "bn").speak


# --------------------------------------------------------------------------------------------- the cache


class Recorder:
    def __init__(self):
        self.gets, self.puts = [], []

    def get(self, key):
        self.gets.append(key)
        return None, "miss"

    def put(self, key, value):
        self.puts.append(key)


def run_resolve(m, monkeypatch, booking):  # noqa: F811
    cache = Recorder()
    monkeypatch.setattr(m, "_intent_cache", cache)
    monkeypatch.setattr(
        m,
        "extract_intent",
        lambda *a, **k: ({"intent": "smalltalk", "slots": {}}, {"total_time_s": 0.0, "attempts": 1}),
    )

    async def go():
        session = m.CallSession(FakeWS())
        session.booking = booking
        try:
            await m._resolve_intent_uncached(session, "জয়ন্ত", "bn", "জয়ন্ত")
            await asyncio.sleep(0.2)  # the cache write runs in the background
        finally:
            session.cleanup()

    asyncio.run(go())
    return cache


def test_the_cache_is_not_used_while_a_booking_waits_for_the_name(m, monkeypatch):  # noqa: F811
    cache = run_resolve(m, monkeypatch, waiting_for_name())
    assert cache.gets == [] and cache.puts == []


def test_the_cache_is_not_used_while_the_age_or_address_is_asked(m, monkeypatch):  # noqa: F811
    st = waiting_for_name(patient_name="জয়ন্ত")
    st.asked_fields.add("patient_age")
    cache = run_resolve(m, monkeypatch, st)
    assert cache.gets == [] and cache.puts == []


def test_the_cache_is_used_as_before_otherwise(m, monkeypatch):  # noqa: F811
    cache = run_resolve(m, monkeypatch, None)
    assert cache.gets == ["জয়ন্ত"] and cache.puts == ["জয়ন্ত"]
    done = waiting_for_name(patient_name="জয়ন্ত", patient_age=25)
    done.asked_fields.update({"patient_age"})
    cache = run_resolve(m, monkeypatch, done)
    assert cache.gets == ["জয়ন্ত"]  # everything asked has been answered: back to normal


def test_the_answers_a_booking_detail_helper_reads_the_session(m):  # noqa: F811
    session = m.CallSession(FakeWS())
    assert m._answers_a_booking_detail(session, "bn") is False
    session.booking = waiting_for_name()
    assert m._answers_a_booking_detail(session, "bn") is True
    session.cleanup()
    assert isinstance(types.SimpleNamespace(), object)


# ------------------------------------------------------------------------- the WhatsApp answer (call ac3534a5)


def asked_whatsapp():
    st = new_state("book_appointment")
    st.stage = "collecting"
    st.slots.update(
        {
            "doctor_name": "Jaydeep Sanyal",
            "date": "2026-11-04",
            "time_slot": "17:00",
            "phone": "9876543210",
            "_wa_asked": "1",
        }
    )
    return st


@pytest.mark.parametrize("said", ["হ্যাঁ আছে", "হ্যাঁ", "বললাম হ্যাঁ আছে", "yes", "হ্যা আছে"])
def test_a_clear_yes_to_the_whatsapp_question_is_settled_by_the_words(said):
    """The confidence gate must not withhold it (main reads readback_answer), or the question counts as answered while the next one is never asked."""
    st = asked_whatsapp()
    plan = bc.before_model(st, said, "bn", agreement=0.33)
    assert plan.skip_model and plan.readback_answer, said
    assert st.slots.get("_wa_done") == "1"


def test_a_no_or_an_unclear_answer_is_not_exempt_from_the_gate():
    unclear = asked_whatsapp()
    plan = bc.before_model(unclear, "আমি ভাবছি", "bn", agreement=0.33)
    assert not plan.readback_answer and plan.speak  # asked again, not settled
    no = asked_whatsapp()
    plan = bc.before_model(no, "না", "bn", agreement=1.0)
    assert not plan.readback_answer and plan.speak  # "which number does have WhatsApp?" is spoken by the booking itself
    second_miss = asked_whatsapp()
    second_miss.slots["_wa_tries"] = 1
    plan = bc.before_model(second_miss, "আমি ভাবছি", "bn", agreement=0.33)
    assert (
        plan.skip_model and not plan.readback_answer
    )  # moved on after the second miss, but not by a yes the words settle
