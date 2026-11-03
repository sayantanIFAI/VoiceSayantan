"""What the agent says back is written to the log, so a call can be read as a conversation (main.py and main_pcm.py, `_speak`).

The line is `[call_id] said (<language>[, filler]): '<text>'`. The test pins the one property that matters: the logged text is exactly the text the
caller's page was sent, whatever the reply went through on the way (the single-question rule, the single-apology rule, date wording).

    python -m pytest tests/test_said_log.py -v
"""

import io
import json
import logging
import os
import sys
import wave

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _pod_stubs import pod_stubs  # noqa: E402

SR = 16000


class FakeWS:
    def __init__(self):
        self.texts = []

    async def send_text(self, t):
        self.texts.append(t)

    async def send_bytes(self, b):
        pass

    async def close(self):
        pass

    def spoken(self):
        return [d["text"] for d in (json.loads(t) for t in self.texts) if d.get("sender") == "AI"]


class FakeTTS:
    async def synthesize(self, lang, text, speed=1.0, prosody=None):
        b = io.BytesIO()
        with wave.open(b, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(b"\x00\x00" * (SR // 4))
        return b.getvalue()


@pytest.fixture(scope="module", params=["main_pcm", "main"])
def m(request):
    with pod_stubs(REPO_ROOT) as imp:
        yield imp(request.param)


def _session(m, monkeypatch):
    monkeypatch.setattr(m, "_admission", None)
    monkeypatch.setattr(m, "_tts_router", FakeTTS())
    session = m.CallSession(FakeWS())
    session.release_gate()
    session.turn_epoch = session.speak_epoch
    return session


def _said(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().split("] ", 1)[-1].startswith("said (")]


async def test_a_reply_is_logged_exactly_as_it_was_sent(m, monkeypatch, caplog):
    session = _session(m, monkeypatch)
    caplog.set_level(logging.INFO)
    await m._speak(session, "The CBC costs three hundred and fifty rupees.", "en")
    sent = session.ws.spoken()
    assert sent == ["The CBC costs three hundred and fifty rupees."]
    assert _said(caplog) == [f"[{session.call_id}] said (en): {sent[0]!r}"]


async def test_the_logged_text_is_the_final_text_after_the_wording_rules(m, monkeypatch, caplog):
    """An ISO date in a reply is reworded just before speaking (agent/date_phrase.py). The log must hold the words that were sent, not the ones handed in."""
    session = _session(m, monkeypatch)
    caplog.set_level(logging.INFO)
    handed_in = "Your appointment is on 2030-01-15."
    await m._speak(session, handed_in, "en")
    sent = session.ws.spoken()[-1]
    assert sent != handed_in and "2030-01-15" not in sent
    assert _said(caplog) == [f"[{session.call_id}] said (en): {sent!r}"]


async def test_a_please_hold_filler_is_marked_as_one(m, monkeypatch, caplog):
    session = _session(m, monkeypatch)
    session.speaking_filler = True
    caplog.set_level(logging.INFO)
    await m._speak(session, "Please hold.", "en")
    assert _said(caplog) == [f"[{session.call_id}] said (en, filler): 'Please hold.'"]


async def test_a_reply_dropped_after_an_interrupt_is_not_logged(m, monkeypatch, caplog):
    """A stale reply is discarded before anything is sent; the log must not claim the agent said it."""
    session = _session(m, monkeypatch)
    session.turn_epoch = session.speak_epoch - 1
    caplog.set_level(logging.INFO)
    await m._speak(session, "This was overtaken by the caller talking.", "en")
    assert session.ws.spoken() == [] and _said(caplog) == []


async def test_bengali_is_logged_as_written(m, monkeypatch, caplog):
    session = _session(m, monkeypatch)
    caplog.set_level(logging.INFO)
    await m._speak(session, "আমি আপনাকে কীভাবে সাহায্য করতে পারি।", "bn")
    assert _said(caplog) == [f"[{session.call_id}] said (bn): {session.ws.spoken()[0]!r}"]
