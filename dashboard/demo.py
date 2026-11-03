"""Made-up calls in the exact file formats the agent writes, so the dashboard can be seen working before it is pointed at a real pod.

Nothing here touches a real journal or log. `write_demo(folder)` writes a journal (today and yesterday, plus two calls in progress) and an agent
log, and returns a Config that points at them.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import random

from dashboard.config import Config
from dashboard.store import clinic_today

TEXTS = {
    "price": ["আমার সিবিসি টেস্টের দাম কত", "what is the price of uric acid test", "ইউরিক অ্যাসিড টেস্ট কত লাগবে"],
    "sitting": ["ডাক্তার বিশ্বজিৎ সেন কাল বসবেন কি", "आज डॉक्टर बैठेंगे क्या"],
    "book": ["ডাক্তার বিশ্বজিৎ সেনের অ্যাপয়েন্টমেন্ট নেব", "আমি একটা অ্যাপয়েন্টমেন্ট করতে চাই", "I want to book an appointment"],
    "detail": ["কালকে দশটায় করে দিন", "আমার নাম রহিম শেখ", "নয় শূন্য শূন্য শূন্য শূন্য এক দুই তিন চার পাঁচ"],
    "yes": ["হ্যাঁ", "ঠিক আছে"],
    "no": ["না না", "না, শুক্রবার"],
    "person": ["আমি একজন মানুষের সঙ্গে কথা বলতে চাই"],
    "result": ["আমার রিপোর্টের মানে কী, আমি কি ভালো আছি"],
    "noisy": ["আ আ করে", "ডাক্তার ... হলে"],
    "abuse": ["তোমরা সব বাজে"],
}


REPLIES = {  # made-up replies, one list per kind of caller turn
    "price": ["সিবিসি টেস্টের দাম চারশো টাকা। আর কিছু জানতে চান?", "The uric acid test costs one hundred and fifty rupees."],
    "sitting": ["ডাক্তার বিশ্বজিৎ সেন কাল সকাল দশটা থেকে বসবেন।", "डॉक्टर आज शाम चार बजे से बैठेंगे।"],
    "book": ["কোন তারিখে অ্যাপয়েন্টমেন্ট নিতে চান?", "Which day would you like the appointment?"],
    "detail": ["ধন্যবাদ। আপনার ফোন নম্বরটা বলবেন?", "ঠিক আছে। রোগীর নাম কী?"],
    "yes": ["আপনার বুকিং নিশ্চিত হয়েছে।"],
    "no": ["ঠিক আছে, কী পরিবর্তন করব?"],
    "person": ["আমি আপনাকে একজন সহকারীর সাথে যুক্ত করছি।"],
    "result": ["রিপোর্টের মানে ডাক্তারই বুঝিয়ে দেবেন; আমি আপনাকে একজনের সাথে যুক্ত করছি।"],
    "noisy": ["দুঃখিত, লাইনে শব্দ আছে। আরেকবার বলবেন?"],
    "abuse": ["আমি আপনাকে সাহায্য করতে চাই। অনুগ্রহ করে ভদ্রভাবে কথা বলুন।"],
}
FILLER = "একটু অপেক্ষা করুন।"


class _Maker:
    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)
        self.used: set[str] = set()

    def call_id(self) -> str:
        while True:
            cid = f"{self.rng.getrandbits(32):08x}"
            if cid not in self.used:
                self.used.add(cid)
                return cid


def _ev(events: list, kind: str, /, **payload) -> None:
    events.append({"seq": len(events) + 1, "kind": kind, "payload": payload})


def _turn_timing(r: random.Random, lang: str) -> dict:
    """One made-up turn's timing, shaped like the agent's: stages that add up to the total, a tier, the recognisers' own times, the model's time."""
    tier = r.choices(["fast_path", "cache", "rule", "model", "other"], weights=[34, 8, 6, 30, 22])[0]
    ln = lambda median, sigma: max(1, int(r.lognormvariate(math.log(median), sigma)))  # noqa: E731
    intent = {
        "fast_path": ln(15, 0.5),
        "cache": ln(8, 0.4),
        "rule": ln(5, 0.4),
        "model": ln(420, 0.45),
        "other": ln(25, 0.6),
    }[tier]
    tts_hit = r.random() < 0.2  # a clip the synthesiser had already made
    api_calls = r.choice([0, 1, 1, 2, 3]) if tier in ("fast_path", "model", "other") else 0
    api_ms = sum(ln(35, 0.5) for _ in range(api_calls))
    st = {
        "prep": ln(12, 0.4),
        "lid": ln(190, 0.22),
        "asr": ln(150, 0.6),
        "intent": intent,
        "reply": ln(30, 0.6) + api_ms,
        "tts": 8 if tts_hit else ln(230, 0.5),
        "send": ln(3, 0.4),
    }
    if r.random() < 0.04:  # a slow tail: one stage several times its usual time
        k = r.choice(["asr", "intent", "tts", "reply"])
        st[k] *= r.randint(3, 6)
    engines = {lang if lang in ("bn", "hi") else "bn": ln(300, 0.35), "en": ln(160, 0.35)}
    return {
        "tier": tier,
        "stages": st,
        "total": sum(st.values()),
        "api_calls": api_calls,
        "api_ms": api_ms,
        "engines": engines,
    }


def _scenario(kind: str, m: _Maker) -> tuple[list, list[tuple[str, float, dict]], str | None]:
    """(events, [(caller text, agreement, timing)], caller phone) for one kind of call."""
    ev: list = []
    turns: list[tuple[str, float, dict]] = []
    r = m.rng
    lang = r.choice(["bn", "bn", "bn", "hi", "en"])
    _ev(ev, "start", channel="voice", disclosure_version="v1")
    _ev(ev, "language", language=lang)

    def say(key: str, agree: float | None = None) -> None:
        timing = _turn_timing(r, lang)
        timing["reply"] = r.choice(REPLIES[key])  # what the agent said back, as it logs it
        timing["filler"] = timing["tier"] == "model" and r.random() < 0.3  # a "please hold" before a slow answer
        turns.append((r.choice(TEXTS[key]), agree if agree is not None else round(r.uniform(0.82, 1.0), 2), timing))

    sig = {
        "turns": 3,
        "answers_given": 0,
        "reasks": 0,
        "corrections": 0,
        "left_mid_task": False,
        "task_completed": False,
    }
    outcome, band, score = "completed", "happy", 84
    phone = "9000012345"
    if kind == "answered":
        say("price")
        _ev(ev, "intent", intent="test_rate")
        sig["answers_given"] = 1
    elif kind == "answered_sitting":
        say("sitting")
        _ev(ev, "intent", intent="doctor_availability")
        sig["answers_given"] = 1
    elif kind in ("booked_requested", "booked_after_enquiry", "booked_with_correction"):
        if kind == "booked_after_enquiry":
            say("sitting")
            _ev(ev, "intent", intent="doctor_availability")
        say("book")
        _ev(ev, "intent", intent="book_appointment")
        say("detail")
        _ev(ev, "intent", intent="book_appointment")
        if kind == "booked_with_correction":
            say("no")
            sig["corrections"] = 1
            band, score = "neutral", 72
        say("yes")
        _ev(
            ev,
            "confirmed",
            slots={
                "doctor_name": "Dr. B. Sen",
                "date": "2026-11-03",
                "time_slot": "10:00",
                "patient_name": "রহিম শেখ",
                "phone": phone,
            },
        )
        _ev(ev, "action", name="booking_confirmed", ref="KCD-" + str(r.randint(10000, 99999)))
        sig["task_completed"] = True
        sig["turns"] = 6
    elif kind == "dropped_in_booking":
        say("book")
        _ev(ev, "intent", intent="book_appointment")
        say("noisy", 0.31)
        _ev(ev, "reask", kind="reask", reason="noisy", action="reask", lang=lang)
        sig.update(left_mid_task=True, reasks=1)
        band, score = "unhappy", 53
    elif kind == "dropped_silence":
        say("price")
        _ev(ev, "intent", intent="test_rate")
        outcome, band, score = "silence_timeout", "neutral", 65
        sig["answers_given"] = 1
    elif kind == "dropped_after_reask":
        say("noisy", 0.28)
        _ev(ev, "reask", kind="reask", reason="noisy", action="reask", lang=lang)
        outcome, band, score = "silence_timeout", "unhappy", 56
        sig["reasks"] = 1
    elif kind == "transfer_caller_asked":
        say("person")
        _ev(ev, "escalation", reason="caller_requested")
        outcome, band, score = "handed_off", "neutral", 61
        sig["asked_for_person"] = True
    elif kind == "transfer_clinical":
        say("result")
        _ev(ev, "escalation", reason="clinical_interpretation")
        outcome, band, score = "handed_off", "neutral", 70
    elif kind == "transfer_unintelligible":
        say("noisy", 0.22)
        _ev(ev, "reask", kind="reask", reason="noisy", action="reask", lang=lang)
        say("noisy", 0.19)
        _ev(ev, "reask", kind="reask", reason="noisy", action="reask", lang=lang)
        say("noisy", 0.2)
        _ev(ev, "reask", kind="reask", reason="noisy", action="handoff", lang=lang)
        _ev(ev, "escalation", reason="unintelligible:noisy")
        outcome, band, score = "handed_off", "unhappy", 48
        sig.update(reasks=3, system_handoff=True)
    elif kind == "abusive":
        say("abuse")
        outcome, band, score = "abusive_caller", "unhappy", 44
    elif kind == "system_error":
        say("price")
        _ev(ev, "intent", intent="test_rate")
        _ev(ev, "reask", kind="system_failure", reason="tool_failure", lang=lang)
        sig["system_failures"] = 1
        band, score = "neutral", 66
    else:
        raise ValueError(kind)
    totals = sorted(t[2]["total"] for t in turns)
    if totals:
        sig.update(
            median_reply_ms=totals[len(totals) // 2], slow_replies=sum(1 for x in totals if x > 1500), turns=len(totals)
        )
    _ev(ev, "satisfaction", score=score, band=band, reasons=[], version="implicit-v1", basis="behaviour", signals=sig)
    _ev(ev, "end", outcome=outcome)
    return ev, turns, phone


MIX = (
    ["answered"] * 22
    + ["answered_sitting"] * 10
    + ["booked_requested"] * 12
    + ["booked_after_enquiry"] * 5
    + ["booked_with_correction"] * 4
    + ["dropped_in_booking"] * 5
    + ["dropped_silence"] * 3
    + ["dropped_after_reask"] * 3
    + ["transfer_caller_asked"] * 4
    + ["transfer_clinical"] * 3
    + ["transfer_unintelligible"] * 2
    + ["abusive"]
    + ["system_error"] * 2
)


def _stamp(day: str, hh: int, mm: int, sec: int) -> str:
    return f"{day} {hh % 24:02d}:{mm % 60:02d}:{sec % 60:02d},120"


def write_demo(root: str, per_day: int = 0, seed: int = 7) -> Config:
    m = _Maker(seed)
    journal = os.path.join(root, "journal")
    os.makedirs(os.path.join(journal, "inflight"), exist_ok=True)
    log_path = os.path.join(root, "agent.log")
    today = datetime.date.fromisoformat(clinic_today())
    log_lines: list[str] = []
    ollama_lines: list[str] = []
    for back in (1, 0):
        day = (today - datetime.timedelta(days=back)).isoformat()
        kinds = list(MIX)
        m.rng.shuffle(kinds)
        if per_day:
            kinds = kinds[:per_day]
        lines = []
        for n, kind in enumerate(kinds):
            cid = m.call_id()
            events, turns, phone = _scenario(kind, m)
            lines.append(json.dumps({"call_id": cid, "caller_phone": phone, "events": events}, ensure_ascii=False))
            minute = 8 * 60 + n * 3
            hh, mm = divmod(minute, 60)
            log_lines.append(f"{_stamp(day, hh, mm, 0)} INFO main_pcm: [{cid}] call started (4 active)")
            for i, (text, agree, tm) in enumerate(turns):
                lang = next((e["payload"]["language"] for e in events if e["kind"] == "language"), "bn")
                t0 = 5 + i * 9
                # the order the agent logs a turn in: the recognisers' times, what was heard, the tier marker, what was said, the turn's timing
                log_lines.append(
                    f"{_stamp(day, hh, mm, t0)} INFO main_pcm: [{cid}] ASR timings: "
                    + " | ".join(f"{k} {v} ms" for k, v in tm["engines"].items())
                )
                log_lines.append(
                    f"{_stamp(day, hh, mm, t0)} INFO main_pcm: [{cid}] heard ({lang}, rnnt, agreement {agree:.2f}): {text!r}"
                )
                marker = {
                    "cache": "intent cache L1 hit",
                    "fast_path": "fast path resolved test_rate (0.91) -- no LLM call",
                    "rule": "sitting question read by rule -- no model call",
                    "model": "fast path test_rate refused (below the commit floor) -- the model decides",
                }.get(tm["tier"])
                if marker:
                    log_lines.append(f"{_stamp(day, hh, mm, t0 + 1)} INFO main_pcm: [{cid}] {marker}")
                if tm.get("filler"):
                    log_lines.append(
                        f"{_stamp(day, hh, mm, t0 + 1)} INFO main_pcm: [{cid}] said ({lang}, filler): {FILLER!r}"
                    )
                log_lines.append(f"{_stamp(day, hh, mm, t0 + 2)} INFO main_pcm: [{cid}] said ({lang}): {tm['reply']!r}")
                parts = " | ".join(f"{k} {v} ms" for k, v in tm["stages"].items())
                log_lines.append(
                    f"{_stamp(day, hh, mm, t0 + 3)} INFO main_pcm: [{cid}] turn timing: {parts} | total {tm['total']} ms"
                    f" | clinic API {tm['api_calls']} calls {tm['api_ms']} ms"
                )
                gin = f"{day.replace('-', '/')} - {hh % 24:02d}:{mm % 60:02d}:{(t0 + 1) % 60:02d}"
                ollama_lines.append(
                    f'[GIN] {gin} | 200 | {m.rng.uniform(18, 60):.1f}ms |       127.0.0.1 | POST     "/api/embed"'
                )
                if tm["tier"] == "model":
                    ollama_lines.append(
                        f'[GIN] {gin} | 200 | {tm["stages"]["intent"] + 0.4:.1f}ms |       127.0.0.1 | POST     "/api/generate"'
                    )
            if any(e["payload"].get("action") == "handoff" or e["kind"] == "escalation" for e in events):
                reason = next(e["payload"]["reason"] for e in events if e["kind"] == "escalation")
                log_lines.append(f"{_stamp(day, hh, mm, 40)} WARNING main_pcm: [{cid}] handoff to human: {reason}")
            log_lines.append(f"{_stamp(day, hh, mm, 50)} INFO main_pcm: [{cid}] call ended (3 active)")
            log_lines.append(
                f"{day} {hh % 24:02d}:{mm % 60:02d}:51,001 INFO httpx: HTTP Request: GET http://127.0.0.1:8080/api/health"
            )
        with open(os.path.join(journal, day + ".jsonl"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    for kind in ("dropped_in_booking", "answered"):  # two calls in progress
        cid = m.call_id()
        events, _turns, _phone = _scenario(kind, m)
        with open(os.path.join(journal, "inflight", cid + ".jsonl"), "w", encoding="utf-8") as f:
            f.write(
                "\n".join(json.dumps(e, ensure_ascii=False) for e in events if e["kind"] not in ("end", "satisfaction"))
                + "\n"
            )
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n")
    ollama_path = os.path.join(root, "ollama.log")
    with open(ollama_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ollama_lines) + "\n")
    return Config(
        journal_dir=journal,
        archive_dir=os.path.join(root, "archive"),
        log_files=(log_path,),
        db_path=os.path.join(root, "dashboard.db"),
        host="127.0.0.1",
        port=8890,
        user="",
        password="",
        poll_s=10.0,
        keep_transcripts=True,
        transcript_days=30,
        ollama_logs=(ollama_path,),
        agent_urls=(),
        speed_days=90,
    )
