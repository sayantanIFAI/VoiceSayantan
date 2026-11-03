"""The Ollama log: how long each model request took, as the model server itself saw it.

Ollama logs one line per request, e.g.

    [GIN] 2026/11/02 - 12:31:01 | 200 |  311.9ms |       127.0.0.1 | POST     "/api/generate"

The agent calls `/api/generate` for the intent model and `/api/embed` (or `/api/embeddings`) for the semantic cache's embedding model. The line has no
call id, so these times belong to the model server, not to a particular turn; the turn's own intent stage is in the agent's `turn timing:` line.
"""

from __future__ import annotations

import dataclasses
import re

_LINE = re.compile(
    r'^\[GIN\] (\d{4}/\d{2}/\d{2}) - (\d{2}:\d{2}:\d{2}) \|\s*(\d{3}) \|\s*([0-9.]+(?:µs|us|ms|s|m|h)(?:[0-9.]+(?:µs|us|ms|s|m))*)\s*\|[^|]*\|\s*(\w+)\s+"([^"]*)"'
)
_PART = re.compile(r"([0-9.]+)(µs|us|ms|s|m|h)")
_UNIT_MS = {"µs": 0.001, "us": 0.001, "ms": 1.0, "s": 1000.0, "m": 60000.0, "h": 3600000.0}
GENERATE = ("/api/generate", "/api/chat")
EMBED = ("/api/embed", "/api/embeddings")


@dataclasses.dataclass(frozen=True)
class OllamaCall:
    day: str
    time: str
    status: int
    ms: float
    route: str  # generate | embed | other
    path: str


def duration_ms(text: str) -> float:
    """`311.9ms`, `1.234s`, `1m3.5s`, `950µs` in milliseconds."""
    return sum(float(n) * _UNIT_MS[u] for n, u in _PART.findall(text))


def parse_line(line: str) -> OllamaCall | None:
    m = _LINE.match(line)
    if m is None:
        return None
    day, time_, status, dur, _method, path = m.groups()
    route = "generate" if path in GENERATE else "embed" if path in EMBED else "other"
    return OllamaCall(day.replace("/", "-"), time_, int(status), round(duration_ms(dur), 3), route, path)
