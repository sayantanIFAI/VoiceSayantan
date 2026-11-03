"""The dashboard's speed view (dashboard/speed.py): reading the agent's timing lines, exact percentiles, the tiers, the live readings.

Made-up calls in the agent's real formats (dashboard/demo.py); nothing here touches the voice agent."""

import dataclasses
import json
import os
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from dashboard import demo, ingest, live, logparse, ollama_log, server, speed  # noqa: E402
from dashboard.logparse import LogEvent  # noqa: E402
from dashboard.store import Store, clinic_today  # noqa: E402


def _cfg(tmp_path, **over):
    return dataclasses.replace(demo.write_demo(str(tmp_path)), **over)


def _timing_line(
    call="4f2a9c01",
    stages="prep 12 ms | lid 190 ms | asr 240 ms | intent 18 ms | reply 40 ms | tts 210 ms | send 3 ms",
    total=713,
    api=" | clinic API 2 calls 61 ms",
):
    return f"2026-11-02 10:15:09,500 INFO main: [{call}] turn timing: {stages} | total {total} ms{api}"


# ------------------------------------------------------------------ the lines


def test_a_turn_timing_line_gives_every_stage_the_total_and_the_clinic_api_time():
    ev = logparse.parse_line(_timing_line())
    assert ev.kind == "timing" and ev.call_id == "4f2a9c01"
    assert ev.data == {
        "stages": {"prep": 12, "lid": 190, "asr": 240, "intent": 18, "reply": 40, "tts": 210, "send": 3},
        "total": 713,
        "api_calls": 2,
        "api_ms": 61,
    }


def test_a_turn_with_fewer_stages_is_read_as_it_is():
    """The agent marks a stage only when it happens; a turn with no speech synthesis has no tts stage."""
    ev = logparse.parse_line(_timing_line(stages="prep 12 ms | asr 240 ms", total=252, api=""))
    assert ev.data["stages"] == {"prep": 12, "asr": 240} and ev.data["api_calls"] == 0


def test_recogniser_times_and_tier_markers_are_read():
    base = "2026-11-02 10:15:08,100 INFO main: [4f2a9c01] "
    assert logparse.parse_line(base + "ASR timings: bn 420 ms | en 210 ms").data["engines"] == {"bn": 420, "en": 210}
    cases = {
        "intent cache L1 hit": "cache",
        "intent cache L2 hit (while the model was running)": "cache",
        "fast path resolved test_rate (0.91) -- no LLM call": "fast_path",
        "fast path test_rate refused (x) -- the model decides": "model",
        "sitting question read by rule -- no model call": "rule",
        "test named by rule (frame / spelled code) -> test_rate for 'x'": "rule",
    }
    for text, tier in cases.items():
        assert logparse.parse_line(base + text).data == {"tier": tier}, text
    assert logparse.parse_line(base + "intent cache L2 hit skipped: sentence names several tests") is None


def test_ollama_request_times_in_every_unit():
    def parse(dur, path="/api/generate"):
        return ollama_log.parse_line(
            f'[GIN] 2026/11/02 - 12:31:01 | 200 |  {dur} |       127.0.0.1 | POST     "{path}"'
        )

    assert (
        parse("311.9ms").ms == 311.9
        and parse("1.234s").ms == 1234.0
        and parse("1m3.5s").ms == 63500.0
        and parse("950µs").ms == 0.95
    )
    assert parse("20ms", "/api/embed").route == "embed" and parse("20ms", "/api/tags").route == "other"
    assert ollama_log.parse_line('time=2026-11-02T12:31:01.000+05:30 level=INFO msg="x"') is None


# ------------------------------------------------------------------ the arithmetic


def test_percentiles_are_nearest_rank_and_exact():
    d = speed.describe(list(range(1, 101)))
    assert (d["n"], d["p50"], d["p95"], d["p99"], d["max"]) == (100, 50, 95, 99, 100)
    assert speed.describe([7])["p95"] == 7
    d = speed.describe([10, 20, 30, 40])
    assert (d["p50"], d["p95"]) == (20, 40)  # the 2nd of 4 values, and the 4th
    assert speed.describe([]) is None


# ------------------------------------------------------------------ ingest and report


def _turns(store, day, call, totals, lang="bn", tier=None):
    events = [LogEvent(day, "10:00:00", call, "heard", {"lang": lang, "decoder": "rnnt", "agreement": 1.0})]
    for i, total in enumerate(totals):
        if tier:
            events.append(LogEvent(day, f"10:{i // 60:02d}:{i % 60:02d}", call, "tier", {"tier": tier}))
        events.append(
            LogEvent(
                day,
                f"10:{i // 60:02d}:{i % 60:02d}",
                call,
                "timing",
                {"stages": {"prep": 5, "tts": total - 5}, "total": total, "api_calls": 0, "api_ms": 0},
            )
        )
    store.add_log_events(events)


def test_the_report_gives_exact_percentiles_the_slow_share_and_the_slices(tmp_path):
    store = Store(str(tmp_path / "d.db"))
    today = clinic_today()
    _turns(store, today, "aaaa0001", [i * 20 for i in range(1, 101)], lang="bn", tier="model")  # 20 ... 2000 ms
    _turns(store, today, "bbbb0002", [100] * 10, lang="hi", tier="fast_path")
    r = store.latency(1, "", "", today)
    total = next(s for s in r["stages"] if s["stage"] == "total")
    assert total["n"] == 110 and total["max"] == 2000
    assert r["slow_share"] == round(25 / 110, 4)  # 1520 ... 2000 ms are the 25 turns slower than 1.5 s
    assert set(r["by_language"]) == {"bn", "hi"} and r["by_language"]["hi"]["total"]["p95"] == 100
    assert set(r["by_tier"]) == {"model", "fast_path"} and r["by_tier"]["fast_path"]["total"]["n"] == 10
    only_bn = store.latency(1, "bn", "", today)
    assert next(s for s in only_bn["stages"] if s["stage"] == "total")["p95"] == 1900
    only_model = store.latency(1, "", "model", today)
    assert next(s for s in only_model["stages"] if s["stage"] == "total")["n"] == 100


def test_a_tier_marker_belongs_to_the_next_timing_line_only(tmp_path):
    store = Store(str(tmp_path / "d.db"))
    today = clinic_today()
    events = [
        LogEvent(today, "10:00:00", "aaaa0001", "heard", {"lang": "bn"}),
        LogEvent(today, "10:00:01", "aaaa0001", "tier", {"tier": "cache"}),
        LogEvent(today, "10:00:02", "aaaa0001", "timing", {"stages": {"tts": 100}, "total": 100}),
        LogEvent(today, "10:00:10", "aaaa0001", "heard", {"lang": "en"}),
        LogEvent(today, "10:00:12", "aaaa0001", "timing", {"stages": {"tts": 200}, "total": 200}),
    ]
    store.add_log_events(events)
    rows = sqlite3.connect(store.path).execute("SELECT total, lang, tier FROM turn_timing ORDER BY total").fetchall()
    assert rows == [(100, "bn", "cache"), (200, "en", "other")]


def test_ingest_reads_timings_models_and_recognisers_once(tmp_path):
    cfg = _cfg(tmp_path)
    store = Store(cfg.db_path)
    first = ingest.ingest_once(cfg, store)
    assert first["ollama"] > 0
    db = sqlite3.connect(cfg.db_path)
    n_lines = open(cfg.log_files[0], encoding="utf-8").read().count("turn timing:")
    assert db.execute("SELECT COUNT(*) FROM turn_timing").fetchone()[0] == n_lines
    assert db.execute("SELECT COUNT(*) FROM turn_timing WHERE lang IS NULL").fetchone()[0] == 0
    # the stages of a turn add up to its total, as the agent's own line does
    assert (
        db.execute(
            "SELECT COUNT(*) FROM turn_timing WHERE COALESCE(prep,0)+COALESCE(lid,0)+COALESCE(asr,0)+COALESCE(intent,0)+COALESCE(reply,0)+COALESCE(tts,0)+COALESCE(send,0) != total"
        ).fetchone()[0]
        == 0
    )
    assert (
        db.execute("SELECT COUNT(*) FROM log_events WHERE kind IN ('timing','asr_engines','tier')").fetchone()[0] == 0
    )  # not part of the transcript
    second = ingest.ingest_once(cfg, store)
    assert second["ollama"] == 0 and second["log_events"] == 0
    assert db.execute("SELECT COUNT(*) FROM turn_timing").fetchone()[0] == n_lines
    r = store.latency(2, "", "", clinic_today())
    assert {e["engine"] for e in r["asr_engines"]} >= {"bn", "en"}
    assert {o["route"] for o in r["ollama"]} == {"generate", "embed"}


def test_the_slowest_turns_open_their_call(tmp_path):
    cfg = _cfg(tmp_path)
    store = Store(cfg.db_path)
    ingest.ingest_once(cfg, store)
    turns = store.slowest_turns(2, "", "", 5, clinic_today())
    assert [t["total"] for t in turns] == sorted((t["total"] for t in turns), reverse=True)
    assert all(t["slowest_stage"] in speed.STAGES for t in turns)
    t = turns[0]
    assert t["call_day"] and store.call_detail(t["call_day"], t["call_id"]) is not None


# ------------------------------------------------------------------ the per-call figures, and an older database


def test_the_calls_median_reply_time_comes_from_the_journal(tmp_path):
    cfg = _cfg(tmp_path)
    store = Store(cfg.db_path)
    ingest.ingest_once(cfg, store)
    r = store.latency(2, "", "", clinic_today())
    assert r["call_medians"]["n"] > 0 and r["call_medians"]["turns"] >= r["call_medians"]["n"]


def test_an_older_database_gains_the_new_columns_and_is_filled_by_reading_the_journals_again(tmp_path):
    cfg = _cfg(tmp_path)
    old = sqlite3.connect(cfg.db_path)
    old.executescript(
        """CREATE TABLE calls(day TEXT NOT NULL, call_id TEXT NOT NULL, live INTEGER NOT NULL DEFAULT 0, lang TEXT, channel TEXT, category TEXT,
        transfer_reason TEXT, transfer_group TEXT, drop_cause TEXT, reasks INTEGER, reask_reasons TEXT, booking_intent INTEGER, booking_origin TEXT,
        booking_confirmed INTEGER, booking_changed INTEGER, wrong TEXT, unhappy INTEGER, band TEXT, score INTEGER, tags TEXT, last4 TEXT, detail TEXT,
        PRIMARY KEY(day, call_id));
        INSERT INTO calls(day, call_id, category) VALUES ('2000-01-01', 'oldcall01', 'answered');"""
    )
    old.commit()
    old.close()
    store = Store(cfg.db_path)
    cols = {r[1] for r in sqlite3.connect(cfg.db_path).execute("PRAGMA table_info(calls)")}
    assert {"median_reply_ms", "slow_replies", "turns"} <= cols
    assert store.needs_calls_backfill()
    first = ingest.ingest_once(cfg, store)
    assert first["calls"] > 0 and not store.needs_calls_backfill()
    assert (
        sqlite3.connect(cfg.db_path)
        .execute("SELECT COUNT(*) FROM calls WHERE median_reply_ms IS NOT NULL")
        .fetchone()[0]
        > 0
    )
    assert (
        sqlite3.connect(cfg.db_path).execute("SELECT COUNT(*) FROM calls WHERE call_id='oldcall01'").fetchone()[0] == 1
    )  # nothing was lost
    assert ingest.ingest_once(cfg, store)["calls"] == 0


# ------------------------------------------------------------------ the running agent


class _Agent(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        bodies = {
            "/api/stats": {
                "turn_latency_by_language": {
                    "bn": {"samples": 40, "p50_s": 0.8, "p95_s": 1.9},
                    "hi": {"samples": 0, "p50_s": None, "p95_s": None},
                },
                "admission": {"turn_latency_p50_s": 0.9, "turn_latency_p95_s": 2.0, "active_calls": 3},
                "detector_budget": {"audio_quality": {"samples": 10, "p95_s": 0.2, "p50_s": 0.1}},
                "tts_cache": {"hit_rate": 0.4},
                "intent_cache": {"hit_rate": 0.1},
                "fast_path": {"serve_rate": 0.5},
            },
            "/api/health": {
                "ingress": {"event_loop_lag_ms_p95": 42.0, "event_loop_lag_ms_max": 90.0, "max_backlog_ms": 120.0}
            },
        }
        body = bodies.get(self.path)
        self.send_response(200 if body is not None else 404)
        self.end_headers()
        self.wfile.write(json.dumps(body or {}).encode())

    def log_message(self, *a):
        pass


def test_live_readings_come_from_the_agents_own_endpoints(tmp_path):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Agent)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        got = dict(live.readings(url))
        assert (
            got["first_audio_p95_s.bn"] == 1.9 and "first_audio_p95_s.hi" not in got
        )  # a language with no samples says nothing
        assert got["admission_p95_s"] == 2.0 and got["detector.audio_quality.p95_s"] == 0.2
        assert got["loop_lag_p95_ms"] == 42.0 and got["backlog_ms"] == 120.0 and got["tts_cache_hit_rate"] == 0.4
        cfg = _cfg(tmp_path, agent_urls=(url,))
        store = Store(cfg.db_path)
        assert ingest.ingest_once(cfg, store)["readings"] > 5
        lv = store.latency(1, "", "", clinic_today())["live"]
        assert lv["latest"][url.split("//")[1]]["first_audio_p95_s.bn"]["value"] == 1.9
    finally:
        httpd.shutdown()


def test_an_agent_that_does_not_answer_is_not_an_error(tmp_path):
    assert live.readings("http://127.0.0.1:1", timeout=0.5) == []
    cfg = _cfg(tmp_path, agent_urls=("http://127.0.0.1:1",))
    assert ingest.ingest_once(cfg, Store(cfg.db_path))["readings"] == 0


# ------------------------------------------------------------------ the web server and the page


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_the_latency_endpoints_and_the_script(tmp_path):
    cfg = _cfg(tmp_path)
    store = Store(cfg.db_path)
    ingest.ingest_once(cfg, store)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(cfg, store))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        code, body = _get(base + "/api/latency?days=2")
        d = json.loads(body)
        assert (
            code == 200
            and d["turns"] > 0
            and {s["stage"] for s in d["stages"]} >= {"lid", "asr", "intent", "tts", "total"}
        )
        assert json.loads(_get(base + "/api/latency?days=2&tier=model")[1])["turns"] < d["turns"]
        code, body = _get(base + "/api/latency/slow?days=2&limit=4")
        assert code == 200 and 0 < len(json.loads(body)["turns"]) <= 4
        assert _get(base + "/api/latency?tier=nonsense")[0] == 400 and _get(base + "/api/latency?lang=xx")[0] == 400
        code, body = _get(base + "/latency.js")
        assert code == 200 and b"loadSpeed" in body
        assert _get(base + "/static/../server.py")[0] == 404
    finally:
        httpd.shutdown()


def test_the_page_loads_the_speed_script_and_the_script_writes_text_only():
    page = open(os.path.join(REPO_ROOT, "dashboard", "static", "index.html"), encoding="utf-8").read()
    script = open(os.path.join(REPO_ROOT, "dashboard", "static", "latency.js"), encoding="utf-8").read()
    assert 'id="speedCard"' in page and 'src="latency.js"' in page and "loadSpeed" in page
    assert "innerHTML" not in script and "document.write" not in script and "eval(" not in script
    assert '"/api/' not in script and 'get("api/latency?' in script  # relative, so it works behind /dashboard/


@pytest.mark.parametrize("stage", speed.STAGES)
def test_every_stage_the_agent_marks_has_a_label(stage):
    assert stage in speed.STAGE_INFO
