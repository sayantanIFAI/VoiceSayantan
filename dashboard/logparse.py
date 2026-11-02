"""Reads the lines of the agent's log that belong to one call.

The agent logs `%(asctime)s %(levelname)s %(name)s: %(message)s` and puts `[call_id]` first in a call's messages. Of those, this reads only the few
that say something about what happened: when the call started and ended, what the recogniser heard, an empty recognition, an emergency, abuse, a hand-off,
a timeout, the call score. Every other line is ignored, so a change to some other log message cannot break the dashboard.

The agent does NOT log what it says back, so the AI's side of a conversation is not in this file and is not shown anywhere in the dashboard.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import re

_HEADER = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),\d{3} (\w+) ([\w.\-]+): (.*)$")
_CALL = re.compile(r"^\[([0-9A-Za-z_-]{4,40})\] (.*)$")
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
    path: str, inode: int, offset: int, head: str, keep_text: bool = True
) -> tuple[list[LogEvent], int, int, str]:
    """The events appended to `path` since the last read. Returns (events, inode, offset, head).

    The deploy script starts the agent with `> logfile`, which empties the file at every restart, so a file that is smaller than the
    saved offset, a new file, or a file whose first bytes changed is read again from its start. Only whole lines are consumed."""
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
        events: list[LogEvent] = []
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
                ev = parse_line(raw, keep_text)
                if ev is not None:
                    events.append(ev)
    return events, st.st_ino, offset, first
