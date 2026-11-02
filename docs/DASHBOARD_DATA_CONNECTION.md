# Connecting the dashboard to real data

Written 2026-11-02 from the code on `main`. Nothing here was built or run. Companion to [TEST_GUIDE.md](TEST_GUIDE.md) section 7 and [QUERY_AND_FAILURE_TAXONOMY.md](QUERY_AND_FAILURE_TAXONOMY.md).

## 1. Principles

1. **The dashboard never sits in the call path.** It reads side channels (a counter endpoint, files, the database). The agent already has an event-loop lag problem at 30 calls (ADR 0002); anything that adds work per turn must be a queue put, as the call journal already is.
2. **Read-only, one writer.** One small collector process on the pod writes the dashboard's own store; the dashboard only reads that store. The agent and clinic API are never queried by a browser.
3. **Redact on ingest, not on display.** What lands in the dashboard store must already be free of names, phone numbers and caller words (see section 3).
4. **Data stays inside the pod's boundary.** HANDOVER section 10 flags a past incident of patient data on an EU pod. The collector, store and dashboard run on the same India-resident deployment as the agent.

## 2. Sources, and how to read each

| Source | What is in it | How to read it | Watch out for |
|---|---|---|---|
| `GET /api/stats` on each agent (`:8100` main, `:8101` pcm) | counters: `fast_path`, `intent_cache`, `tts_cache`, `admission`, `insufficient_information`, `abstentions`-style buckets, `turn_latency_by_language`, `reask_outcomes`, `audio_issue_buckets`, `language_mismatches`, `apology_events`, `barge_in_interrupts`, `senior_detections`, `golden_buckets` | scrape from `127.0.0.1` every 15 s; flatten `{key: {"intent:lang": n}}` to `name{reason,intent,lang}` | counters are **per process and reset on restart**: store raw samples and compute deltas, treating a decrease as a reset. Label by process name. |
| `GET /api/health`, `/api/admission` | models loaded, languages active, admission open, ingress backlog, loop lag | same scrape | no build identifier today (see 6) |
| Call journal `/workspace/call_journal/YYYY-MM-DD.jsonl` (one line per finished call) and `inflight/<call_id>.jsonl` (a call in progress) | the call's events: `start`, `language`, `intent`, `action`, `confirmed`, `reask`, `escalation`, `satisfaction`, `patient`, `history`, `end` | tail with a stored byte offset per file; read `inflight` for live calls | **raw personal data** (section 3). The nightly archiver deletes the day's file at 01:00 clinic time and moves it to `/workspace/call_archive/yyyy/mm/DATE.jsonl.gz` plus a CSV; ingest before then, or read the gzip to backfill. Dates are clinic time (UTC+5:30). |
| Agent log `/workspace/logs/pcm_app.log` | `turn timing:` lines (marks and total ms, clinic API calls and ms), warnings for LID, ASR, TTS, tool failures | tail and keep **only** lines matching `turn timing:` | the same file holds the recognised text (`heard (...): %r`, `main.py:5947`) and phone digits (`main.py:6921`). Never ship this log whole. |
| Clinic API database (PostgreSQL, `127.0.0.1:5432`) | bookings and `booking_log`, `call_records` (only after the 01:00 load), referrals, callbacks, `audit_log`, preferences | a **read-only role** with a statement timeout, or the existing endpoints such as `GET /api/v1/calls/satisfaction/summary` | today's calls are not here yet in `journal` mode |
| `gate-report.json` from `scripts/gate.sh` | per-check pass, fail, skip | the CI job or the developer's run pushes it with the commit sha | skips must be shown as skips |
| `tools/asr_eval.py --json` | WER, CER, entity table, per bucket | pushed after each evaluation with the model and build | synthetic and real utterances are separate groups |
| `tools/loadtest/sampler.py` output | backlog, loop lag, GPU, CPU every 2 s | ingest the `.jsonl` after a run | test runs only; label them so they are not mixed with live data |

## 3. Privacy: two things to settle before ingesting

* **The journal line is not redacted.** `CallJournal.close_call` writes `caller_phone` and the `confirmed` event's **raw slots** (name, phone, address). The redaction (`redact_confirmed`: an allow-list, a phone as its last four digits) happens later, in the clinic API. A collector reading journal files must apply the same allow-list itself and drop `caller_phone` (keep the last four digits at most). Do not copy journal files anywhere unredacted.
* **The agent log holds caller words.** HANDOVER section 6 says transcripts are not logged; the current code logs them at INFO. Decide the policy: either keep the log for debugging and restrict who can read it, or change those lines. For the dashboard, the safe route is to stop scraping the log (section 5, step 2) and have the agent emit structured numbers.

## 4. Where the dashboard's own data lives

Two constraints from the repo: `/workspace` survives pod restarts but is a network mount where Postgres cannot run; the local disk is fast but is wiped on a full pod restart (`clinic-api/db.py`, ADR 0006).

| Option | Good | Cost |
|---|---|---|
| **A. SQLite file on `/workspace`, collector is the only writer** | survives restarts; same reasoning the clinic API used before Postgres; nothing to install | one writer; fine for this volume (a few thousand calls a day) |
| B. A second database in the existing Postgres cluster (`ops_metrics`, separate from `clinic`) | concurrent readers, SQL for the failure views | covered by the existing base-backup and archive scripts; local disk is wiped on a full restart, restored from `/workspace` backups |
| C. Prometheus plus Grafana for counters, Postgres for events | standard time-series tools, alerts built in | two more services to keep up on a pod that restarts; an exporter for the `/api/stats` JSON |

**Recommendation:** start with A (or B) and one dashboard server that reads it. Add Prometheus only if you want its alerting. The mockups are plain HTML panels, so a small server with a JSON endpoint per panel is enough.

### Tables (all redacted)

| Table | Key | Holds |
|---|---|---|
| `counter_samples` | (ts, process, name, labels) | the scraped counters, raw |
| `calls` | (day, call_id) | channel, languages, intents, outcome, score and band, duration, build |
| `call_events` | (day, call_id, seq) | the redacted events |
| `turns` | (day, call_id, turn) | proposed per-turn event (TEST_GUIDE 7.3) |
| `failures` | (day, call_id, seq) | proposed failure event (QUERY_AND_FAILURE_TAXONOMY part 4) |
| `gate_runs`, `asr_eval_runs`, `load_runs` | (sha, ts) | results from CI and tools |

Writes are idempotent on the key, so the collector can restart or re-read a file without double-counting (the call record already works this way: the clinic API applies an event only if its `seq` is higher than the last applied).

## 5. Build order

**Step 1: no change to the agent.**
* Collector scrapes `/api/stats` and `/api/health` every 15 s; tails the journal (redacted) and the `turn timing:` lines only.
* Panels you get: health now, tier mix (from `fast_path`/cache counters), re-ask and abstention mix, language mismatches, latency by language, safety zeros, call outcomes and scores.
* Panels you cannot get yet: the exact funnel, tier per turn, any failure view beyond re-asks.

**Step 2: structured events from the agent** (the agent change, small and local).
* Add the per-turn and `failure` events, written through the existing call recorder so they travel in the journal. Edit `main.py` and regenerate `main_pcm.py` with `tools/make_pcm_variant.py` (never edit `main_pcm.py` by hand). Put the event schema in an `agent/` module that does not import the orchestrator (CLAUDE.md one-import rule).
* Make every `except ToolCallError` that swallows record `tool_swallowed` with the tool name; record failed booking results (today only successes are recorded).
* Add a build identifier to `/api/health`.
* Add tests CF1 to CF28 from the taxonomy file; run `bash scripts/gate.sh --full`.
* Then stop scraping `pcm_app.log`.

**Step 3: join the offline results.** CI pushes `gate-report.json`; the evaluation tool pushes WER and entity tables; the release panel and the regression view come alive.

**Step 4: alerts.** Rules from TEST_GUIDE 7.5 on the stored series; page only on the "must be zero" rows and on S0/S1 bursts.

## 6. Things in the code that affect this

| Finding | Effect | Suggested handling |
|---|---|---|
| `call_id = uuid.uuid4().hex[:8]` (`main.py:1170`): 8 hex characters, 32 bits | at 6,000 to 7,000 calls a day, two calls on the **same day** collide roughly once every six months (birthday arithmetic: 6,500 calls gives about a 0.5% chance per day); across a month of about 200,000 calls, several colliding pairs are expected. `call_records.call_id` is `unique=True` and events merge by `seq`, so a collision would merge two different calls in the database. | key the dashboard by (day, call_id) now; lengthen the id in the agent when step 2 is done |
| `/api/stats` resets on restart and is per process | a restart looks like a drop to zero | store samples, compute deltas |
| Journal dates are clinic time, written at call end | a call that crosses midnight lands in the next day's file | store both timestamps; use the `start` event time |
| `/api/health` has no build or git sha | cannot slice or compare by build | add it |
| Notification provider is a placeholder (status `queued`) | the "message sent" rate would look perfect | label the panel "queued", not "sent" |
| The AEC mode, prompt variant and admission cap come from environment variables | needed as slice labels | publish them in `/api/health` |

## 7. Questions to answer before building

1. SQLite on `/workspace`, a second Postgres database, or Prometheus plus Grafana?
2. Who may see the dashboard (operations, engineers, the clinic owner, all)? The existing gateway uses one basic-auth password; per-role access would need more.
3. Should the agent log keep recognised text? That decides whether step 2 is optional or required.
4. Is it acceptable to lengthen `call_id` (a change that touches the agent, the journal file names, and the database)?
