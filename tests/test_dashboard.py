"""The call dashboard (dashboard/): reading the agent's journal and log, the labels, privacy, the store and the web server.

It uses made-up calls in the agent's real file formats (dashboard/demo.py). Nothing here touches the voice agent."""

import datetime
import json
import os
import sys
import threading
import urllib.error
import urllib.request

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from dashboard import classify, demo, ingest, journal, logparse, server  # noqa: E402
from dashboard.store import Store, clinic_today  # noqa: E402


def _ev(seq, kind, /, **payload):
    return {"seq": seq, "kind": kind, "payload": payload}


def _cfg(tmp_path, **over):
    import dataclasses

    return dataclasses.replace(demo.write_demo(str(tmp_path)), **over)


# ------------------------------------------------------------------ the log


def test_heard_line_gives_the_text_language_and_agreement():
    line = (
        "2026-11-02 10:15:03,120 INFO main_pcm: [4f2a9c01] heard (bn, rnnt, agreement 0.82): 'আমার সিবিসি টেস্টের দাম কত'"
    )
    ev = logparse.parse_line(line)
    assert ev.call_id == "4f2a9c01" and ev.kind == "heard" and ev.day == "2026-11-02"
    assert ev.data == {"lang": "bn", "decoder": "rnnt", "agreement": 0.82, "text": "আমার সিবিসি টেস্টের দাম কত"}


def test_heard_text_with_quotes_is_given_back_whole():
    line = '2026-11-02 10:15:03,120 INFO main_pcm: [4f2a9c01] heard (en, rnnt, agreement 1.00): "it\'s the doctor"'
    assert logparse.parse_line(line).data["text"] == "it's the doctor"


def test_text_is_not_kept_when_told_not_to():
    line = "2026-11-02 10:15:03,120 INFO main_pcm: [4f2a9c01] heard (bn, rnnt, agreement 0.82): 'secret'"
    assert "text" not in logparse.parse_line(line, keep_text=False).data


@pytest.mark.parametrize(
    "line",
    [
        "2026-11-02 10:15:03,120 INFO httpx: HTTP Request: GET http://127.0.0.1:8080/api/health",
        "Traceback (most recent call last):",
        "2026-11-02 10:15:03,120 INFO main_pcm: [4f2a9c01] a message this dashboard does not use",
        "",
    ],
)
def test_other_lines_are_ignored(line):
    assert logparse.parse_line(line) is None


def test_handoff_and_score_lines():
    h = logparse.parse_line(
        "2026-11-02 10:16:00,001 WARNING main_pcm: [4f2a9c01] handoff to human: clinical_interpretation"
    )
    assert (h.kind, h.data["value"]) == ("handoff", "clinical_interpretation")
    s = logparse.parse_line("2026-11-02 10:16:01,001 INFO main_pcm: [4f2a9c01] call score: 72 (neutral) corrections -4")
    assert s.data == {"score": 72, "band": "neutral"}
    n = logparse.parse_line("2026-11-02 10:16:01,001 INFO main_pcm: [4f2a9c01] call score: None (unscored) too_short")
    assert n.data["score"] is None


def test_reading_waits_for_a_whole_line_and_restarts_after_a_truncation(tmp_path):
    p = tmp_path / "agent.log"
    a = "2026-11-02 10:00:00,000 INFO m: [aaaa1111] call started (1 active)\n"
    b = "2026-11-02 10:00:05,000 INFO m: [aaaa1111] ASR returned empty text\n"
    p.write_text(a + b[:20], encoding="utf-8")
    evs, inode, off, head = logparse.read_new(str(p), 0, 0, "")
    assert [e.kind for e in evs] == ["start"]
    p.write_text(a + b, encoding="utf-8")
    evs, inode, off, head = logparse.read_new(str(p), inode, off, head)
    assert [e.kind for e in evs] == ["empty"]
    p.write_text(
        "2026-11-02 11:00:00,000 INFO m: [bbbb2222] call started (1 active)\n", encoding="utf-8"
    )  # the deploy script empties the log at a restart
    evs, inode, off, head = logparse.read_new(str(p), inode, off, head)
    assert [(e.call_id, e.kind) for e in evs] == [("bbbb2222", "start")]


# ------------------------------------------------------------------ the labels


def _summary(events, finished=True):
    return journal.summarise("c0000001", events, "9000012345", finished)


def test_a_booking_confirmed_after_an_enquiry_is_counted_as_that():
    ev = [
        _ev(1, "start", channel="voice"),
        _ev(2, "language", language="bn"),
        _ev(3, "intent", intent="doctor_availability"),
        _ev(4, "intent", intent="book_appointment"),
        _ev(5, "action", name="booking_confirmed", ref="KCD-1"),
        _ev(6, "end", outcome="completed"),
    ]
    lab = classify.classify(_summary(ev))
    assert (lab.category, lab.booking_origin, lab.booking_confirmed) == ("booked", "after_enquiry", True)


def test_a_booking_asked_for_first_is_requested():
    ev = [
        _ev(1, "intent", intent="smalltalk"),
        _ev(2, "intent", intent="book_appointment"),
        _ev(3, "end", outcome="completed"),
    ]
    lab = classify.classify(_summary(ev))
    assert lab.booking_origin == "requested" and lab.booking_confirmed is False


def test_a_hangup_during_a_booking_is_a_drop_with_that_cause():
    ev = [
        _ev(1, "intent", intent="book_appointment"),
        _ev(2, "satisfaction", score=53, band="unhappy", signals={"left_mid_task": True}),
        _ev(3, "end", outcome="completed"),
    ]
    lab = classify.classify(_summary(ev))
    assert (lab.category, lab.drop_cause) == ("dropped", "left_during_booking")
    assert "attention" in lab.tags


def test_silence_after_a_reask_is_a_drop_after_a_reask():
    ev = [
        _ev(1, "reask", kind="reask", reason="noisy", action="reask", lang="bn"),
        _ev(2, "end", outcome="silence_timeout"),
    ]
    lab = classify.classify(_summary(ev))
    assert lab.category == "dropped" and lab.reasks == 1 and "clarified" in lab.tags


@pytest.mark.parametrize(
    ("reason", "group"),
    [
        ("caller_requested", "caller_asked"),
        ("complaint", "caller_asked"),
        ("clinical_interpretation", "policy"),
        ("emergency", "policy"),
        ("audio_overrun", "system"),
        ("unintelligible:noisy", "system"),
    ],
)
def test_who_caused_a_transfer(reason, group):
    ev = [_ev(1, "escalation", reason=reason), _ev(2, "end", outcome="handed_off")]
    lab = classify.classify(_summary(ev))
    assert (lab.category, lab.transfer_reason, lab.transfer_group) == ("transferred", reason, group)


def test_a_correction_and_a_system_error_count_as_something_going_wrong():
    ev = [
        _ev(1, "reask", kind="system_failure", reason="tool_failure", lang="bn"),
        _ev(2, "satisfaction", score=66, band="neutral", signals={"corrections": 1, "language_flips": 1}),
        _ev(3, "end", outcome="completed"),
    ]
    lab = classify.classify(_summary(ev))
    assert set(lab.wrong_signals) == {"correction_at_readback", "language_put_right", "system_error_heard"}
    assert "said_wrong" in lab.tags


def test_a_call_without_an_end_is_live():
    assert classify.classify(_summary([_ev(1, "intent", intent="test_rate")], finished=False)).category == "live"


# ------------------------------------------------------------------ privacy


def test_confirmed_values_and_the_phone_never_reach_the_summary():
    ev = [
        _ev(
            1,
            "confirmed",
            slots={"patient_name": "রহিম শেখ", "phone": "9000012345", "doctor_name": "Dr. B. Sen", "date": ""},
        ),
        _ev(2, "end", outcome="completed"),
    ]
    s = journal.summarise("c0000001", ev, "9000012345")
    blob = json.dumps(s.timeline, ensure_ascii=False) + s.last4
    assert "রহিম" not in blob and "9000012345" not in blob
    assert s.timeline[0]["fields"] == ["doctor_name", "patient_name", "phone"]
    assert s.last4 == "2345"


def test_the_call_table_holds_no_phone_number_or_patient_name(tmp_path):
    """The journal carries the caller's phone and the confirmed values; the `calls` table, built from it, must carry neither. (A transcript is different
    on purpose: it is what the caller said, so it holds whatever they said, and it is deleted after `transcript_days`.)"""
    import sqlite3

    cfg = _cfg(tmp_path)
    store = Store(cfg.db_path)
    ingest.ingest_once(cfg, store)
    rows = repr(sqlite3.connect(cfg.db_path).execute("SELECT * FROM calls").fetchall())
    assert "9000012345" not in rows and "রহিম শেখ" not in rows


# ------------------------------------------------------------------ store and ingest


def test_ingest_reads_the_journal_and_log_and_a_second_pass_changes_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    store = Store(cfg.db_path)
    first = ingest.ingest_once(cfg, store)
    assert first["calls"] > 0 and first["log_events"] > 0 and first["live"] == 2
    second = ingest.ingest_once(cfg, store)
    assert second["calls"] == 0 and second["log_events"] == 0
    s = store.summary(2, "", clinic_today())
    assert s["calls"] == first["calls"] + 2
    assert sum(s["categories"].values()) == s["calls"]
    assert s["categories"]["live"] == 2
    assert s["booking"]["confirmed"] >= 1 and s["transferred"]["total"] >= 1 and s["dropped"]["total"] >= 1


def test_the_same_call_id_on_two_days_is_two_calls(tmp_path):
    store = Store(str(tmp_path / "d.db"))
    s = journal.summarise("deadbeef", [_ev(1, "end", outcome="completed")])
    store.save_call("2026-11-01", s)
    store.save_call("2026-11-02", s)
    assert len(store.list_calls(30, "", "", 100, "2026-11-02")) == 2


def test_opening_a_call_gives_its_transcript_and_its_events(tmp_path):
    cfg = _cfg(tmp_path)
    store = Store(cfg.db_path)
    ingest.ingest_once(cfg, store)
    transferred = store.list_calls(2, "", "transferred", 5, clinic_today())[0]
    d = store.call_detail(transferred["day"], transferred["call_id"])
    assert any(t["kind"] == "heard" and t["text"] for t in d["log"])
    assert any(e["kind"] == "escalation" for e in d["summary"]["timeline"])
    assert d["labels"]["category"] == "transferred"


def test_transcripts_are_not_stored_when_switched_off(tmp_path):
    cfg = _cfg(tmp_path, keep_transcripts=False)
    store = Store(cfg.db_path)
    ingest.ingest_once(cfg, store)
    c = store.list_calls(2, "", "attention", 50, clinic_today())[0]
    assert all("text" not in t for t in store.call_detail(c["day"], c["call_id"])["log"])


def test_a_log_restart_does_not_lose_the_history(tmp_path):
    cfg = _cfg(tmp_path)
    store = Store(cfg.db_path)
    ingest.ingest_once(cfg, store)
    before = store.summary(2, "", clinic_today())["calls"]
    open(cfg.log_files[0], "w", encoding="utf-8").close()  # `> logfile` at a restart
    ingest.ingest_once(cfg, store)
    assert store.summary(2, "", clinic_today())["calls"] == before
    c = store.list_calls(2, "", "transferred", 1, clinic_today())[0]
    assert store.call_detail(c["day"], c["call_id"])["log"]  # the transcript is still there


def test_old_transcripts_are_deleted(tmp_path):
    cfg = _cfg(tmp_path, transcript_days=0)
    store = Store(cfg.db_path)
    ingest.ingest_once(cfg, store)
    y = (datetime.date.fromisoformat(clinic_today()) - datetime.timedelta(days=1)).isoformat()
    c = [x for x in store.list_calls(2, "", "transferred", 50, clinic_today()) if x["day"] == y][0]
    assert store.call_detail(y, c["call_id"])["log"] == []


# ------------------------------------------------------------------ the web server


def _serve(cfg, store):
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(cfg, store))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_the_api_serves_the_page_the_summary_and_a_call(tmp_path):
    cfg = _cfg(tmp_path)
    store = Store(cfg.db_path)
    ingest.ingest_once(cfg, store)
    httpd, base = _serve(cfg, store)
    try:
        code, body = _get(base + "/")
        assert code == 200 and b"Call dashboard" in body
        code, body = _get(base + "/api/summary?days=2")
        assert code == 200 and json.loads(body)["calls"] > 0
        code, body = _get(base + "/api/calls?days=2&tag=attention&limit=3")
        calls = json.loads(body)["calls"]
        assert code == 200 and 0 < len(calls) <= 3
        code, body = _get(f"{base}/api/call?day={calls[0]['day']}&id={calls[0]['call_id']}")
        assert code == 200 and json.loads(body)["call_id"] == calls[0]["call_id"]
        assert _get(base + "/api/call?day=nope&id=x")[0] == 400
        assert _get(base + "/api/calls?tag=drop%20table")[0] == 400
        assert _get(base + "/api/call?day=2000-01-01&id=ffffffff")[0] == 404
    finally:
        httpd.shutdown()


def test_a_password_is_asked_for_when_one_is_set(tmp_path):
    cfg = _cfg(tmp_path, user="ops", password="s3cret")
    store = Store(cfg.db_path)
    httpd, base = _serve(cfg, store)
    try:
        assert _get(base + "/api/summary")[0] == 401
        import base64

        good = {"Authorization": "Basic " + base64.b64encode(b"ops:s3cret").decode()}
        bad = {"Authorization": "Basic " + base64.b64encode(b"ops:wrong").decode()}
        assert _get(base + "/api/summary", good)[0] == 200
        assert _get(base + "/api/summary", bad)[0] == 401
    finally:
        httpd.shutdown()


def test_it_will_not_listen_on_a_public_address_without_a_password(tmp_path):
    cfg = _cfg(tmp_path, host="0.0.0.0")
    with pytest.raises(SystemExit):
        server.serve(cfg, Store(cfg.db_path))


def test_the_page_sets_text_only_through_textcontent():
    page = open(os.path.join(REPO_ROOT, "dashboard", "static", "index.html"), encoding="utf-8").read()
    assert "innerHTML" not in page and "document.write" not in page and "eval(" not in page


# ------------------------------------------------------------------ the integration with the live page and the pod


def _read(*parts):
    return open(os.path.join(REPO_ROOT, *parts), encoding="utf-8").read()


def test_the_dashboard_page_asks_for_its_data_with_relative_urls():
    """Behind the gateway the page is at /dashboard/, so "/api/..." would reach the voice agent's own API instead of the dashboard."""
    page = _read("dashboard", "static", "index.html")
    assert '"/api/' not in page and '"api/summary' in page and '"api/call' in page


@pytest.mark.parametrize("path", [("static", "pcm", "index.html"), ("static", "index.html")])
def test_both_live_pages_link_to_the_dashboard(path):
    page = _read(*path)
    assert 'href="dashboard/"' in page and "Call dashboard" in page


def test_the_gateway_routes_the_dashboard_behind_the_login_and_the_pod_starts_it():
    import re

    conf = _read("deploy", "gateway", "nginx.conf")
    server = conf[conf.index("server {") :]
    assert "proxy_pass http://127.0.0.1:8890/;" in server
    block = server[server.index("location /dashboard/") : server.index("location / {")]
    assert "auth_basic off" not in block  # only /twilio/ is open; the dashboard shows what callers said
    start = _read("deploy", "start_all.sh")
    assert re.search(r"start\s+dashboard\s+8890\s+/workspace/logs/dashboard\.log", start)
    assert "-m dashboard" in start


def test_archived_logs_are_read_through_a_glob_pattern(tmp_path):
    """The deploy scripts keep the log of each run in logs/archive/<time>/; a restart empties the live log, so the past transcripts live there."""
    cfg = _cfg(tmp_path)
    archive = tmp_path / "logs" / "archive" / "20261101-050148"
    archive.mkdir(parents=True)
    live = open(cfg.log_files[0], encoding="utf-8").read()
    (archive / "pcm_app.log").write_text(live, encoding="utf-8")
    open(cfg.log_files[0], "w", encoding="utf-8").close()  # the live log was emptied by the restart
    import dataclasses

    cfg = dataclasses.replace(
        cfg, log_files=(cfg.log_files[0], str(tmp_path / "logs" / "archive" / "*" / "pcm_app.log"))
    )
    store = Store(cfg.db_path)
    first = ingest.ingest_once(cfg, store)
    assert first["log_events"] > 0
    c = store.list_calls(2, "", "transferred", 1, clinic_today())[0]
    assert any(t["kind"] == "heard" for t in store.call_detail(c["day"], c["call_id"])["log"])
    assert ingest.ingest_once(cfg, store)["log_events"] == 0  # an archived log is read once
