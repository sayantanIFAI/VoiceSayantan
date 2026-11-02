# Call dashboard

A read-only screen for the voice agent. It shows, for a day, a week or a month:

* how calls ended (answered, booked, transferred, dropped, abusive or off-topic, in progress);
* **dropped in the middle**: why (left during a booking, went silent, left after being asked to repeat, ...);
* **transferred to a person**: who caused it (the caller asked, a rule or safety policy, the system could not cope) and the reason;
* **clarifying questions**: the times the AI asked the caller to repeat, by cause (noisy line, too quiet, other voices, ...);
* **bookings**: calls with a booking intent, how many were confirmed, and how many started with an enquiry;
* **the caller disagreed or something went wrong**: a correction at the read-back, a complaint, a request for a person, the language put right, a system error;
* a list of calls, filtered to "needs attention" by default. **Click a call to see what the caller said** (from the agent log, with the recogniser's
  agreement for each turn) **and what the agent recorded** (from the call journal).

## It changes nothing in the agent

No file under `agent/`, `main.py`, `main_pcm.py`, `clinic-api/`, `deploy/` or `tools/` is touched, and the dashboard does not import any of them. It reads
what the agent already writes:

| Source | Used for |
|---|---|
| `/workspace/call_journal/YYYY-MM-DD.jsonl`, `inflight/` (`CALL_JOURNAL_DIR`) | outcome, language, intents, re-asks, hand-off reasons, booking actions, the call score and its signals |
| `/workspace/call_archive/yyyy/mm/DATE.jsonl.gz` (`CALL_ARCHIVE_DIR`) | the same, for days the nightly archiver has already moved (read once, only if the day was not read from a journal) |
| `/workspace/logs/pcm_app.log`, `main_app.log` (`DASHBOARD_LOG_FILES`) | what the recogniser heard in each turn, and a few markers (empty recognition, emergency, abuse, hand-off, timeouts) |

It keeps its own SQLite file (`DASHBOARD_DB`, default `/workspace/dashboard/dashboard.db`). The deploy script starts the agent with `> logfile`, which empties
the log at every restart; copying the lines into this file as they appear is what keeps the transcripts after a restart.

## Run it

From the repository root (it needs only Python 3.11 or newer, no packages):

```bash
python3 -m dashboard --once     # read the agent's files once and print how many calls and log lines were found
python3 -m dashboard            # serve on http://127.0.0.1:8890/ and keep reading
python3 -m dashboard --demo     # made-up calls from a temporary folder, to see the screen before pointing it at the pod
```

## On the pod

The voice page (`static/pcm/index.html`, and `static/index.html`) has a small bar-chart icon at the top right that opens `/dashboard/` on the same address.
The gateway (`deploy/gateway/nginx.conf`) passes `/dashboard/` to the dashboard on `127.0.0.1:8890`, **behind the same login as the voice page**, and
`deploy/start_all.sh` starts the dashboard with the other services. To put an update on a running pod without restarting the voice agent:

```bash
cd /workspace/kolkata-care-voice-agent && git pull
cp deploy/gateway/nginx.conf /workspace/gateway/nginx.conf
bash /workspace/gateway/gateway.sh start        # reloads the running gateway (nginx -t first)
bash deploy/start_all.sh                        # starts only what is not already up: the dashboard
```

The static pages are read from disk, so the icon appears on the next page load. Anyone who can sign in to the voice page can open the dashboard and read
transcripts; give the dashboard its own login (a separate nginx password file for `/dashboard/`) if that is not what you want.

Elsewhere, reach it through an SSH tunnel to port 8890. To serve it on another address, set a user name and password; it refuses to listen on any
non-loopback address without them:

```bash
DASHBOARD_HOST=0.0.0.0 DASHBOARD_USER=ops DASHBOARD_PASSWORD=... python3 -m dashboard
```

Settings (all optional): `DASHBOARD_PORT` (8890), `DASHBOARD_POLL_S` (10), `DASHBOARD_TRANSCRIPT_DAYS` (30), `DASHBOARD_KEEP_TRANSCRIPTS` (`1`; set `0` to
store the recogniser's agreement and the markers but never the words).

## Privacy

* A transcript is whatever the caller said, so it can hold a name, a number or an address. It is shown only to someone who can reach the page, it is
  deleted from the dashboard's store after `DASHBOARD_TRANSCRIPT_DAYS`, and it can be switched off.
* From the journal it keeps the call's outcome and events, **not** the caller's phone (only its last four digits) and **not** the values the caller
  confirmed (name, phone, address); only the names of the fields are kept. `tests/test_dashboard.py` checks this.
* The agent log is not copied whole: only the lines the dashboard understands are kept.
* The access log of this server is switched off, because a request line can carry a call id.

## What it cannot show (and why)

* **The AI's own words.** The agent does not write them to any file. A call shows what the caller said and what the agent recorded, as two lists.
* **"Did you mean ...?" and "which one, A or B?" questions.** Not recorded, so the clarification count is the re-asks only.
* **A booking offered by the AI.** Not recorded. "An enquiry came first, then a booking" is the nearest count; it includes bookings the caller would
  have made anyway.
* **The caller saying "that is wrong".** There is no detector in the agent, so "went wrong" counts visible disagreement instead.
* **Speech-to-text accuracy.** That needs a human transcript to compare with (`tools/asr_eval.py`); see `docs/ASR_SCORING_AND_ERROR_CAPTURE.md`.

Showing any of the first three would need the agent to record one more event. That is a separate decision about the agent, and nothing here assumes it.

## Notes

* A call is identified by (day, call id), not by call id alone: the agent's ids are 8 hex characters, so the same id can come up on another day.
* The log's clock is the pod's clock and the journal's day is the clinic's (UTC+5:30), so a call near midnight is matched to the log within one day either way.
* `python3 -m pytest tests/test_dashboard.py` runs the tests; they use made-up calls and need no pod.
