"""A plain name or age, said to the question that asks for it, is a whole answer: the speculative transcript calls it complete, so the end-of-speech wait is the short one (call 56a625cd: five name answers waited
1.6 s and three age / station answers 2.0 s). Only a shortening: anything that is not plainly such an answer keeps its wait.

    python -m pytest tests/test_answer_kind_verdict.py -v
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
from test_orchestrator_persona import ASRResult  # noqa: E402

from agent import booking_capture as bc  # noqa: E402
from agent.booking_flow import new_state  # noqa: E402

ASK_NAME = "আপনার নামটা বলবেন প্লিজ?"


def booking(**slots):
    st = new_state("book_appointment")
    st.stage = "collecting"
    st.slots.update(
        {
            "doctor_name": "Debasish Das",
            "date": "2026-11-06",
            "time_slot": "10:00",
            "phone": "9876543210",
            "_phone_ok": "9876543210",
            **slots,
        }
    )
    return st


def session_asking(m, said, st):  # noqa: F811
    session = m.CallSession(FakeWS())
    session.booking = st
    session.last_spoken = said
    return session


def test_the_question_just_asked_names_the_kind_of_answer(m):  # noqa: F811
    age_q = bc.prompt("ask_age", "bn")
    st = booking(patient_name="জয়ন্ত")
    assert m._expected_answer_kind(session_asking(m, age_q, st)) == "age"
    assert (
        m._expected_answer_kind(session_asking(m, f"আমি নামটা শুনেছি জয়ন্ত। {age_q}", st)) == "age"
    )  # the name read-back that asks the age
    assert m._expected_answer_kind(session_asking(m, bc.prompt("ps_ask", "bn"), st)) == "name"
    assert m._expected_answer_kind(session_asking(m, bc.prompt("ps_again", "bn"), st)) == "name"
    assert (
        m._expected_answer_kind(session_asking(m, ASK_NAME, booking())) == "name"
    )  # as before: the name is the next required detail
    assert (
        m._expected_answer_kind(session_asking(m, "ঠিকানাটা বলবেন?", st)) is None
    )  # an address can run long: its wait is not shortened or lengthened


@pytest.mark.parametrize(
    "kind, text, expected",
    [
        ("name", "জয়ন্ত", True),
        ("name", "শুভজিৎ গাঙ্গুলী", True),
        ("name", "আমার নাম রোহান আনসারি", True),
        ("name", "পাটুলি", True),
        ("name", "আচ্ছা", False),
        ("name", "কখন বসবে", False),
        ("name", "আমার ডেঙ্গু হয়েছে", False),
        ("name", "9876543210", False),
        ("age", "সাতাশ", True),
        ("age", "সাতাশ বছর", True),
        ("age", "27", True),
        ("age", "আমার বয়স সাতাশ বছর ছয় মাস সাত দিন", False),
        ("age", "জয়ন্ত", False),
        ("yes_no", "জয়ন্ত", False),
        (None, "সাতাশ", False),
    ],
)
def test_which_answers_are_whole(m, kind, text, expected):  # noqa: F811
    assert m._answer_completes(kind, text, "bn") is expected


def run_speculation(m, monkeypatch, said, st, heard, calls):  # noqa: F811
    class Router:
        async def transcribe(self, lang, path):
            return ASRResult(heard)

    async def slice_(session, start, end, seq):
        return "/tmp/none.wav"

    async def prepared(session, path):
        return path, []

    async def preempt(session, text, lang):
        calls.append(text)

    async def no_llm(text, lang):
        return None

    monkeypatch.setattr(m, "_asr_router", Router())
    monkeypatch.setattr(m, "_slice_utterance", slice_)
    monkeypatch.setattr(m, "_asr_input_wav", prepared)
    monkeypatch.setattr(m, "_preempt_intent", preempt)
    monkeypatch.setattr(m, "_llm_completeness", no_llm)

    async def go():
        session = session_asking(m, said, st)
        session.lang = "bn"
        try:
            verdict = await m._speculative_completeness(session, 7.5)
            await asyncio.sleep(0.05)  # the early intent call is scheduled in the background
            return verdict
        finally:
            session.cleanup()

    return asyncio.run(go())


def test_a_plain_name_to_the_name_question_is_complete_and_needs_no_early_model_call(m, monkeypatch):  # noqa: F811
    calls: list[str] = []
    assert run_speculation(m, monkeypatch, ASK_NAME, booking(), "জয়ন্ত", calls) == "complete"
    assert calls == []


def test_a_plain_age_to_the_age_question_is_complete(m, monkeypatch):  # noqa: F811
    calls: list[str] = []
    assert (
        run_speculation(m, monkeypatch, bc.prompt("ask_age", "bn"), booking(patient_name="জয়ন্ত"), "সাতাশ", calls)
        == "complete"
    )
    assert calls == []


def test_something_else_keeps_its_verdict_and_its_early_model_call(m, monkeypatch):  # noqa: F811
    calls: list[str] = []
    verdict = run_speculation(m, monkeypatch, ASK_NAME, booking(), "কাল কখন বসবে ডাক্তার", calls)
    assert verdict != "complete" and calls == ["কাল কখন বসবে ডাক্তার"]


def test_the_kill_file_switch_restores_the_old_verdict(m, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ANSWER_KIND_VERDICT", "0")
    calls: list[str] = []
    assert run_speculation(m, monkeypatch, ASK_NAME, booking(), "জয়ন্ত", calls) != "complete"
