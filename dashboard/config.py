"""Where the dashboard reads from and how it is served. Every value can be set by an environment variable; the defaults are the paths the pod uses."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # agent/call_journal.py writes one line per finished call here, and inflight/ for calls in progress
    journal_dir: str
    archive_dir: str  # tools/call_log_archiver.py moves a day's journal here at 01:00 clinic time
    log_files: tuple[str, ...]  # the agent logs; only lines that belong to a call are read
    db_path: str  # the dashboard's own store
    host: str
    port: int
    user: str
    password: str
    poll_s: float
    keep_transcripts: bool  # False: the dashboard never stores what the caller said
    transcript_days: int  # transcripts older than this are deleted from the dashboard's store


def from_env() -> Config:
    files = os.environ.get("DASHBOARD_LOG_FILES", "/workspace/logs/pcm_app.log,/workspace/logs/main_app.log")
    return Config(
        journal_dir=os.environ.get("CALL_JOURNAL_DIR", "/workspace/call_journal"),
        archive_dir=os.environ.get("CALL_ARCHIVE_DIR", "/workspace/call_archive"),
        log_files=tuple(f.strip() for f in files.split(",") if f.strip()),
        db_path=os.environ.get("DASHBOARD_DB", "/workspace/dashboard/dashboard.db"),
        host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.environ.get("DASHBOARD_PORT", "8890")),
        user=os.environ.get("DASHBOARD_USER", ""),
        password=os.environ.get("DASHBOARD_PASSWORD", ""),
        poll_s=float(os.environ.get("DASHBOARD_POLL_S", "10")),
        keep_transcripts=os.environ.get("DASHBOARD_KEEP_TRANSCRIPTS", "1") == "1",
        transcript_days=int(os.environ.get("DASHBOARD_TRANSCRIPT_DAYS", "30")),
    )
