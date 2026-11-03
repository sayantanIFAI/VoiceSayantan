"""Reads the lines of the agent's log that belong to one call.

The agent logs `%(asctime)s %(levelname)s %(name)s: %(message)s` and puts `[call_id]` first in a call's messages. Of those, this reads only the few
that say something about what happened: when the call started and ended, what the recogniser heard, an empty recognition, an emergency, abuse, a hand-off,
a timeout, the call score. Every other line is ignored, so a change to some other log message cannot break the dashboard.

Three more lines are read for the speed view: `turn timing:` (where the time from the start of a turn to the first audio went, stage by stage),
`ASR timings:` (how long each recogniser took) and the few lines that say which tier answered a turn (the intent cache, the fast path, a rule).

Since 2026-11-03 the agent also logs what it says back (`said (<language>[, filler]): '<text>'`, one line per reply, written where the reply is sent), so a call
reads as a conversation on one clock. Calls made before that have the caller's side only.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import re
from collections.abc import Callable

_HEADER = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),\d{3} (\w+) ([\w.\-]+): (.*)$")
_CALL = re.compile(r"^\[([0-9A-Za-z_-]{4,40})\] (.*)$")
_SAID = re.compile(r"^said \(([\w?]+)(, filler)?\): (.*)$")
_HEARD = re.compile(r"^heard \(([\w?]+), ([\w?]+), agreement ([0-9.]+)\): (.*)$")
_SIMPLE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^call started"), "start"),
    (re.compile(r"^call ended"), "end"),
    (re.compile(r"^ASR returned empty text"), "empty"),
    (re.compile(r"^possible emergency"), "emergency"),
    (re.compile(r"^abusive turn (\d+)"), "abuse"),
    (re.compile(r"^handoff to human: (.+)$"), "handoff"),
    (re.compile(r"^audio_overrun"), "audio_overrun"),
    (re.compile(r"^idle timeout"), "idle_timeout"),
    (re.compile(r"^[0-9.]+s of silence"), "silence"),
    (re.compile(r"^reply discarded after interrupt"), "interrupted"),
    (re.compile(r"^reply language mismatch"), "lang_mismatch"),
    (re.compile(r"^reply blocked, unspeakable"), "unspeakable"),
    (re.compile(r"^call score: (\d+|None) \((\w+)\)"), "score"),
)
_TIMING = re.compile(r"^turn timing: (.*) \| total (\d+) ms(?: \| clinic API (\d+) calls (\d+) ms)?$")
_STAGE = re.compile(r"([a-z_]+) (\d+) ms")
_ASR_ENGINES = re.compile(r"^ASR timings: (.*)$")
# which tier answered the turn: the line is logged just before that turn's timing line. A turn with none of these was answered by something else
# (the model after a refusal is marked; booking flow, early routes and guards are not).
_TIERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^intent cache \S+ hit(?! skipped)"), "cache"),
    (re.compile(r"^fast path resolved "), "fast_path"),
    (re.compile(r"^fast path \S+ refused .*the model decides"), "model"),
    (re.compile(r".*(?:answered by rule|read by rule|named by rule)"), "rule"),
)
BLOCK_BYTES = 8 * 1024 * 1024  # a first read of a large log is done in blocks of this size


@dataclasses.dataclass(frozen=True)
class LogEvent:
    day: str  # the date in the log's own clock
    time: str
    call_id: str
    kind: str  # start, end, heard, empty, emergency, abuse, handoff, audio_overrun, idle_timeout, silence, interrupted, lang_mismatch, unspeakable, score
    data: dict


def _unrepr(text: str) -> str:
    """The agent logs the recognised text with %r; give back the plain string."""
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text.strip("'\"")
    return value if isinstance(value, str) else str(value)


def parse_line(line: str, keep_text: bool = True) -> LogEvent | None:
    """One log line as a call event, or None when it is not one of the lines this dashboard uses."""
    head = _HEADER.match(line)
    if head is None:
        return None
    day, time_, _level, _logger, message = head.groups()
    call = _CALL.match(message)
    if call is None:
        return None
    call_id, body = call.groups()
    heard = _HEARD.match(body)
    if heard is not None:
        lang, decoder, agreement, text = heard.groups()
        data = {"lang": lang, "decoder": decoder, "agreement": float(agreement)}
        if keep_text:
            data["text"] = _unrepr(text)
        return LogEvent(day, time_, call_id, "heard", data)
    said = _SAID.match(body)
    if said is not None:
        lang, filler, text = said.groups()
        data = {"lang": lang, "filler": bool(filler)}
        if keep_text:
            data["text"] = _unrepr(text)
        return LogEvent(day, time_, call_id, "said", data)
    timing = _TIMING.match(body)
    if timing is not None:
        stages = {name: int(ms) for name, ms in _STAGE.findall(timing.group(1))}
        data = {
            "stages": stages,
            "total": int(timing.group(2)),
            "api_calls": int(timing.group(3) or 0),
            "api_ms": int(timing.group(4) or 0),
        }
        return LogEvent(day, time_, call_id, "timing", data)
    engines = _ASR_ENGINES.match(body)
    if engines is not None:
        return LogEvent(
            day, time_, call_id, "asr_engines", {"engines": {n: int(ms) for n, ms in _STAGE.findall(engines.group(1))}}
        )
    for pattern, tier in _TIERS:
        if pattern.match(body):
            return LogEvent(day, time_, call_id, "tier", {"tier": tier})
    for pattern, kind in _SIMPLE:
        m = pattern.match(body)
        if m is None:
            continue
        data = {}
        if kind in ("handoff", "abuse") and m.groups():
            data["value"] = m.group(1)
        if kind == "score":
            data = {"score": None if m.group(1) == "None" else int(m.group(1)), "band": m.group(2)}
        return LogEvent(day, time_, call_id, kind, data)
    return None


def read_new(
    path: str,
    inode: int,
    offset: int,
    head: str,
    keep_text: bool = True,
    parser: Callable[[str], object | None] | None = None,
) -> tuple[list, int, int, str]:
    """The events appended to `path` since the last read. Returns (events, inode, offset, head).

    The deploy script starts the agent with `> logfile`, which empties the file at every restart, so a file that is smaller than the
    saved offset, a new file, or a file whose first bytes changed is read again from its start. Only whole lines are consumed.
    `parser` turns one line into an event or None (default: this module's agent-log parser); the Ollama log is read with its own."""
    try:
        st = os.stat(path)
    except OSError:
        return [], inode, offset, head
    if offset and st.st_ino == inode and st.st_size == offset:
        return [], inode, offset, head  # not grown since the last read
    with open(path, "rb") as f:
        first = f.read(64).hex()
        if st.st_ino != inode or st.st_size < offset or (head and first != head):
            offset = 0
        events: list = []
        while True:
            f.seek(offset)
            data = f.read(BLOCK_BYTES)
            if not data:
                break
            end = data.rfind(b"\n")
            if end < 0:
                break  # a partial line: wait for the rest
            chunk = data[: end + 1]
            offset += len(chunk)
            for raw in chunk.decode("utf-8", "replace").splitlines():
                ev = parser(raw) if parser is not None else parse_line(raw, keep_text)
                if ev is not None:
                    events.append(ev)
    return events, st.st_ino, offset, first
