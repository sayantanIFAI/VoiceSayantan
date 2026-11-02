"""Reads the call journal the agent writes (agent/call_journal.py) and turns one call's events into a summary.

A finished call is one line `{"call_id", "caller_phone", "events": [{"seq", "kind", "payload"}, ...]}` in `<journal>/YYYY-MM-DD.jsonl`; a call still in
progress is a file of event lines in `<journal>/inflight/`. At 01:00 clinic time the archiver moves a day to `<archive>/yyyy/mm/DATE.jsonl.gz`.

What is NOT carried over: the caller's phone (only its last four digits) and the values of the `confirmed` event (names, phone, address). Only the
names of the fields that were confirmed are kept.
"""

from __future__ import annotations

import dataclasses
import glob
import gzip
import json
import os
from collections.abc import Iterator

# events that tell nothing about how the call went; they are skipped when looking for the last thing that happened
_TRAILING = frozenset({"end", "satisfaction"})


@dataclasses.dataclass
class CallSummary:
    call_id: str
    finished: bool = True
    channel: str = ""
    last4: str = ""
    languages: list[str] = dataclasses.field(default_factory=list)
    intents: list[str] = dataclasses.field(default_factory=list)  # every intent event, in order
    reasks: list[dict] = dataclasses.field(default_factory=list)  # {"reason", "action", "lang"}
    failures: list[str] = dataclasses.field(default_factory=list)  # llm_failure / tool_failure the caller heard
    escalations: list[str] = dataclasses.field(default_factory=list)
    actions: list[str] = dataclasses.field(default_factory=list)
    outcome: str = ""
    last_kind: str = ""  # the last event before the end of the call
    score: int | None = None
    band: str = ""
    score_reasons: list = dataclasses.field(default_factory=list)
    signals: dict = dataclasses.field(default_factory=dict)
    timeline: list[dict] = dataclasses.field(default_factory=list)


def _timeline_entry(ev: dict) -> dict:
    kind = str(ev.get("kind") or "")
    p = ev.get("payload") or {}
    if kind == "confirmed":
        slots = p.get("slots") or {}
        return {
            "seq": ev.get("seq"),
            "kind": kind,
            "fields": sorted(k for k, v in slots.items() if v not in (None, "", [])),
        }
    if kind in ("start", "language", "intent", "reask", "action", "escalation", "end"):
        return {
            "seq": ev.get("seq"),
            "kind": kind,
            **{k: v for k, v in p.items() if isinstance(v, (str, int, float, bool)) or v is None},
        }
    if kind == "satisfaction":
        return {"seq": ev.get("seq"), "kind": kind, "score": p.get("score"), "band": p.get("band")}
    return {"seq": ev.get("seq"), "kind": kind}


def summarise(call_id: str, events: list[dict], phone: str | None = None, finished: bool = True) -> CallSummary:
    s = CallSummary(call_id=call_id, finished=finished)
    s.last4 = str(phone)[-4:] if phone else ""
    ordered = sorted((e for e in events if isinstance(e, dict)), key=lambda e: e.get("seq") or 0)
    for ev in ordered:
        kind = ev.get("kind")
        p = ev.get("payload") or {}
        if kind == "start":
            s.channel = str(p.get("channel") or "")
        elif kind == "language":
            lang = str(p.get("language") or "")
            if lang and lang not in s.languages:
                s.languages.append(lang)
        elif kind == "intent":
            if p.get("intent"):
                s.intents.append(str(p["intent"]))
        elif kind == "reask":
            if p.get("kind") == "system_failure":
                s.failures.append(str(p.get("reason") or "failure"))
            else:
                s.reasks.append(
                    {
                        "reason": str(p.get("reason") or "unclear"),
                        "action": str(p.get("action") or "reask"),
                        "lang": str(p.get("lang") or ""),
                    }
                )
        elif kind == "action":
            if p.get("name"):
                s.actions.append(str(p["name"]))
        elif kind == "escalation":
            s.escalations.append(str(p.get("reason") or "unknown"))
        elif kind == "satisfaction":
            s.score = p.get("score") if isinstance(p.get("score"), int) else None
            s.band = str(p.get("band") or "")
            s.score_reasons = [
                list(r) for r in (p.get("reasons") or []) if isinstance(r, (list, tuple)) and len(r) == 2
            ]
            s.signals = dict(p.get("signals") or {})
        elif kind == "end":
            s.outcome = str(p.get("outcome") or "")
            s.finished = True
        s.timeline.append(_timeline_entry(ev))
    for ev in reversed(ordered):
        if ev.get("kind") not in _TRAILING:
            s.last_kind = str(ev.get("kind") or "")
            break
    return s


def _json_lines(f) -> Iterator[dict]:
    for raw in f:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


def line_count(path: str) -> int:
    """How many call lines a journal file holds (counted the same way finished_calls counts them)."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        return sum(1 for _ in _json_lines(f))


def finished_calls(path: str, skip: int = 0) -> Iterator[tuple[int, CallSummary]]:
    """The calls of one journal file (plain or .gz) after the first `skip` lines, as (line number, summary)."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        for n, line in enumerate(_json_lines(f), start=1):
            if n <= skip or not line.get("call_id"):
                continue
            yield (
                n,
                summarise(
                    str(line["call_id"]), list(line.get("events") or []), line.get("caller_phone"), finished=True
                ),
            )


def inflight_calls(journal_dir: str) -> Iterator[CallSummary]:
    """Calls still in progress (or died with their process and not yet folded in by the archiver)."""
    for path in sorted(glob.glob(os.path.join(journal_dir, "inflight", "*.jsonl"))):
        call_id = os.path.basename(path)[: -len(".jsonl")]
        try:
            with open(path, encoding="utf-8") as f:
                events = list(_json_lines(f))
        except OSError:
            continue
        if events:
            yield summarise(call_id, events, None, finished=any(e.get("kind") == "end" for e in events))


def day_of(path: str) -> str:
    """`2026-11-02` from `.../2026-11-02.jsonl` or `.../2026-11-02.jsonl.gz`."""
    return os.path.basename(path).split(".")[0]


def day_files(journal_dir: str) -> list[str]:
    return sorted(p for p in glob.glob(os.path.join(journal_dir, "*.jsonl")))


def archive_files(archive_dir: str) -> list[str]:
    return sorted(glob.glob(os.path.join(archive_dir, "*", "*", "*.jsonl.gz")))
