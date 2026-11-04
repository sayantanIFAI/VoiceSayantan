"""The speculative transcript made during the silence wait stands in for the turn's own recognition when it read the same clip (main._usable_speculation, _asr_input_wav, the router's reuse).

    python -m pytest tests/test_speculative_reuse.py -v

What is asserted: the same audio preparation on both sides, a match only for the same stretch of the call, nothing reused when the caller kept talking, a switch that turns it off, and the recogniser not
being asked again for the language whose reading is reused.
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
from test_orchestrator_persona import ASRResult  # noqa: E402


def committed(start=10.0, end=13.2):
    return types.SimpleNamespace(call_id="t1", last_commit_start_abs=start, last_commit_end_abs=end)


def spec(start=10.0, end=13.2, lang="bn", text="কালকে সকাল এগারোটা"):
    return {"start": start, "end": end, "lang": lang, "result": ASRResult(text)}


@pytest.fixture(autouse=True)
def _switch_on(monkeypatch):
    monkeypatch.delenv("SPECULATIVE_REUSE", raising=False)


def test_the_same_stretch_is_used(m):  # noqa: F811
    s = spec()
    assert m._usable_speculation(committed(), s) is s
    assert m._usable_speculation(committed(end=13.3), s) is s  # the end moved a little with the voice detector: still the same words


def test_a_later_end_or_another_start_is_not_used(m):  # noqa: F811
    assert m._usable_speculation(committed(end=13.6), spec()) is None  # the caller kept talking after the speculation
    assert m._usable_speculation(committed(start=10.5), spec()) is None  # a different stretch of the call
    assert m._usable_speculation(committed(), None) is None
    assert m._usable_speculation(types.SimpleNamespace(call_id="t1"), spec()) is None  # no turn end recorded


def test_the_switch_turns_it_off(m, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("SPECULATIVE_REUSE", "0")
    assert m._usable_speculation(committed(), spec()) is None
    monkeypatch.delenv("SPECULATIVE_REUSE")
    kill = tmp_path / "off"
    kill.write_text("")
    real = m.os.path.exists
    monkeypatch.setattr(m.os.path, "exists", lambda p: True if p == "/workspace/.speculative_reuse_off" else real(p))
    assert m._usable_speculation(committed(), spec()) is None


def test_the_speculation_and_the_turn_prepare_the_audio_the_same_way(m, monkeypatch):  # noqa: F811
    attended = []

    def attend(path, level, f0):
        attended.append(path)
        return path + ".att"

    monkeypatch.setattr(m, "_attend_wav_to_path", attend)
    monkeypatch.setattr(m, "NEAR_END_ATTENTION", "on")
    monkeypatch.setattr(m, "CONDITION_INPUT", "off")
    session = types.SimpleNamespace(near_end=types.SimpleNamespace(established=True, level_dbfs=-30.0, f0_hz=180.0), noise_suppress=False)
    path, temps = asyncio.run(m._asr_input_wav(session, "/tmp/clip.wav"))
    assert path == "/tmp/clip.wav.att" and temps == ["/tmp/clip.wav.att"] and attended == ["/tmp/clip.wav"]
    session.near_end.established = False
    path, temps = asyncio.run(m._asr_input_wav(session, "/tmp/clip.wav"))
    assert path == "/tmp/clip.wav" and temps == []


def test_the_speculative_transcription_reads_the_prepared_audio_and_keeps_its_result(m, monkeypatch, tmp_path):  # noqa: F811
    read = []

    class Router:
        async def transcribe(self, lang, path):
            read.append((lang, path))
            return ASRResult("আপনার কত টাকা")

    async def slice_(session, start, end, seq):
        return str(tmp_path / "raw.wav")

    async def prepared(session, path):
        return path + ".att", []

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(m, "_asr_router", Router())
    monkeypatch.setattr(m, "_slice_utterance", slice_)
    monkeypatch.setattr(m, "_asr_input_wav", prepared)
    monkeypatch.setattr(m, "_preempt_intent", noop)
    monkeypatch.setattr(m, "_llm_completeness", noop)
    session = m.CallSession(FakeWS())
    session.processed_until_s = 4.0
    session.lang = "bn"
    asyncio.run(m._speculative_completeness(session, 7.5))
    assert read == [("bn", str(tmp_path / "raw.wav") + ".att")]
    kept = session.spec_asr
    assert kept["start"] == 4.0 and kept["end"] == 7.5 and kept["lang"] == "bn" and kept["result"].text == "আপনার কত টাকা"
    session.cleanup()


def test_the_router_does_not_read_the_clip_again_for_the_reused_language(m, monkeypatch):  # noqa: F811
    asked = []

    class Router:
        async def transcribe(self, lang, path):
            asked.append(lang)
            return ASRResult("english words", 0.1)

    class Lid:
        def identify_path(self, path):
            return m.LIDResult(language="bn", confidence=0.99, scores={"bn": 0.99, "en": 0.0, "hi": 0.01})

    monkeypatch.setattr(m, "_asr_router", Router())
    monkeypatch.setattr(m, "_lid", Lid())
    monkeypatch.setattr(m, "_languages_active", ["bn", "hi", "en"])
    session = m.CallSession(FakeWS())
    session.lang_router._previous_language = "bn"
    reused = ASRResult("কালকে সকাল এগারোটা")
    session.reuse_asr = {"start": 1.0, "end": 2.0, "lang": "bn", "result": reused}
    lang, result, _decisive = asyncio.run(m._route_and_transcribe_inner(session, "/tmp/x.wav"))
    assert "bn" not in asked  # the Bengali reading came from the speculation
    assert result is reused and lang == "bn"
    asked.clear()
    session.reuse_asr = None
    asyncio.run(m._route_and_transcribe_inner(session, "/tmp/x.wav"))
    assert "bn" in asked  # without a reusable reading the recogniser is asked as before
    session.cleanup()
