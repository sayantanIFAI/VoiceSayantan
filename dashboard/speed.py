"""Latency: p50 / p95 / p99 of every step the agent already times, stored per turn so any window or slice can be answered exactly.

Where each number comes from (all of it already exists; nothing in the agent is changed):

  turn timing:   the agent's log line for each turn, the time from "the turn started" to "the first audio left", stage by stage
                 (prep, lid, asr, intent, reply, tts, send, total) plus the clinic-API calls made during the turn.
                 The stages are consecutive slices of that one path, so their p95s do not add up to the total's p95.
  ASR timings:   how long each recogniser (bn / hi / en) took on a clip. They start together with language ID, so the turn's `asr` slice is
                 only the wait AFTER language ID finished, not the recogniser's whole time. This one is the whole time.
  Ollama log:    the model server's own time for each request: the intent model (/api/generate) and the cache's embedding model (/api/embed).
  call journal:  per call, the median first-audio time and how many replies were slower than 1.5 s (the call score's own signals).
  /api/stats, /api/health of the running agent: its own per-language window, event-loop lag and ingress backlog, read every poll.

What is NOT measured, and is said so on the page: the wait before a turn starts (end-of-speech detection), the time on the line and in the
caller's speaker, the TTS server's queue versus its synthesis, and the model's time inside one particular turn.
"""

from __future__ import annotations

import datetime
import math
from collections import defaultdict
from contextlib import closing

STAGES = ("prep", "lid", "asr", "intent", "reply", "tts", "send")
STAGE_INFO = {
    "prep": ("Noise clean-up and level check", "turn pipeline"),
    "lid": ("Language ID (CPU)", "turn pipeline"),
    "asr": ("Speech recognition, after language ID finished", "turn pipeline"),
    "intent": ("Understanding: rules, cache, fast path or the model", "turn pipeline"),
    "reply": ("Lookups and wording of the reply", "turn pipeline"),
    "tts": ("Speech synthesis of the first clause", "turn pipeline"),
    "send": ("Handing the audio to the line", "turn pipeline"),
    "total": ("Turn start to first audio", "turn pipeline"),
}
# numbers the code itself uses: the owner's target for first audio, the call score's "slow reply", the "please hold" filler
TARGET_MS = 500
SLOW_MS = 1500
FILLER_MS = 1000
# waits that are built into turn-taking and happen BEFORE a turn starts; these are the defaults in main.py / agent/endpointing.py, and the pod's
# environment can set others (deploy/env.sh), so they are shown as configuration, not as a measurement
CONFIGURED_WAITS = (
    ("Silence after a bare yes/no or a whole phone number", 0.45, "ENDPOINT_CERTAIN_S"),
    ("Silence after a finished-looking sentence", 1.2, "ENDPOINT_COMPLETE_S"),
    ("Silence otherwise", 2.0, "TURN_SILENCE_CONFIRM_S"),
    ("Silence after an unfinished-looking sentence", 3.5, "ENDPOINT_INCOMPLETE_S"),
    ("Newest audio never trusted as silence", 0.3, "TURN_TAIL_GUARD_S"),
    ("Pause before the first reply of a turn", 0.15, "NATURAL_PAUSE_S"),
    ('"Please hold" filler after this much silence', 1.0, "FILLER_THRESHOLD_S"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS turn_timing(
  log_day TEXT NOT NULL, call_id TEXT NOT NULL, time TEXT NOT NULL, lang TEXT, tier TEXT,
  prep INTEGER, lid INTEGER, asr INTEGER, intent INTEGER, reply INTEGER, tts INTEGER, send INTEGER, total INTEGER NOT NULL,
  api_calls INTEGER, api_ms INTEGER, sig TEXT NOT NULL,
  UNIQUE(log_day, call_id, time, sig));
CREATE INDEX IF NOT EXISTS turn_timing_day ON turn_timing(log_day);
CREATE TABLE IF NOT EXISTS asr_engine_timing(
  log_day TEXT NOT NULL, call_id TEXT NOT NULL, time TEXT NOT NULL, engine TEXT NOT NULL, ms INTEGER NOT NULL,
  UNIQUE(log_day, call_id, time, engine, ms));
CREATE INDEX IF NOT EXISTS asr_engine_day ON asr_engine_timing(log_day);
CREATE TABLE IF NOT EXISTS ollama_calls(
  day TEXT NOT NULL, time TEXT NOT NULL, status INTEGER, route TEXT NOT NULL, ms REAL NOT NULL, path TEXT,
  UNIQUE(day, time, route, ms, path, status));
CREATE INDEX IF NOT EXISTS ollama_day ON ollama_calls(day);
CREATE TABLE IF NOT EXISTS live_samples(ts TEXT NOT NULL, source TEXT NOT NULL, name TEXT NOT NULL, value REAL NOT NULL);
CREATE INDEX IF NOT EXISTS live_name_ts ON live_samples(name, ts);
"""


# ------------------------------------------------------------------ the arithmetic


def percentile(sorted_values: list, q: float):
    """Nearest rank: the smallest value that at least q percent of the values are at or below."""
    n = len(sorted_values)
    return sorted_values[max(0, min(n - 1, math.ceil(q / 100 * n) - 1))]


def describe(values: list) -> dict | None:
    """n, mean, p50, p95, p99 and max of a list of numbers, or None when there are none."""
    if not values:
        return None
    xs = sorted(values)
    return {
        "n": len(xs),
        "mean": round(sum(xs) / len(xs), 1),
        "p50": round(percentile(xs, 50), 1),
        "p95": round(percentile(xs, 95), 1),
        "p99": round(percentile(xs, 99), 1),
        "max": round(xs[-1], 1),
    }


# ------------------------------------------------------------------ writing


class CallMemory:
    """For each call being read: the language of its last `heard` line and the tier marker seen since its last timing line, so a timing line
    can be given both. Kept in memory only; a marker split from its timing line by two reads is simply not attached."""

    def __init__(self, cap: int = 4000):
        self._state: dict[tuple[str, str], dict] = {}
        self._cap = cap

    def get(self, day: str, call_id: str) -> dict:
        key = (day, call_id)
        if key not in self._state:
            if len(self._state) >= self._cap:
                self._state.pop(next(iter(self._state)))
            self._state[key] = {}
        return self._state[key]

    def end(self, day: str, call_id: str) -> None:
        self._state.pop((day, call_id), None)


def note_event(db, memory: CallMemory, ev) -> int:
    """Handle one agent-log event for the speed view. Returns the number of rows added. The caller stores `heard`, `start`, `end` as usual."""
    st = memory.get(ev.day, ev.call_id)
    if ev.kind == "heard":
        st["lang"], st["tier"] = ev.data.get("lang"), None
        return 0
    if ev.kind == "end":
        memory.end(ev.day, ev.call_id)
        return 0
    if ev.kind == "tier":
        st["tier"] = ev.data.get("tier")
        return 0
    if ev.kind == "asr_engines":
        n = 0
        for engine, ms in (ev.data.get("engines") or {}).items():
            n += db.execute(
                "INSERT OR IGNORE INTO asr_engine_timing VALUES (?,?,?,?,?)",
                (ev.day, ev.call_id, ev.time, engine, int(ms)),
            ).rowcount
        return n
    if ev.kind == "timing":
        stages = ev.data.get("stages") or {}
        sig = "|".join(f"{k}={stages[k]}" for k in sorted(stages)) + f"|total={ev.data.get('total')}"
        cur = db.execute(
            "INSERT OR IGNORE INTO turn_timing(log_day, call_id, time, lang, tier, prep, lid, asr, intent, reply, tts, send, total, api_calls, api_ms, sig)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ev.day,
                ev.call_id,
                ev.time,
                st.get("lang"),
                st.get("tier") or "other",
                *[stages.get(s) for s in STAGES],
                int(ev.data.get("total") or 0),
                ev.data.get("api_calls"),
                ev.data.get("api_ms"),
                sig,
            ),
        )
        st["tier"] = None
        return cur.rowcount
    return 0


def add_ollama(db, calls: list) -> int:
    n = 0
    for c in calls:
        n += db.execute(
            "INSERT OR IGNORE INTO ollama_calls VALUES (?,?,?,?,?,?)", (c.day, c.time, c.status, c.route, c.ms, c.path)
        ).rowcount
    return n


def add_live(db, ts: str, source: str, readings: list[tuple[str, float]]) -> None:
    db.executemany("INSERT INTO live_samples VALUES (?,?,?,?)", [(ts, source, name, value) for name, value in readings])


def prune(db, keep_days: int, today: str) -> None:
    cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=keep_days)).isoformat()
    for table, col in (("turn_timing", "log_day"), ("asr_engine_timing", "log_day"), ("ollama_calls", "day")):
        db.execute(f"DELETE FROM {table} WHERE {col} < ?", (cutoff,))  # noqa: S608 - fixed names
    db.execute(
        "DELETE FROM live_samples WHERE ts < ?",
        ((datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=7)).isoformat(),),
    )


# ------------------------------------------------------------------ reading


def _where(lo: str, hi: str, day_col: str, lang: str, tier: str) -> tuple[str, list]:
    sql, args = f"{day_col} BETWEEN ? AND ?", [lo, hi]
    if lang:
        sql += " AND lang=?"
        args.append(lang)
    if tier:
        sql += " AND tier=?"
        args.append(tier)
    return sql, args


def _series(db, column: str, where: str, args: list) -> list[tuple[str, int]]:
    return db.execute(
        f"SELECT log_day, {column} FROM turn_timing WHERE {where} AND {column} IS NOT NULL",
        args,  # noqa: S608 - fixed names
    ).fetchall()


def report(store, days: int, lang: str, tier: str, today: str) -> dict:
    """Everything the speed section shows, for the last `days` days (clinic time), optionally for one language heard and one tier."""
    lo = (datetime.date.fromisoformat(today) - datetime.timedelta(days=max(days, 1) - 1)).isoformat()
    where, args = _where(lo, today, "log_day", lang, tier)
    out: dict = {"from": lo, "to": today, "lang": lang, "tier": tier}
    with closing(store._connect()) as db:  # noqa: SLF001 - the store's own connection factory
        stages, trend = [], {}
        for name in (*STAGES, "total", "api_ms"):
            rows = _series(db, name, where, args)
            d = describe([r[1] for r in rows])
            label, group = STAGE_INFO.get(name, ("Clinic API time during the turn", "data"))
            stages.append({"stage": name, "label": label, "group": group, **(d or {"n": 0})})
            per_day: dict[str, list] = defaultdict(list)
            for day, v in rows:
                per_day[day].append(v)
            trend[name] = {d_: describe(v) for d_, v in sorted(per_day.items())}
        out["stages"] = stages
        out["trend"] = {
            n: [{"day": d_, "p50": x["p50"], "p95": x["p95"], "n": x["n"]} for d_, x in t.items()]
            for n, t in trend.items()
        }

        total_rows = _series(db, "total", where, args)
        n_all = len(total_rows)
        out["turns"] = n_all
        out["slow_share"] = round(sum(1 for _d, v in total_rows if v > SLOW_MS) / n_all, 4) if n_all else None
        out["over_target_share"] = round(sum(1 for _d, v in total_rows if v > TARGET_MS) / n_all, 4) if n_all else None

        langs = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT lang FROM turn_timing WHERE log_day BETWEEN ? AND ? AND lang IS NOT NULL", (lo, today)
            )
        ]  # noqa: S608,F541
        by_lang = {}
        for lg in sorted(langs):
            w, a = _where(lo, today, "log_day", lg, tier)
            by_lang[lg] = {
                s: describe([r[1] for r in _series(db, s, w, a)])
                for s in ("total", "prep", "lid", "asr", "intent", "reply", "tts")
            }
        out["by_language"] = by_lang

        tiers = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT tier FROM turn_timing WHERE log_day BETWEEN ? AND ? AND tier IS NOT NULL", (lo, today)
            )
        ]
        by_tier = {}
        for t in sorted(tiers):
            w, a = _where(lo, today, "log_day", lang, t)
            by_tier[t] = {
                s: describe([r[1] for r in _series(db, s, w, a)]) for s in ("total", "intent", "reply", "tts")
            }
        out["by_tier"] = by_tier

        out["asr_engines"] = [
            {
                "engine": e,
                **(
                    describe(
                        [
                            r[0]
                            for r in db.execute(
                                "SELECT ms FROM asr_engine_timing WHERE engine=? AND log_day BETWEEN ? AND ?",
                                (e, lo, today),
                            )
                        ]
                    )
                    or {}
                ),
            }
            for (e,) in db.execute(
                "SELECT DISTINCT engine FROM asr_engine_timing WHERE log_day BETWEEN ? AND ? ORDER BY engine",
                (lo, today),
            ).fetchall()
        ]
        oll = []
        for (route,) in db.execute(
            "SELECT DISTINCT route FROM ollama_calls WHERE day BETWEEN ? AND ? ORDER BY route", (lo, today)
        ).fetchall():
            ms = [
                r[0]
                for r in db.execute(
                    "SELECT ms FROM ollama_calls WHERE route=? AND day BETWEEN ? AND ?", (route, lo, today)
                )
            ]
            errors = db.execute(
                "SELECT COUNT(*) FROM ollama_calls WHERE route=? AND day BETWEEN ? AND ? AND status>=400",
                (route, lo, today),
            ).fetchone()[0]
            oll.append({"route": route, "errors": errors, **(describe(ms) or {})})
        out["ollama"] = oll

        sql = "SELECT median_reply_ms, slow_replies, turns FROM calls WHERE day BETWEEN ? AND ? AND live=0 AND median_reply_ms IS NOT NULL"
        a2: list = [lo, today]
        if lang:
            sql += " AND lang=?"
            a2.append(lang)
        rows = db.execute(sql, a2).fetchall()
        out["call_medians"] = {
            **(describe([r[0] for r in rows]) or {"n": 0}),
            "slow_replies": sum(r[1] or 0 for r in rows),
            "turns": sum(r[2] or 0 for r in rows),
        }

        out["live"] = _live(db)
    out["thresholds"] = {"target_ms": TARGET_MS, "slow_ms": SLOW_MS, "filler_ms": FILLER_MS}
    out["configured_waits"] = [{"what": w, "seconds": s, "setting": n} for w, s, n in CONFIGURED_WAITS]
    return out


def _live(db) -> dict:
    since = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=3)).isoformat()
    latest: dict[str, dict] = {}
    for source, name, value, ts in db.execute(
        "SELECT source, name, value, ts FROM live_samples s WHERE ts>=? AND ts=(SELECT MAX(ts) FROM live_samples WHERE source=s.source AND name=s.name AND ts>=?)",
        (since, since),
    ):
        latest.setdefault(source, {})[name] = {"value": value, "ts": ts}
    series = {}
    for source, names in latest.items():
        for name in sorted(
            n for n in names if n.startswith("first_audio_p95_s.") or n in ("loop_lag_p95_ms", "backlog_ms")
        ):
            pts = [
                (r[0], r[1])
                for r in db.execute(
                    "SELECT ts, value FROM live_samples WHERE source=? AND name=? AND ts>=? ORDER BY ts",
                    (source, name, since),
                )
            ]
            step = max(1, len(pts) // 90)
            series[f"{source} {name}"] = [{"ts": t, "v": v} for t, v in pts[::step]]
    return {"latest": latest, "series": series}


def slowest(store, days: int, lang: str, tier: str, limit: int, today: str) -> list[dict]:
    lo = (datetime.date.fromisoformat(today) - datetime.timedelta(days=max(days, 1) - 1)).isoformat()
    where, args = _where(lo, today, "log_day", lang, tier)
    with closing(store._connect()) as db:  # noqa: SLF001
        rows = db.execute(
            f"SELECT log_day, call_id, time, lang, tier, {', '.join(STAGES)}, total, api_calls, api_ms FROM turn_timing WHERE {where} ORDER BY total DESC LIMIT ?",  # noqa: S608
            [*args, max(1, min(limit, 200))],
        ).fetchall()
    out = []
    for r in rows:
        st = {s: r[s] for s in STAGES if r[s] is not None}
        top = max(st, key=lambda k: st[k]) if st else ""
        out.append(
            {
                "log_day": r["log_day"], "call_id": r["call_id"], "time": r["time"], "lang": r["lang"], "tier": r["tier"],
                "total": r["total"], "stages": st, "slowest_stage": top, "api_calls": r["api_calls"], "api_ms": r["api_ms"],
                "call_day": store.call_day_for(r["call_id"], r["log_day"]),
            }
        )  # fmt: skip
    return out
