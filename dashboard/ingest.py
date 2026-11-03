"""Copies what the agent has written into the dashboard's store. Read-only on everything the agent owns; safe to run again and again."""

from __future__ import annotations

import datetime
import glob
import logging
import os
import threading

from dashboard import journal, live, logparse, ollama_log
from dashboard.config import Config
from dashboard.store import Store, clinic_today

logger = logging.getLogger("dashboard.ingest")


def ingest_once(cfg: Config, store: Store) -> dict:
    stats = {"log_events": 0, "calls": 0, "live": 0, "ollama": 0, "readings": 0}
    today = clinic_today()
    # the log parser learned new lines: read the logs from the start once (agents' lines already read were skipped, and the saved position is past them)
    logs_again = store.needs_logs_backfill()
    backfill = (
        store.needs_calls_backfill()
    )  # a new column of `calls` is filled by reading the journals and archives again

    for path in sorted({p for pattern in cfg.log_files for p in glob.glob(pattern)}):
        inode, offset, head = (0, 0, "") if logs_again else store.get_source(path)
        events, inode, offset, head = logparse.read_new(path, inode, offset, head, cfg.keep_transcripts)
        if events:
            stats["log_events"] += store.add_log_events(events)
        store.put_source(path, inode, offset, head)

    for path in journal.day_files(cfg.journal_dir):
        key = "journal:" + path
        _inode, seen, _head = store.get_source(key)
        total = journal.line_count(path)
        # the archiver rewrote the file with fewer lines: read it again (saving a call twice changes nothing)
        if backfill or total < seen:
            seen = 0
        if total == seen:
            continue
        day = journal.day_of(path)
        for _n, summary in journal.finished_calls(path, skip=seen):
            store.save_call(day, summary)
            stats["calls"] += 1
        store.put_source(key, 0, total, "")

    # archived days never change, so each is read once, and only if no journal for that day was read
    for path in journal.archive_files(cfg.archive_dir):
        key = "archive:" + path
        if store.get_source(key)[1] and not backfill:
            continue
        day = journal.day_of(path)
        if backfill or not store.has_finished_calls(day):
            for _n, summary in journal.finished_calls(path):
                store.save_call(day, summary)
                stats["calls"] += 1
        store.put_source(key, 0, 1, "")

    for path in sorted({p for pattern in cfg.ollama_logs for p in glob.glob(pattern)}):
        key = "ollama:" + path
        inode, offset, head = (0, 0, "") if logs_again else store.get_source(key)
        calls, inode, offset, head = logparse.read_new(path, inode, offset, head, parser=ollama_log.parse_line)
        if calls:
            stats["ollama"] += store.add_ollama(calls)
        store.put_source(key, inode, offset, head)

    for url in cfg.agent_urls:
        readings = live.readings(url)
        store.add_live(url.split("//", 1)[-1], readings)
        stats["readings"] += len(readings)

    in_progress = list(journal.inflight_calls(cfg.journal_dir))
    since = (datetime.date.fromisoformat(today) - datetime.timedelta(days=1)).isoformat()
    store.replace_live(today, in_progress, since)
    stats["live"] = len(in_progress)

    store.prune_transcripts(cfg.transcript_days, today)
    store.prune_speed(cfg.speed_days, today)
    if backfill:
        store.calls_backfilled()
    if logs_again:
        store.logs_backfilled()
    store.set_meta("last_ingest", datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"))
    return stats


class Ingestor(threading.Thread):
    """Runs ingest_once every `poll_s` seconds. An error is logged and the next round tries again."""

    def __init__(self, cfg: Config, store: Store):
        super().__init__(name="dashboard-ingest", daemon=True)
        self.cfg, self.store = cfg, store
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                ingest_once(self.cfg, self.store)
            except Exception:  # noqa: BLE001 - the dashboard must keep serving what it already has
                logger.exception("ingest round failed")
            self._stop_event.wait(self.cfg.poll_s)

    def stop(self) -> None:
        self._stop_event.set()


def ensure_dirs(cfg: Config) -> None:
    os.makedirs(os.path.dirname(cfg.db_path) or ".", exist_ok=True)
