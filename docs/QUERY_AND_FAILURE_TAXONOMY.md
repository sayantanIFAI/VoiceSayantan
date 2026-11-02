# What callers can ask, and how it can fail: query families and a contextual failure taxonomy

Written 2026-11-02 from the code on `main`. Companion to [TEST_GUIDE.md](TEST_GUIDE.md) (test layers, dashboard) and [DETERMINISTIC_THRESHOLDS.md](DETERMINISTIC_THRESHOLDS.md).

**What this file is based on.** Intent list, early-routing order, FAQ topics, phrase keys, API failure reasons and cue modules were read in the repo. The clinic data (9 departments, 34 lab tests, 36+ doctors) is **seeded dummy data** (`clinic-api/seed.py`); a real hospital's catalogue and call mix will differ. I have **no call logs**, so the families below are what the code is built to handle, not a measured distribution of what callers ask.

---

## Part 1. What can a caller ask?

The business is a diagnostics centre with doctors' chambers (OPD): lab tests and scans, doctors' sittings, booking, payment, reports. Callers range from first-timers to returning patients, are often elderly or anxious, and speak Bengali, Hindi, English or a mix.

"Route" says what decides the answer: **rule** (deterministic cue), **fast path** (deterministic matcher, may abstain), **model** (Ollama intent), **human** (hand-off), **fixed** (a fixed line, no lookup).

| # | Family | Example caller words | Route | Facts come from | Wrong-answer exposure |
|---|---|---|---|---|---|
| 1 | Test price | "CBC test koto?"; "uric acid ar cbc total koto hobe"; "remove that one" | fast path, model | lab test table | wrong test priced; partial list of several tests priced as the whole |
| 2 | Test preparation | "fasting lagbe?", "sample kothay dibo" | fast path, model | prep text per test | wrong prep for a similar test |
| 3 | Test availability and days | "do you do chest X-ray", "kon din hoy" | rule, fast path | lab test days | a day shown for a test the lab does not run |
| 4 | Rare or unlisted test or scan | "USG of the thyroid", "TB test" | rule, then human | none (by design) | pricing something the lab does not do |
| 5 | Body-part imaging | "buker chhobi korbo" (picture of my chest) | rule | catalogue test names | naming a scan the clinic lacks |
| 6 | Lay terms and prescriptions | "blood test", "I have a prescription" | rule | fixed lines, WhatsApp prescription route | guessing which blood test |
| 7 | Doctor sitting | "kalke boshbe", "aj achen?", "next Sunday", "if he is absent who sits" | rule, fast path, model | schedules, leave table | stale schedule, doctor on leave |
| 8 | Doctor facts | "which department", "fee", "is he good", "which floor", "sitting hours" | rule | doctor table | wrong fee or room |
| 9 | Who should I see | "chest pain", "chhuli", "my son has a rash", "head pain" | rule, clinician-approved keyword table, symptom lexicon | department routes | wrong department; a department the clinic does not have (see 3.4) |
| 10 | Book a doctor | "Dr Sen er appointment nebo" | model, then booking state machine | schedules, slots, bookings | double booking; booking for the wrong doctor; wrong phone |
| 11 | Book lab tests | "CBC and sugar test book korbo" | model, state machine | lab table, bookings | wrong test set; charge not confirmed |
| 12 | Change a booking | reschedule, cancel, look up, resend confirmation, add a test | model, state machine | bookings | wrong caller authorised; lock after 5 failures |
| 13 | Payment | "payment link pelam na", "cannot pay online", "pay at counter", "do I owe anything" | rule | payment records, fixed lines | stating a balance (never done: proof by WhatsApp and a callback) |
| 14 | Serial, token, arrival | "which serial is running", "my serial number", "when should I come" | rule | booking tokens, sitting start | wrong serial; wrong arrival time |
| 15 | Reports and results | "is my report ready", "show report to doctor", "what does my result mean" | rule, human | none (never guessed) | telling a result; guessing ready status |
| 16 | Clinic FAQ | hours, location, payment methods, insurance, parking, report collection, contact number, home collection | fast path, model | FAQ table (8 topics) | wrong hours; "insurance" answer for a health-package question |
| 17 | Owner-dictated answers | "is this Sonoscan?", Swasthya Sathi, distance from Sealdah, token rule | rule | fixed text, `CLINIC_BRANCH` setting | wrong branch |
| 18 | Own history (verified) | "when did I last do my CBC", "what tests have I had", "my next appointment", "what medicine was I given" | rule, then security questions | patient record | disclosing to the wrong person |
| 19 | Reach a person | "talk to someone", "I want to complain", "connect me to the doctor", lost property, a referral from another centre | rule, human | none | missing the request |
| 20 | Emergency and distress | chest pain, can't breathe, bleeding, frightened voice | rule | fixed notice | a miss (recall over precision by design) |
| 21 | Conversation control | "say again", "speak Hindi", "spell that", "what day is today", thanks, goodbye, silence, swearing, wrong number, small talk | rule | none | language flipped without being asked |
| 22 | Several things in one sentence | price and sitting in one breath; a correction ("no, Friday") | model, rule | as above | one question dropped |

The model-resolved intents are exactly 15 (`test_rate`, `doctor_availability`, `book_appointment`, `test_prep`, `clinic_faq`, `smalltalk`, `unclear`, `book_test`, `reschedule_appointment`, `cancel_appointment`, `lookup_booking`, `add_test_booking`, `resend_confirmation`, `department_query`, `repeat_last`). Everything else in the table is decided by rules **before** the model (`agent/early_routing.py` fixes the order: person, doctor-direct, complaint, link missing, cannot pay online, pay now, dues, health package, rare test, report pickup, referral, quality reassurance, good doctor, day availability, doctor weekdays, next-if-absent, sitting hours, when to come, and so on).

**What a hospital would add that the code does not obviously cover** (questions for the owner, not findings): pharmacy or medicine stock, admission and ward enquiries, ambulance, blood-bank availability, discharge summary, insurance pre-authorisation. The Blueprint scope may exclude them; confirm.

### Booking "induced" (definition agreed 2026-11-02)

A booking is **induced** when the agent **offers** one after answering a question, and the caller **accepts**. A booking the caller asked for from the start is **requested**, not induced. The code already makes such offers: `main.py` sets `session.dept_pending` with kind `confirm_one` ("do you want an appointment with Dr X?") or `pick` (a choice among the doctors sitting today) in `_finish_enquiry_turn`, and a next-sitting offer through `_next_sit_offer`. Nothing records the offer or its outcome today.

| Event (proposed) | When |
|---|---|
| `booking_offered` | the agent sets `dept_pending` or a next-sitting offer; payload: kind (`confirm_one`, `pick`, `next_sitting`), the question that led to it (intent only) |
| `booking_offer_accepted` | the caller's next turn answers yes or picks a doctor, and the booking flow starts |
| `booking_offer_declined` / `booking_offer_ignored` | a no, or a turn on another subject |
| `booking_confirmed` | the existing `action` event, in the same call |

Reported as: offered, accepted (share of offered), confirmed (share of accepted), and compared with requested bookings.

---

## Part 2. What is recorded about failures today

I read how a call is recorded. This is the gap the new view has to close.

| Fact (checked in the code) | Consequence |
|---|---|
| The call record has these event kinds: `start`, `language`, `intent`, `action`, `confirmed`, `history`, `patient`, `satisfaction`, `escalation`, `reask`, `end`. | There is no `failure` event. |
| `_record_action` writes an `action` event **only when `result["success"]`** (`main.py:2133`). | A failed booking, change or cancel (`slot_taken`, `hold_expired`, `phone_mismatch`, `locked`...) leaves **no event**. I found no counter for them either. |
| The `reask` event is written for a re-ask (reason and action) and for a spoken `llm_failure` or `tool_failure`. | It does not say **which tool**, which flow step, or which intent. |
| `main.py` has 76 handlers for `ToolCallError`: 32 are bare `except ToolCallError:`, 8 are `contextlib.suppress(ToolCallError)`, 36 bind the error (counted by pattern, so treat as approximate). | At least 40 places swallow a failed data fetch **with nothing recorded** (many are deliberate "advisory" lookups, but nothing counts them). |
| Language ID failures are logged (`LID failed`, `ASR <lang> failed`) and the result becomes `unknown`. | There is no event; the `language` event holds only the final language. |
| `/api/stats` counters: `reask_outcomes`, `insufficient_information`, `abstentions`, `language_mismatches`, `apology_events`, `audio_issue_buckets`, `barge_in_interrupts`. | Counted by reason, intent and language, but **not tied to a call or a task step**, and reset on restart. |
| The call score counts `reasks`, `system_failures`, `language_flips`, `corrections`, `left_mid_task`... | A number per call; it cannot say which stage failed. |

---

## Part 3. A contextual failure taxonomy

A **contextual** failure record says not only *what* broke but *what the caller was trying to do* when it broke and *what happened to them next*.

### 3.1 Classes (what kind of failure)

| Class | Meaning | Example |
|---|---|---|
| **Fault** | a component broke | Ollama timeout, clinic API 5xx, TTS down |
| **Miss** | the system could not understand | empty ASR, garbled transcript, `unclear` intent |
| **Abstention** | the system was unsure and chose to ask | fast path between its floors, did-you-mean, low-confidence withheld |
| **Business negative** | a correct "no" from the clinic | slot taken, doctor not sitting that day, test not found |
| **Policy refusal** | a rule blocked it | unverified write, change lock, booking beyond 3 days |
| **Wrong path** | it understood the wrong thing, then recovered | Hindi label on a Bengali call, wrong tier, language flip |
| **Silent degradation** | something failed and nobody was told | a swallowed `ToolCallError`, a stale cache served |
| **Safety event** | needs a human or a review | emergency, clinical interpretation, a reply that contradicts the API |

### 3.2 Severity (what it cost the caller)

| Level | Meaning |
|---|---|
| S0 | a wrong or unsafe thing was said or done (a wrong fact, a missed emergency, a write for the wrong person) |
| S1 | the task was lost (abandoned, handed off because the system failed, booking not made) |
| S2 | the task was delayed (re-ask, retry, filler, second attempt) |
| S3 | invisible to the caller but degraded (stale cache, swallowed lookup, fallback used) |
| S4 | informational (business negative that the caller accepted) |

### 3.3 Codes by stage, with what is visible today

"Seen" = how a failure shows today: **counter** (in `/api/stats`), **event** (call record), **log** (text only), **none**.

**Audio and turn**

| Code | Class | Seen | Recovery the caller gets |
|---|---|---|---|
| `asr_empty` | Miss | event + counter (reask) | kind re-ask, handoff after 2 |
| `audio_too_quiet`, `audio_noisy`, `audio_crosstalk`, `audio_mumbled` | Miss | event (reask reason) + counter | a re-ask that names the cause (`reask_low_volume` ... ) |
| `background_voice_dropped` | Abstention | counter | gentle re-ask; the other voice's words are not used |
| `speaker_changed` | Policy refusal | log | verification revoked, re-verify |
| `ingress_overrun` | Fault | log + outcome `audio_overrun` | hand-off to a person |
| `silence_timeout` | Miss | outcome | "hello?" up to 3 times, then goodbye |

**Language**

| Code | Class | Seen | Recovery |
|---|---|---|---|
| `lid_exception` | Fault | log | treated as unknown; recognisers decide |
| `lid_unknown` / `lid_low_confidence` | Abstention | log | previous language used, or top-two recognisers |
| `lid_ambiguous_streak` (4th in a row, no prior) | Miss | log | hand-off |
| `hi_label_on_bn_audio` (Bengali called Hindi) | Wrong path | log only | Bengali reading wins when its agreement is high enough |
| `en_label_on_indic_audio` / `indic_label_on_en_audio` | Wrong path | log only | English overrule rules |
| `reply_language_flip` (unrequested) | Wrong path | counter (`language_flips` in score) | the call stays in its language |
| `reply_language_mismatch` | Safety event | counter | logged as an error |
| `switch_false_positive` ("English Bazar") | Wrong path | none | dropped while the address is asked |
| `unroutable_language` | Fault | log | no recogniser registered |

**Understanding**

| Code | Class | Seen | Recovery |
|---|---|---|---|
| `llm_unreachable`, `llm_deadline`, `llm_bad_json` | Fault | event (`llm_failure`) | doctor booking still recognised from the catalogue; else apology |
| `intent_unclear` | Miss | counter | "didn't understand"; third in a row escalates |
| `fastpath_abstained` / `fastpath_vetoed` | Abstention | counter (`abstentions`) | model decides |
| `low_confidence_withheld` | Abstention | counter (`insufficient_information`) | "please say that again" |

**Grounding**

| Code | Class | Seen | Recovery |
|---|---|---|---|
| `entity_not_found` (doctor, test) | Business negative | none | not-found reply, never a guess |
| `entity_ambiguous` | Abstention | none | "which one, A or B?" |
| `did_you_mean_declined` | Abstention | none | asks again |
| `multi_test_shortfall` (fewer tests understood than said) | Miss | none | "I caught A and B, tell me all names again" |
| `department_dropped` (symptom word maps to a department the clinic has no row for) | Silent degradation | none | looks the same as "symptom not understood" (3.4) |

**Data fetch**

| Code | Class | Seen | Recovery |
|---|---|---|---|
| `tool_timeout` (4 s) | Fault | event if spoken; **none** if swallowed | `tool_failure` apology |
| `tool_http_5xx` | Fault | same | same |
| `tool_bad_shape` (`ApiShapeError`) | Fault | log | treated as tool failure, not "not found" |
| `tool_swallowed` (advisory lookup failed) | Silent degradation | **none** | feature quietly missing for that turn |
| `catalogue_fetch_failed`, `static_answers_stale` | Fault / Silent | log | previous copy served |
| `availability_cache_stale` (120 s agent cache, 20 s schedule cache) | Silent degradation | none | an older sitting shown |
| `db_unavailable` | Fault | log | API fails closed |

**Booking and changes** (API `reason` values found in `clinic-api`)

| Step | Reasons | Class | Seen |
|---|---|---|---|
| Doctor | `doctor_not_found`, `doctor_ambiguous` | Business negative / Abstention | none |
| Date and time | `invalid_date`, `date_in_past`, `too_far_ahead`, `doctor_not_available_that_day`, `invalid_slot`, `book_on_the_day` | Business negative | none |
| Hold | `slot_taken`, `hold_expired`, `already_booked` | Business negative | none |
| Who is asking | `phone_required`, `phone_mismatch`, `no_phone_on_file`, `not_authorized`, `not_verified`, `write_unverified`, `cannot_verify`, `locked`, `too_many_attempts`, `rate_limited` | Policy refusal | handoff reason only for `unverified_booking_write` and `verification_*` |
| Tests | `unknown_test`, `test_not_found`, `no_valid_tests`, `sample_type`, `charge_confirmation_required`, `area_not_covered` (home collection) | Business negative | none |
| Payment and reports | `not_paid`, `not_ready`, `otp_invalid_or_expired` | Business negative | none |
| Generic | `not_found`, `missing_field`, `invalid_text`, `invalid_key_or_language` | mixed | none |

**Reply and speech**

| Code | Class | Seen | Recovery |
|---|---|---|---|
| `unspeakable_span` | Fault | log (error) | recorded fallback WAV |
| `tts_failure` | Fault | log | recorded fallback WAV |
| `stale_reply_discarded` (caller barged in) | Wrong path | log | rest of reply dropped |
| `apology_stacked_removed`, `question_dropped` | Wrong path | counter (`apology_events`) | text trimmed before speaking |
| `humanize_rewrite_discarded` | Wrong path | none | original sentence kept |
| `gate_backstop_release` (no `playback_done`) | Fault | log | gate released at the deadline |

**After the call**

| Code | Class | Seen |
|---|---|---|
| `record_events_unflushed` | Fault | log (error) |
| `journal_write_failed`, `archiver_failed` | Fault | log |
| `draft_not_saved`, `callback_not_queued` | Fault | none found |
| `notification_queued_only` (SMS/WhatsApp provider is a placeholder) | Silent degradation | status "queued" in the outbox |

### 3.4 One finding to check

`clinic-api/symptom_lexicon.py` holds **16** departments (adds General Surgery, Neurology, Neurosurgery, Urology, Gastroenterology, Psychiatry, Ophthalmology). The seed has **9**. In `route_department`, a lexicon department that has no row in the database is dropped (`if n in by_name_lex`). So with the seeded data, "I get fits" or "eye pain" produces `matched: False`, the same as a symptom nobody understood, and the caller is defaulted to General Medicine. With a real catalogue this may not happen; it should be a named failure code (`department_dropped`) so it can be seen.

---

## Part 4. The contextual failure record (proposed)

One event kind, `failure`, written to the same call record, with **no free text and no personal data**:

```json
{ "call": "...", "turn": 7, "ts": "...", "build": "<git sha>",
  "stage": "booking.confirm",
  "code": "slot_taken",
  "class": "business_negative",
  "severity": "S2",
  "component": "clinic-api",
  "attempt": 1,
  "task": { "kind": "book_appointment", "step": "confirm", "turns_in_task": 9,
            "slots_filled": ["doctor","date","time","name","phone"], "slots_missing": [] },
  "context": { "intent": "book_appointment", "tier": "model", "lang_heard": "bn", "lang_reply": "bn",
               "lang_locked": true, "channel": "narrowband_8k", "asr_agreement": 0.91,
               "lid_top": "bn", "lid_conf": 0.97, "caller": "returning_verified",
               "api": {"tool": "confirm_booking", "http": 200, "ms": 118, "reason": "slot_taken"},
               "hold_age_s": 412 },
  "recovery": "alternatives_offered",
  "outcome": { "recovered_within_turns": 2, "final": "booked" },
  "chain": "c-8f2" }
```

Design points:
* **`stage` and `code` come from fixed lists** (Part 3.3) so they can be counted and tested.
* **`task`** is the contextual part: what the caller was doing, how far in, what was missing.
* **`recovery`** is what the caller experienced (re-ask, alternatives, apology, fallback audio, hand-off, nothing).
* **`outcome`** is filled in later (when the task ends), so the dashboard can say whether a failure was fatal.
* **`chain`** links failures that came from one root cause (for example `lid_low_confidence` then `reply_language_flip` then `asr_empty` then `handoff`).
* **Silent degradation** gets a record too: every `except ToolCallError` that swallows must emit `tool_swallowed` with the tool name. This is the cheapest change with the largest visibility gain.
* This is an observability event, not a fact source: it does not touch CLAUDE.md rule 1.

---

## Part 5. Dashboard views for failures

Added to the layout in TEST_GUIDE section 7:

| View | Answers | Built from |
|---|---|---|
| **Failure funnel** | At which stage do failures occur, which code, and what recovery followed? | `failure` events by stage, code, recovery |
| **Context heatmap** | Where does one code concentrate? Code (rows) by language, channel, intent, flow step, caller type, hour, build | `failure.context` |
| **Task rescue** | Of tasks that hit a failure, how many were recovered, handed off, abandoned; how many turns were lost | `failure.outcome` |
| **Booking board** | Step-by-step drop-off (doctor, date, time, name, phone, read-back, hold, confirm, payment) with the API reason at each step | `failure` where `task.kind` is a booking, plus `action` events |
| **Language board** | Heard-versus-reply confusion matrix, flips, offers made and accepted, wrong-language replies, LID versus recogniser disagreement, with decoder-agreement bands | `language` events, `failure` where `stage` starts `language` |
| **Data-fetch board** | Per tool: calls, p50 and p95, timeouts, 5xx, bad shape, retries, stale-cache serves, **swallowed errors** | `failure` where `stage` starts `data` |
| **Cascade view** | One chain drawn as a path: root cause then each consequence | `failure.chain` |
| **Silent-failure meter** | The count of `tool_swallowed`, which should trend down as handlers learn to speak | `tool_swallowed` |

Alert ideas (proposals): any S0; `tool_http_5xx` or `tool_timeout` above 1% of calls to one tool; `slot_taken` above its weekly norm (a cache or hold-time problem); a language pair whose reply-flip rate is twice the others; a new code appearing after a deploy; any rise in `tool_swallowed`.

The mockup next to this file shows the failure views with invented numbers.

---

## Part 6. Test cases for contextual failure

For every query family in Part 1, inject each applicable fault and assert **four things**: the spoken line is the right kind, no fact is invented, the flow state is not corrupted, and a `failure` event with the right `stage`/`code`/`task` is written (the last assertion needs Part 4 to exist).

| ID | Fault injected | Query family | Expected spoken line | Flow state | Event |
|---|---|---|---|---|---|
| CF1 | clinic API times out (4 s) | 1 test price | `tool_failure` apology, no price | unchanged | `data.tool_timeout`, tool `get_test_rate` |
| CF2 | clinic API returns an HTML page | 1 | `tool_failure`, **not** "not found" | unchanged | `data.tool_bad_shape` |
| CF3 | API says test not found | 1 | not-found line | unchanged | none (business negative, optional S4) |
| CF4 | two tests tie within 0.2 | 1 | "which one, A or B?" | pending entity set | `grounding.entity_ambiguous` |
| CF5 | three tests said, two understood | 1 | asks for all names again | nothing priced | `grounding.multi_test_shortfall` |
| CF6 | ASR agreement 0.40 | 1, 7 | insufficient-information line, no lookup | unchanged | `understanding.low_confidence_withheld` |
| CF7 | Ollama down | 10 book a doctor | doctor still recognised from catalogue, or `llm_failure` | booking continues or restarts cleanly | `understanding.llm_unreachable` |
| CF8 | slot taken between hold and confirm | 10 | alternatives offered | no booking row | `booking.confirm / slot_taken` |
| CF9 | hold expired (900 s) | 10 | recovery line | no booking without a hold | `booking.hold / hold_expired` |
| CF10 | date beyond the 3-day window | 10 | window stated | date cleared | `booking.date / too_far_ahead` |
| CF11 | doctor not sitting that day | 10, 7 | next sitting offered | date cleared | `booking.date / doctor_not_available_that_day` |
| CF12 | caller phone differs from the booking | 12 change | refused | unchanged; counter +1 | `booking.change / phone_mismatch` |
| CF13 | fifth failed change | 12 | locked for 15 minutes | locked | `booking.change / locked` |
| CF14 | booking write while unverified | 10 | handoff | unchanged | `booking.write / write_unverified` |
| CF15 | same write retried with the same key | 10 | one booking | one row | none; idempotent replay counted |
| CF16 | LID throws | any | normal reply | n/a | `language.lid_exception` |
| CF17 | Bengali audio labelled Hindi 0.98 | 1 | Bengali reply | language unchanged | `language.hi_label_on_bn_audio` |
| CF18 | accented English labelled Hindi | any | English reply | language per rules | `language.en_label_on_indic_audio` |
| CF19 | four ambiguous first turns | any | handoff | n/a | `language.lid_ambiguous_streak` |
| CF20 | caller says "English Bazar" during the address | 10 | stays in language | address captured | `language.switch_false_positive` (suppressed) |
| CF21 | symptom for a department with no row | 9 | General Medicine default | n/a | `grounding.department_dropped` |
| CF22 | TTS server down | any | recorded fallback WAV | unchanged | `speech.tts_failure` |
| CF23 | reply has a Latin span | any | fallback WAV, error log | unchanged | `speech.unspeakable_span` |
| CF24 | caller barges in mid reply | any | rest discarded | unchanged | `delivery.stale_reply_discarded` |
| CF25 | advisory lookup fails (any of the 40 swallow sites) | various | reply as before | unchanged | `data.tool_swallowed` with tool name |
| CF26 | postgres down | 10, 12 | fails closed | unchanged | `data.db_unavailable` |
| CF27 | journal disk full | any | call continues | n/a | `after.journal_write_failed` |
| CF28 | three failures in one booking, then success | 10 | n/a | booked | one `chain`, `outcome.final = booked` |

---

## Part 7. Things to settle with the owner

1. **Real catalogue.** The department, test and doctor lists here are seed data. The query mix and the `department_dropped` finding depend on the client's real database.
2. **Query mix.** The nightly journals hold intents per call. Pull one week to rank the families in Part 1 by volume before sizing the dashboard.
3. **Hospital scope.** Are pharmacy, admission, ambulance or blood-bank questions in scope? Today they would end as `unclear` or `smalltalk`.
4. **Swallowed lookups.** Which of the 40 swallow sites are truly optional? Each should at least count itself.
5. **Failure event retention.** The failure record is free of names and phone numbers by design; confirm that policy before adding fields like the doctor's name.
