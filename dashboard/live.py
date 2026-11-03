"""Reads the numbers the running agent already offers over HTTP (`/api/stats`, `/api/health`) and turns them into a flat list of (name, value).

Nothing is changed in the agent: these are GET endpoints it already serves. The agent's own counters are per process and reset when it restarts, so the
dashboard stores each reading with its time instead of keeping the latest one.

  first_audio_p50_s.<lang>, first_audio_p95_s.<lang>   the agent's own window (its last 200 turns) of end-of-turn to first audio, per language
  admission_p50_s, admission_p95_s                    the same, over all languages, as the admission controller sees it
  detector.<name>.p95_s                                a per-turn detector (channel quality, audio analysis, ...) against its time budget
  loop_lag_p95_ms, loop_lag_max_ms, backlog_ms         how late the event loop wakes and how much audio is waiting to be read
  tts_cache_hit_rate, intent_cache_hit_rate, fast_path_serve_rate
  active_calls
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def _get(url: str, timeout: float) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - the base URLs are the operator's own settings
            obj = json.loads(r.read())
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return obj if isinstance(obj, dict) else None


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def readings(base_url: str, timeout: float = 3.0) -> list[tuple[str, float]]:
    """What one agent process says right now. An agent that does not answer gives an empty list."""
    base = base_url.rstrip("/")
    out: list[tuple[str, float]] = []

    def add(name: str, value) -> None:
        v = _num(value)
        if v is not None:
            out.append((name, v))

    stats = _get(base + "/api/stats", timeout)
    if stats:
        for lang, d in (stats.get("turn_latency_by_language") or {}).items():
            if isinstance(d, dict) and d.get("samples"):
                add(f"first_audio_p50_s.{lang}", d.get("p50_s"))
                add(f"first_audio_p95_s.{lang}", d.get("p95_s"))
        adm = stats.get("admission") or {}
        add("admission_p50_s", adm.get("turn_latency_p50_s"))
        add("admission_p95_s", adm.get("turn_latency_p95_s"))
        add("active_calls", adm.get("active_calls"))
        for name, d in (stats.get("detector_budget") or {}).items():
            if isinstance(d, dict) and d.get("samples"):
                add(f"detector.{name}.p95_s", d.get("p95_s"))
        add("tts_cache_hit_rate", (stats.get("tts_cache") or {}).get("hit_rate"))
        add("intent_cache_hit_rate", (stats.get("intent_cache") or {}).get("hit_rate"))
        add("fast_path_serve_rate", (stats.get("fast_path") or {}).get("serve_rate"))
    health = _get(base + "/api/health", timeout)
    if health:
        ing = health.get("ingress") or {}
        add("loop_lag_p95_ms", ing.get("event_loop_lag_ms_p95"))
        add("loop_lag_max_ms", ing.get("event_loop_lag_ms_max"))
        add("backlog_ms", ing.get("max_backlog_ms"))
    return out
