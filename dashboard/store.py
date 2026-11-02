"""The dashboard's own SQLite store.

Two kinds of rows. `calls` holds what the journal says about each call (no caller words). `log_calls` / `log_events` hold what the agent log says
(including what the recogniser heard) and are pruned after `transcript_days`. They are joined only when one call is opened.

A call is keyed by (day, call_id), never by call_id alone: the agent's call ids are 8 hex characters, so the same id can come up on another day.

The file lives on /workspace, a network mount, so the journal mode is left at SQLite's default (rollback journal), the same choice clinic-api/db.py made.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import sqlite3
from collections import Counter
from contextlib import closing

from dashboard.classify import Labels, classify
from dashboard.journal import CallSummary
from dashboard.logparse import LogEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls(
  day TEXT NOT NULL, call_id TEXT NOT NULL, live INTEGER NOT NULL DEFAULT 0,
  lang TEXT, channel TEXT, category TEXT, transfer_reason TEXT, transfer_group TEXT, drop_cause TEXT,
  reasks INTEGER, reask_reasons TEXT, booking_intent INTEGER, booking_origin TEXT, booking_confirmed INTEGER, booking_changed INTEGER,
  wrong TEXT, unhappy INTEGER, band TEXT, score INTEGER, tags TEXT, last4 TEXT, detail TEXT,
  PRIMARY KEY(day, call_id));
CREATE INDEX IF NOT EXISTS calls_day ON calls(day);
CREATE TABLE IF NOT EXISTS log_calls(log_day TEXT NOT NULL, call_id TEXT NOT NULL, started TEXT, ended TEXT, PRIMARY KEY(log_day, call_id));
CREATE TABLE IF NOT EXISTS log_events(
  log_day TEXT NOT NULL, call_id TEXT NOT NULL, time TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL,
  UNIQUE(log_day, call_id, time, kind, data));
CREATE INDEX IF NOT EXISTS log_events_call ON log_events(call_id);
CREATE TABLE IF NOT EXISTS sources(path TEXT PRIMARY KEY, inode INTEGER, off INTEGER, head TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


_SUMMARY_COLUMNS = (
    "category, transfer_reason, transfer_group, drop_cause, reasks, reask_reasons, booking_intent, booking_origin, "
    "booking_confirmed, booking_changed, wrong, unhappy, band, score, lang, live"
)


def clinic_today() -> str:
    """The clinic's date (UTC+5:30), the same clock the call journal uses to name its day files."""
    return (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5, minutes=30)).date().isoformat()


def day_range(days: int, today: str) -> tuple[str, str]:
    end = datetime.date.fromisoformat(today)
    return (end - datetime.timedelta(days=max(days, 1) - 1)).isoformat(), end.isoformat()


class Store:
    def __init__(self, path: str):
        self.path = path
        with closing(self._connect()) as db:
            db.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    # ------------------------------------------------------------------ writing
    def save_call(self, day: str, s: CallSummary, live: bool = False) -> Labels:
        lab = classify(s)
        detail = {"summary": dataclasses.asdict(s), "labels": dataclasses.asdict(lab)}
        with closing(self._connect()) as db, db:
            if not live:
                db.execute("DELETE FROM calls WHERE call_id=? AND live=1", (s.call_id,))
            db.execute(
                "INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    day,
                    s.call_id,
                    int(live),
                    s.languages[0] if s.languages else "",
                    s.channel,
                    lab.category,
                    lab.transfer_reason,
                    lab.transfer_group,
                    lab.drop_cause,
                    lab.reasks,
                    json.dumps(lab.reask_reasons),
                    int(lab.booking_intent),
                    lab.booking_origin,
                    int(lab.booking_confirmed),
                    int(lab.booking_changed),
                    json.dumps(lab.wrong_signals),
                    int(lab.unhappy),
                    s.band,
                    s.score,
                    ",".join(lab.tags),
                    s.last4,
                    json.dumps(detail, ensure_ascii=False),
                ),
            )
        return lab

    def has_finished_calls(self, day: str) -> bool:
        with closing(self._connect()) as db:
            return db.execute("SELECT 1 FROM calls WHERE day=? AND live=0 LIMIT 1", (day,)).fetchone() is not None

    def replace_live(self, day: str, calls: list[CallSummary], since: str) -> None:
        """The calls in progress right now. A call already saved as finished (on or after `since`) is not shown as live as well."""
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM calls WHERE live=1")
        for s in calls:
            with closing(self._connect()) as db:
                done = db.execute(
                    "SELECT 1 FROM calls WHERE call_id=? AND live=0 AND day>=?", (s.call_id, since)
                ).fetchone()
            if not done:
                self.save_call(day, s, live=True)

    def add_log_events(self, events: list[LogEvent]) -> int:
        n = 0
        with closing(self._connect()) as db, db:
            for ev in events:
                cur = db.execute(
                    "INSERT OR IGNORE INTO log_events VALUES (?,?,?,?,?)",
                    (ev.day, ev.call_id, ev.time, ev.kind, json.dumps(ev.data, ensure_ascii=False, sort_keys=True)),
                )
                n += cur.rowcount
                db.execute("INSERT OR IGNORE INTO log_calls(log_day, call_id) VALUES (?,?)", (ev.day, ev.call_id))
                if ev.kind == "start":
                    db.execute(
                        "UPDATE log_calls SET started=? WHERE log_day=? AND call_id=?", (ev.time, ev.day, ev.call_id)
                    )
                elif ev.kind == "end":
                    db.execute(
                        "UPDATE log_calls SET ended=? WHERE log_day=? AND call_id=?", (ev.time, ev.day, ev.call_id)
                    )
        return n

    def prune_transcripts(self, keep_days: int, today: str) -> None:
        cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=keep_days)).isoformat()
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM log_events WHERE log_day < ?", (cutoff,))
            db.execute("DELETE FROM log_calls WHERE log_day < ?", (cutoff,))

    def get_source(self, path: str) -> tuple[int, int, str]:
        with closing(self._connect()) as db:
            row = db.execute("SELECT inode, off, head FROM sources WHERE path=?", (path,)).fetchone()
        return (row["inode"], row["off"], row["head"]) if row else (0, 0, "")

    def put_source(self, path: str, inode: int, offset: int, head: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?,?)", (path, inode, offset, head))

    def set_meta(self, key: str, value: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    def get_meta(self, key: str) -> str:
        with closing(self._connect()) as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else ""

    # ------------------------------------------------------------------ reading
    def summary(self, days: int, lang: str, today: str) -> dict:
        lo, hi = day_range(days, today)
        sql = f"SELECT {_SUMMARY_COLUMNS} FROM calls WHERE day BETWEEN ? AND ?"
        args: list = [lo, hi]
        if lang:
            sql += " AND lang=?"
            args.append(lang)
        with closing(self._connect()) as db:
            rows = db.execute(sql, args).fetchall()
        cats = Counter(r["category"] for r in rows)
        drops = Counter(r["drop_cause"] for r in rows if r["category"] == "dropped")
        tr_rows = [r for r in rows if r["category"] == "transferred"]
        groups = Counter(r["transfer_group"] for r in tr_rows)
        reasons: dict[str, dict] = {}
        for r in tr_rows:
            e = reasons.setdefault(r["transfer_reason"], {"count": 0, "group": r["transfer_group"]})
            e["count"] += 1
        reask_by: Counter = Counter()
        reask_total = 0
        calls_with_reask = 0
        reask_then_lost = 0
        for r in rows:
            if r["reasks"]:
                calls_with_reask += 1
                reask_total += r["reasks"]
                if r["category"] in ("dropped", "transferred"):
                    reask_then_lost += 1
                for k, v in json.loads(r["reask_reasons"] or "{}").items():
                    reask_by[k] += v
        booking_rows = [r for r in rows if r["booking_intent"]]
        origin = Counter(r["booking_origin"] for r in booking_rows)
        confirmed_by = Counter(r["booking_origin"] for r in booking_rows if r["booking_confirmed"])
        not_booked = Counter(r["category"] for r in booking_rows if not r["booking_confirmed"])
        wrong_by: Counter = Counter()
        wrong_calls = 0
        for r in rows:
            sig = json.loads(r["wrong"] or "[]")
            if sig:
                wrong_calls += 1
            for k in sig:
                wrong_by[k] += 1
        scores = [r["score"] for r in rows if r["score"] is not None]
        return {
            "from": lo,
            "to": hi,
            "calls": len(rows),
            "categories": {
                c: cats.get(c, 0)
                for c in ("answered", "booked", "changed", "ended", "transferred", "dropped", "quiet", "live")
            },
            "dropped": {"total": cats.get("dropped", 0), "causes": dict(drops)},
            "transferred": {"total": len(tr_rows), "groups": dict(groups), "reasons": reasons},
            "clarifications": {
                "calls": calls_with_reask,
                "total": reask_total,
                "per_call": round(reask_total / len(rows), 2) if rows else 0,
                "by_reason": dict(reask_by),
                "calls_that_still_ended_dropped_or_transferred": reask_then_lost,
            },
            "booking": {
                "calls_with_booking_intent": len(booking_rows),
                "requested": origin.get("requested", 0),
                "after_enquiry": origin.get("after_enquiry", 0),
                "confirmed": sum(1 for r in booking_rows if r["booking_confirmed"]),
                "confirmed_requested": confirmed_by.get("requested", 0),
                "confirmed_after_enquiry": confirmed_by.get("after_enquiry", 0),
                "not_confirmed_by_outcome": dict(not_booked),
                "changes": sum(1 for r in rows if r["booking_changed"]),
            },
            "wrong": {
                "calls": wrong_calls,
                "by_signal": dict(wrong_by),
                "unhappy_calls": sum(1 for r in rows if r["unhappy"]),
            },
            "score": {
                "scored": len(scores),
                "mean": round(sum(scores) / len(scores), 1) if scores else None,
                "bands": dict(Counter(r["band"] for r in rows if r["band"])),
            },
            "languages": dict(Counter(r["lang"] or "unknown" for r in rows)),
        }

    def list_calls(self, days: int, lang: str, tag: str, limit: int, today: str) -> list[dict]:
        lo, hi = day_range(days, today)
        sql = "SELECT day, call_id, live, lang, channel, category, transfer_reason, drop_cause, reasks, band, score, tags, last4 FROM calls WHERE day BETWEEN ? AND ?"
        args: list = [lo, hi]
        if lang:
            sql += " AND lang=?"
            args.append(lang)
        if tag:
            sql += " AND (',' || tags || ',') LIKE ?"
            args.append(f"%,{tag},%")
        sql += " ORDER BY day DESC, rowid DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        with closing(self._connect()) as db:
            rows = db.execute(sql, args).fetchall()
        return [{**dict(r), "tags": [t for t in (r["tags"] or "").split(",") if t]} for r in rows]

    def call_detail(self, day: str, call_id: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT detail, live FROM calls WHERE day=? AND call_id=?", (day, call_id)).fetchone()
            if row is None:
                return None
            days = [
                r["log_day"]
                for r in db.execute("SELECT DISTINCT log_day FROM log_calls WHERE call_id=?", (call_id,)).fetchall()
            ]
            turns: list[dict] = []
            log_day = ""
            if days:
                want = datetime.date.fromisoformat(day)
                log_day = min(days, key=lambda d: (abs((datetime.date.fromisoformat(d) - want).days), d))
                if abs((datetime.date.fromisoformat(log_day) - want).days) <= 1:
                    for r in db.execute(
                        "SELECT time, kind, data FROM log_events WHERE log_day=? AND call_id=? ORDER BY time, rowid",
                        (log_day, call_id),
                    ):
                        turns.append({"time": r["time"], "kind": r["kind"], **json.loads(r["data"])})
                else:
                    log_day = ""
        detail = json.loads(row["detail"])
        return {"day": day, "call_id": call_id, "live": bool(row["live"]), "log_day": log_day, **detail, "log": turns}
