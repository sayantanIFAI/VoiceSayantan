# Four gaps: numbers, English in Bengali, addresses, latency

Written 2026-11-03 from the pod's last 7 clinic days (28 Oct to 3 Nov) and the code at `fc82dae`. Every figure below was computed on the pod from its own logs, call journal, Ollama log and dashboard database. Nothing here was invented; where the data cannot answer, it says so.

## 0. Read this first: what the data can and cannot tell you

| | |
|---|---|
| Window | 32 agent log files, **473 calls, 1,592 recognised turns** |
| One day is a load test | **29 Oct: 320 calls, up to 64 at once** (ADR 0002 / 0005 capacity rounds). It is reported separately and left out of every "normal" figure below. |
| The "normal" sample is small | 5 quiet days (30 Oct to 3 Nov): **153 calls, 478 timed turns, 480 recognised turns**. Many of these are probably your own testing; the logs cannot tell a tester from a patient. |
| No ground truth | There are no human transcripts of what callers really said. So **accuracy cannot be computed** for numbers, English words or addresses. What follows are proxies (what the agent could and could not read) and timings, which are exact. |
| Privacy | Only counts and the shape of data are shown. No caller words, numbers or addresses are quoted. |

**The headline in one table**

| Gap | What the data says | Your question | Verdict |
|---|---|---|---|
| 1. Numbers | 30 phone-number utterances in 7 days; 18 gave exactly 10 digits, 11 gave fewer, 1 gave more. The recogniser was confident (median agreement 0.99) while digits went missing. Not one stray word was close to a digit word. | Dictionary? | **No: it already has one (102 digit-word forms, 220 two-digit forms, "double/triple"). The loss is in the recogniser, not the vocabulary.** Fix the process, not the word list. |
| 2. English in Bengali | Rare in this data: 1 of 1,331 Bengali turns had Latin words; 8 (0.6%) were English function words in Bengali letters; 3 were Hindi. 0 replies were blocked as unspeakable. | Phonetics or English equivalent? | **Neither is a priority on this evidence.** Grow the existing lists from observed errors, not from guesses. |
| 3. Addresses | The place tables are small (23 districts, 47 police stations, 15 subdivisions/blocks, 28 places) and were not used at all this week (0 lookups). 38 booking calls, 5 confirmed, 31 dropped mid-booking: the step is unknown. | API or dictionary? | **A local dictionary built from open data, plus the PIN code. Not an outside API** (data residency). But first find out where bookings are lost. |
| 4. Latency | First audio: p50 0.7 s, p95 2.0 s. The caller also waits ~1.7 s of silence before processing starts. **The model (intent) leads 88% of slow turns. End-of-speech waiting is the biggest single piece of what the caller feels.** | Deep investigation | Findings and a ranked plan in section 4. |

---

## 1. Numbers

### What the data shows

* **30** utterances carried 3 or more digits (all on quiet days).
* Digits read per utterance: **exactly 10 → 18 (60%)**; fewer than 10 → **11** (1 missing: 4; 2 missing: 4; 3 missing: 2; 4 missing: 1); more than 10 → 1.
* **Median decoder agreement 0.99.** The recogniser was sure of itself in the cases where digits were lost, so the agreement score cannot warn the agent.
* Of the 12 that did not give 10 digits: **3 had no stray words at all** (the digits are simply absent from the text), 3 had one stray word, 6 had two or more (24 stray words in total). **None of the 24 stray words is within 0.7 similarity of any known digit word**, so a fuzzier dictionary would have recovered none of them.
* Script: 25 written in Bengali letters, 3 in Latin (English), 2 in Devanagari. 4 used "double/triple". No digits were written as numerals.
* A caution on the 11 short ones: the booking flow keeps a partial number and asks for the rest (`phone_buffer`), so a 7 to 9 digit utterance is a partly captured number, not necessarily a failure. The data cannot say how many were completed.

### What exists already

102 digit-word forms (`booking_capture._DIGIT_WORDS`), 220 two-digit number words in Bengali and Hindi (`number_words.TWO_DIGIT`), "double/triple/five nines", Devanagari and Bengali numerals, a read-back in groups (`spoken_codes`, `figures`), and a "how many digits did I hear?" re-ask.

### Could do / should do

| Idea | Could it work? | Should we? |
|---|---|---|
| A bigger or fuzzier digit dictionary | The data says no gain: 0 of 24 stray words were near a digit word, and 3 of 12 failures have no stray words at all. | **No.** |
| **Use the number the caller is calling from** (phone calls) | The phone bridge already receives it from Twilio (`form.get("From")`, `twilio_bridge.py:620`) and uses it only for the allow-list. Offer "shall I use the number you are calling from?" and take a yes. Removes the problem for most callers. | **Yes, first.** Small change, large effect. Needs your decision on privacy and on callers who book for someone else. |
| Take the other decoder's text for digits | Each turn already carries the CTC text beside the RNNT text (`ASRResult.alternatives`). When RNNT gives fewer than 10 digits and CTC gives 10, use CTC. | **Test it offline first** on a labelled set; do not switch it on blind. |
| Ask for the number in two parts (5 + 5) | Shorter utterances lose fewer digits. | Cheap to try; measure first. |
| Keypad (DTMF) entry on phone calls | Twilio media streams can deliver keypad presses; to be confirmed in Twilio's documentation. | Worth a spike for the cases where speech keeps failing. |
| Measure it properly | Needs about 200 labelled number utterances (human transcript of the digits). | **Yes**: without it every change above is a guess. |

---

## 2. English words in Bengali

The wording is ambiguous, so both directions are covered.

### Caller says English words (recognition)

* 1,331 of the 1,592 recognised turns were labelled Bengali. **Only 1 contained Latin-script words.** 8 (0.6%) were English function words in Bengali letters ("is there", "who", "sit"), already caught by `english_in_bengali`; 3 were Hindi in Bengali letters, caught by `hindi_in_bengali`. 63 turns were labelled English.
* The English recogniser's reading was compared with the Bengali one in 1,073 turns (the safety net is used constantly, at a GPU cost).
* **What the data cannot see:** an English *noun* ("blood", "report", "X-ray", a test name) that the Bengali recogniser writes in Bengali letters looks like an ordinary Bengali word. Counting those needs a human transcript.
* A related, measurable signal: **7.7% of intent decisions were "unclear"** (21 of 272) and 13 of 161 calls ended on an unclear turn. That is every cause of misunderstanding together, not English alone.
* What exists: catalogue aliases and loan-word names per test (`synonyms_extra`, `catalogue_forms`), sound folding (`gazetteer`), spelled-letter recovery ("সি বি সি" → CBC, `spelled_letters`).

### Agent says English words (speech)

* 0 replies were blocked as unspeakable in the 7 days. The voice drops Latin letters, so every English word in a reply needs a Bengali or Hindi rendering: `pronunciation._ENTRIES` holds **81** curated words, `bn_respell` has **41** rules, acronyms are spelled letter by letter, and the English "WhatsApp" is a recorded clip.

### Could do / should do

| Idea | Verdict |
|---|---|
| **Generate phonetic variants automatically** (a transliteration model) to widen the alias tables | Could work for *listening*, because every variant still maps only to a catalogue entry and stays a suggestion that needs a "yes" (the truth rule). Validate each batch by ear or against real pairs. **Only after the data shows English terms are a real source of errors.** |
| Generate pronunciations automatically for the *voice* | **No.** `pronunciation.py` is explicit that a guessed pronunciation of a medical term is worse than a blocked reply. Keep it curated; extend the 81 entries from the replies the agent actually speaks. |
| Replace English terms with Bengali equivalents in replies | Already how templates are written (`test_name_bn`). Keep it that way. |
| **Learn from errors, not guesses** | **Yes.** The agent now logs what it said and what it heard. Build the wrong-word list described in `ASR_SCORING_AND_ERROR_CAPTURE.md` and feed the top 50 confirmed pairs into the alias tables. |

Priority: **low** this month, on this evidence.

---

## 3. Addresses

### What the data shows

* The place tables hold **23 districts, 47 police stations, 15 subdivisions/blocks and 28 places** (`clinic-api/geo_data.py`). The district layer is complete for West Bengal; the police-station and place layers are small.
* The matcher is careful by design: only answers of 3 words or fewer are looked up, only a district or police station is ever suggested (score 0.55 or more), a sound-alike is trusted only above 0.78 (the code calls this "reasoned, not measured"), and an exact written match is accepted.
* **This week it was not exercised:** 0 address-lookup requests and 0 failures in the clinic API log since its last restart. The accuracy of address recognition therefore cannot be measured from this data.
* Booking funnel on the quiet days: **38 calls with a booking intent, 5 confirmed (13%), 31 dropped mid-booking (82%).** All 5 confirmed bookings carry an address. Dropped calls had between 1 and 11 intent turns; the step where they left is not recorded. These include testers, so the 82% is not a patient figure, but it is the biggest number in this report.

### API or dictionary?

| Option | For | Against |
|---|---|---|
| A map/geocoding API (Google or similar) | Widest coverage, little code. | Sends spoken addresses out of India (HANDOVER section 10 already flags data residency as a past problem), costs per call, adds 100 to 300 ms, and needs the caller's consent. **Not recommended.** |
| **A local dictionary from open data** | Stays on the pod. India Post's PIN-code directory (open government data) and an OpenStreetMap extract of West Bengal (many places have Bengali names) give far more places than 28. Fits the existing matcher and its "a sound-alike is only a suggestion" rule. | Needs cleaning, Bengali names for smaller places are patchy, and it must be refreshed. |
| **Ask for the PIN code** | Six digits, spoken as digits, which the number reader handles. One PIN narrows to a post-office area. | Callers do not always know it. |

### Should do

1. **Find out where bookings are lost first.** With the new `said` lines in the log, the booking step at hang-up can be read from the last question the agent asked. A week of that settles whether the address step matters.
2. Ask only for what the clinic needs. If a district or police station is enough, stop at that; read it back.
3. Extend the local gazetteer from the PIN directory and OSM for Kolkata and the nearest districts, then measure on real answers.
4. Accept a PIN as an alternative to a spoken address.

---

## 4. Latency: the deep investigation

### 4.1 Method

Per-turn timings come from the agent's `turn timing:` log line (start of turn to first audio, in consecutive slices). Quiet days only (478 turns); the load day is separate. The caller-felt wait adds the end-of-speech silence, from the `endpoint:` line the latest release added (8 samples so far, all today).

### 4.2 Where the time goes (quiet days, milliseconds)

| Step | n | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| Clean-up | 478 | 7 | 32 | 50 | 79 |
| Language ID | 478 | 31 | 60 | 843 | 6,351 |
| Recognition (wait after language ID) | 478 | 243 | 467 | 652 | 687 |
| **Understanding (intent)** | 258 | **680** | **1,327** | 1,869 | 2,491 |
| Lookups and wording | 478 | 201 | 408 | 977 | 12,330 |
| Speech synthesis | 478 | 50 | 131 | 301 | 1,902 |
| Hand to line | 478 | 14 | 55 | 96 | 158 |
| **First audio (total)** | 478 | **715** | **2,003** | 6,585 | 12,719 |

* **91%** of turns are over the 0.5 s target, **36%** over 1 s, **17%** over 1.5 s.
* **88% of slow turns (72 of 82) are led by the intent stage.** Excess time over a normal turn: lookups and wording 23%, intent 18%, language ID 6%.
* Only 258 of 478 turns reach the intent stage at all; 220 are answered by earlier guards and routes.
* The model is the lever. Marked tiers: cache p95 0.93 s, fast path 1.24 s, rule 6.9 s (13 turns, dominated by outliers), model 1.89 s, unmarked ("other", mostly the model) **2.0 s with intent p95 1.38 s**.
* Day by day (p50 / p95, ms): 30 Oct 896 / 1,878; 31 Oct 662 / 1,895; 2 Nov 616 / 1,423; 3 Nov 825 / 2,595.

### 4.3 The model server (Ollama, all 7 days)

* `generate`: 165 requests, **p50 0.95 s**, p95 5.3 s excluding three cold loads over 20 s (the slowest 87 s; the known cold-start defect, `HANDOVER.md` defect 2). `embed`: p50 0.18 s, but p95 11 s from cold loads.
* The same intent call measured **311 ms median** on 25 Oct (`agent/llm.py`) and runs at **680 ms** in production. Something costs about 2x. The commit made on the pod today (Ollama evicting the loaded model because one call used a different context size) is a likely part; the GPU is also shared with recognition and speech. Needs the load sampler (`tools/loadtest/sampler.py`) during real use to settle.

### 4.4 What the caller actually feels

The pipeline starts only after the system decides the caller has finished. The new log line shows the wait: **8 samples, silence waited p50 1.7 s, p95 2.0 s** (needed 1.2 to 2.0 s). Settings in force are the code defaults: 0.45 s after a bare yes/no or a whole phone number, 1.2 s after a finished-looking sentence, 2.0 s otherwise, 3.5 s after an unfinished one.

> **Felt delay ≈ 1.7 s of waiting + 0.7 s of processing ≈ 2.4 s median, about 4 s at p95.** The silence wait is roughly 70% of the median, larger than the whole pipeline. n = 8, so treat it as a first reading, not a result; a week of the new line will give the real distribution.

### 4.5 Under load (29 Oct, 959 timed turns, up to 64 calls at once)

p50 **5.2 s**, p95 15.8 s, 86% of turns over 1.5 s. Language ID and recognition stay fast; recognition (the wait after LID) goes to p50 1.3 s and intent to 1.6 s. The configured cap is now 30 calls and has not been re-tested at that level since.

### 4.6 Measurement problems found

* **"Clinic API: 0 calls 0 ms" on every one of the 2,189 turns since the log line was added**, although the lookups and wording stage takes 200 ms (p50) to 12 s. The counter or its hook is not recording, so the lookups stage cannot be split into API time and wording time. Four turns had a lookups stage over 1 s, up to 12.3 s. They cannot be explained from the logs.
* One language-ID call took **6.4 s** (p50 is 31 ms): worth a look for CPU contention.
* The recognisers' whole time (they run in parallel with language ID; 7 days, calls that began with fewer than five others, so a little load-day tail is included): Bengali p50 196 ms / p95 653 ms, Hindi 212 / 668, **English 270 / 1,616**. English is the slow one.

### 4.7 Ranked plan

| # | Action | Expected effect | Effort | Evidence |
|---|---|---|---|---|
| 1 | **Measure the end-of-speech wait for a week** (already logged) and tune it by question type; the latest release has the switches (kill files). Aim to take 0.3 to 0.5 s off finished-looking sentences without raising false cut-offs (`tools/calibrate_endpointing.py`). | Largest felt gain, ~0.5 s | Low (data) then medium | 4.4 |
| 2 | **Answer more turns without the model**: widen the fast path, cache and rules; the model is 88% of slow turns and each avoided call saves about 0.7 s. | 0.7 s on every turn moved | Medium, continuous | 4.2 |
| 3 | **Find why the intent call is 2x its measured speed**: eviction (fixed today), GPU sharing, prompt length, parallelism. Consider a smaller or quantised model after an accuracy test (`tools/intent_ab.py`). | Up to 0.3 to 0.4 s | Medium | 4.3 |
| 4 | **Fix the clinic-API timer** so the lookups stage can be explained, and add a readiness gate so no call reaches a cold model. | Visibility; avoids cold hits of 20 to 87 s | Low | 4.6, 4.3 |
| 5 | Re-test capacity at the cap of 30 calls; keep admission control closed beyond it. | Protects p95 at peak | Medium | 4.5 |
| 6 | Look at the English recogniser's p95 of 1.6 s and the 6.4 s language-ID outlier. | Tail only | Low | 4.6 |

---

## 5. What I recommend, in order

1. **Latency step 1 and the caller-ID default (numbers).** Both are small, both are measurable within a week, both give the biggest felt change.
2. **Find the booking step where callers leave** (next 7 days of `said` lines). It decides whether addresses or numbers matter more.
3. **Build a labelled set** (about 200 number utterances and 200 mixed utterances with a human transcript) so numbers, English words and addresses can be measured instead of argued. The plan and the consent question are in `ASR_SCORING_AND_ERROR_CAPTURE.md`.
4. Widen the deterministic tiers (latency step 2) while the labelled set is built.
5. Only then: local gazetteer from open data, automatic phonetic variants, DTMF.

## 6. What I could not establish

* Real accuracy for numbers, English words and addresses (no ground truth).
* Whether the quiet-day calls are patients or testers.
* Why the clinic-API timer reads 0.
* The step at which 31 booking calls were dropped.
* The end-of-speech wait beyond 8 samples.

How these figures were produced: a read-only script run on the pod over its logs, journal, Ollama log and dashboard database; the scripts are not committed. Say if you want them added to `tools/`.
