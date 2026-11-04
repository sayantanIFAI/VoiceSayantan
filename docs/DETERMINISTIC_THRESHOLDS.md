# Deterministic thresholds and language logic: inventory

Generated 2026-11-02 from `main` by an AST walk of `agent/`, `clinic-api/`, `main.py`, `indic_asr_server.py`, `english_asr_server.py` and `tts_server.py`. `main_pcm.py` is excluded because `tools/make_pcm_variant.py` generates it from `main.py`.

## How to read this

* **Part 1** is the language logic, read by hand from the code. It is the only part that is prose.
* **Parts 2 to 7** are mechanical: every numeric constant the AST can see. A trailing comment is copied from the source line when there is one; the status words `REASONED` / `measured` come from the code's own comments, not from this file.
* **What the AST cannot see**, so it is *not* in the tables: thresholds written inside regular expressions (`{2,}`), numbers that live inside keyword/cue tables and phrase lists, values stored in the database (`agent_messages`, clinic catalogue), constants computed from other constants, and numeric literals used as `len(x) > 1`-style `0`, `1`, `-1` comparisons (skipped as noise). Treat the tables as a complete list of *named and compared numeric literals*, not of every rule.
* Env-tunable values show `env NAME=default`. The value in effect on a pod is whatever `deploy/env.sh` or the process environment sets.

## Part 1. Language logic (read by hand)

Languages: `bn`, `hi`, `en`. `ACTIVE_LANGUAGES` (`main.py:443`) is read from `VOICE_AGENT_LANGUAGES` (default `bn,hi,en`); **Bengali is always active** and is the greeting language and the default `session.lang`. With fewer than two active languages, or no language-ID model, the agent runs Bengali-only (`_route_and_transcribe_inner`, first lines).

No model decides any step below. The only learned inputs are the language-ID scores and each recogniser's own text and decoder agreement.

### 1.1 Script as evidence (`agent/lang_select.py`, `agent/language_policy.py`)

| Rule | Value |
|---|---|
| Bengali block / Devanagari block | U+0980 to U+09FF / U+0900 to U+097F |
| `script_share(text, lang)` | share of *letters* in that block (`en` = share of ASCII letters). Danda U+0964 and U+0965 are shared punctuation, never counted as wrong script. |
| `language_of_script(text, fallback)` | tries `hi`, `bn`, `en` in that order; first with share **>= 0.6** wins; otherwise `fallback` (mixed text or no letters). |
| `reply_matches_language` | word-level: a reply is in the wrong language when more than **0.34** of its lettered words contain none of the expected script (`_FOREIGN_TOLERANCE`, REASONED). |
| `speakable(text, lang)` | false if `unspeakable_spans` finds any, or any wrong-script letter other than danda. |
| `english_word_share` | share of tokens in a fixed English word list (about 190 words, includes clinic words and language-switch words). A one-letter token counts only if it is `a` or `i`. |
| `fix_asr_confusables` | one entry: `tame` becomes `time`, applied only to a transcript already decided to be English. |

### 1.2 Language ID (`agent/lid.py`)

* Model: SpeechBrain VoxLingua107 ECAPA, **scored only over bn/hi/en and renormalised**. If those three carry less than `MIN_SUPPORTED_MASS = 0.25` of the 107-class mass the result is `unknown`, confidence 0. The class docstring says it was written without a pod; the model path is unverified.
* `ASRLanguageRouter.route` (per call):
  1. LID language is supported and confidence **>= 0.55** (`DEFAULT_CONFIDENCE_FLOOR`): commit to it, reset the ambiguity streak.
  2. Else, if the call has a previous language: commit to the previous language.
  3. Else count an ambiguous turn; once the streak exceeds **3** (`DEFAULT_MAX_AMBIGUOUS_STREAK`, so the 4th ambiguous turn) the action is `handoff_human`.
  4. Else `dual_asr`: the top two languages for this turn only.
* `note_response_language(lang)` sets the prior for the next turn even when LID did not commit.

### 1.3 Which recognisers run (`lang_select.py`, `main.py _route_and_transcribe_inner`)

* At the same moment LID starts, the recogniser for the call's previous language (default `bn`) and English are started in parallel. English is never ruled out because LID labels accented English as Hindi or Bengali (measured: bn 0.83 / hi 0.16 / en 0.01).
* `languages_to_verify`: all active languages when LID says `unknown`, or when the **second-best LID score >= 0.03** (`SECOND_LANGUAGE_FLOOR`).
* `engines_needed`: LID's favourite, **plus** `en`, **plus** the call's previous language, **plus** any other language with LID **>= 0.16** (`OTHER_INDIC_MIN_LID`; the code comment says this was fitted to three real calls at 0.16, 0.26, 0.29 against a pinned case at 0.15, with no margin either side).

### 1.4 Choosing among recognisers (`pick_candidate`), in this order

1. **A switch command in English wins even on weak agreement:** English recogniser, agreement **>= 0.2**, Latin share **>= 0.9**, and the text parses as a language-switch request.
2. **English wins outright** when agreement **>= 0.6** (`ENGLISH_MIN_AGREEMENT`) and Latin share **>= 0.9**, and (no LID scores, or LID English **>= 0.05**, or English word share **>= 0.5**). It is then **vetoed** inside an established bn/hi call when any of:
   * LID gives the call's language **>= 0.8**, LID English **< 0.05**, and (word share **< 0.75** or agreement **< 0.7**);
   * the text is **<= 2 words** and LID English **< 0.35**;
   * the text is **<= 3 words**, LID English **< 0.35**, and some non-English reading has agreement **>= 0.85**.
3. **Otherwise the Indic candidates**: keep those LID believes (**>= 0.10**, `INDIC_MIN_LID`); take the best by (script share rounded to one decimal, decoder agreement); ties go to the LID-preferred (earlier) candidate.
4. **Switch guard:** with no established language the prior is forced to `bn`. If the best candidate is not the prior and its own LID score is **< 0.50** (`SWITCH_MIN_LID`), the prior's reading is kept.

### 1.5 Corrections on top of the pick (`main.py`)

| Situation | Rule |
|---|---|
| English recogniser overrules a confident Bengali/Hindi LID (`english_overrules_language_id`) | at least 2 words, agreement **>= 0.6**, Latin share **>= 0.9**; with **>= 3 words** word share **>= 0.6**; with exactly 2 words word share **== 1.0** and agreement **>= 0.8**. The English result is waited for with a **1.5 s** timeout. |
| English *not* waited for | LID is the chosen language at **>= 0.95**, LID English **< 0.05**, decoder agreement **>= 0.95**, and **>= 3 words**. |
| LID says Hindi in a call that is Bengali | if Hindi agreement **>= 0.5** and the Bengali reading (1.5 s timeout) has agreement **>= 0.75** and **>= Hindi agreement + margin**. Margin is **-0.15** when the call is not locked to Hindi (an unlocked call counts as Bengali), **+0.03** when it is. |
| Doubtful Hindi read | Hindi agreement **< 0.5** (`LOW_AGREEMENT_FOR_LOCK`): the Bengali reading is used if its agreement is higher. |
| Other language clearly wins in an established bn/hi call (`_keep_established_bengali`) | its text is wholly in its own script (`language_of_script`) with **>= 2 words**, its agreement exceeds the call language's by **>= 0.05**, and LID(other) **>= LID(call language) - 0.05**. The turn is answered in that language; the call is **not** locked (`clear_winner_lang`). Skipped if the caller explicitly chose a language. |
| Call language's reading stands | agreement **>= 0.75** and within **0.15** of the picked reading's. |
| Hindi words in a Bengali-script reading (`hindi_in_bengali.looks_hindi`) | at least 1 Hindi-only word (3+ consonant skeleton, not on a Bengali-collision list) and **at least 20%** of the Bengali-script tokens (`k*5 >= tokens`). Then Hindi is read as well: wholly Devanagari with **>= 2 words** and agreement **>= 0.5** gives the Hindi reading, otherwise the Bengali reading is kept; **either way the turn is Hindi**. Not when the caller chose a language or the call is locked to Hindi. |
| English words in a Bengali-script reading (`english_in_bengali.looks_english`) | at least 2 *distinct* English function words, at least one not on the weak list, and **at least 25%** of tokens. English is then read as well: ASCII, **>= 3 words**, agreement **>= 0.6** gives the English reading, otherwise the Bengali-letter reading is kept; either way the turn is English. |

### 1.6 The language the agent *replies* in (`_resolve_reply_language` and the code around it)

Recognition language and reply language are separate. The reply language is sticky.

* **Locking.** The first *decisive* turn locks the call's reply language. A turn is non-decisive when LID gave up, or the Indic agreement is **< 0.5**; a non-decisive first turn leaves the lock open so a later clear turn gets a fair first shot. `lang_lock_weak` is set when the locking agreement was **< 0.6**.
* **Hindi is hard to lock.** A Hindi first turn locks only if `_wholly_hindi`: **>= 2 words**, Devanagari share **>= 0.95**, agreement **>= 0.75**. Any later Hindi-looking turn in an unlocked call is non-decisive (`turn_count >= 1`).
* **The reply language changes only when:**
  1. the caller explicitly asks (`detect_language_switch_request`; `lang_explicit` is then set);
  2. the **two-turns offer** fires: the last two detected languages (`lang_history`) are the same, differ from the call language, are active, and that language has not been offered before this call. The agent asks once ("shall I speak X?") in that language instead of answering. It does not fire during a read-back, a short booking answer, a bare greeting, or when an explicit request is present;
  3. an **unrequested English call** hears a clear Bengali/Hindi sentence: **>= 4 words**, script share **>= 0.85**, agreement **>= 0.85**, not a short booking answer, `lang_explicit` unset, then the reply moves to that language;
  4. the same rule frees a **weakly locked** call (`lang_lock_weak`).
* **Never counts as a language signal:**
  * a short booking answer (fewer than **6** words, or a WhatsApp yes/no, and no switch request in it);
  * spoken digit words: `>= 3` digits read and `hits*2 >= total`;
  * a language word inside an address or police-station answer (English Bazar, Bangla More): the switch request is dropped while the booking is asking for the address;
  * an unreadable or empty turn (`_keep_language`).
* **Answering the offer** (`_continue_language_switch_offer`): a reply that is neither yes nor no but is **>= 3 words** with share **>= 0.85** in the *current* language counts as "no" (and is answered as a fresh sentence); **>= 4 words** with share **>= 0.85** in the *offered* language counts as "yes"; an explicit switch request in the reply overrides both.
* **Abuse** is answered in the script it was written in (Bengali or Devanagari share **>= 0.5**), otherwise the call language.
* **Switch-request detection** (`agent/language_switch.py`): per-utterance-language phrase tables for each target; clause splitting on punctuation and on `but / instead / rather / however / বরং / কিন্তু / लेकिन / बल्कि`; negation words and polite "না" forms are not a refusal; "Bangladesh" is never a language; the generic (unsigned) detector applies only to sentences of **<= 12 words**.

### 1.7 Confidence and re-ask thresholds that depend on the recogniser

| Rule | Value |
|---|---|
| `confidence_state` | only an `rnnt` result carries agreement: `LOW` below **0.5** (`LOW_CONFIDENCE_FLOOR`), else `VERIFIED`; `ctc_fallback`, single-decoder models and unknown decoders are `UNAVAILABLE`. |
| Factual intents withheld when LOW | `test_rate`, `doctor_availability`, `test_prep`, `clinic_faq`, `department_query`, `lookup_booking`, `resend_confirmation`. `UNAVAILABLE` is handled by reading the entity back instead. |
| `LOW_SCORE_REASK` | agreement **>= 0.25 and < 0.45**, **>= 2 words**, no digits, not a yes/no, not in a slot-filling context, and fewer than 1 prior such re-ask: say it again, once. |
| Garbled-line check (`audio_quality.transcript_problem`) | tokens present and `0 < agreement < 0.25`; also: own-script letters share **< 0.4**, one-letter tokens **>= 50%**, distinct-character ratio **<= 0.4**; audio length **>= 2.5 s** for the agreement test. |
| Decoder agreement (`agent/asr.py`) | word-level agreement of CTC vs RNNT; if their texts match at **>= 0.8** character similarity once spaces are removed, that similarity counts. RNNT is dropped for CTC when CTC has **>= 8** words and RNNT kept **<= 60%** of them. A clip longer than **11 s** (`ASR_MAX_CLIP_S`) is cut at pauses, searching from **60%** of that length with a **0.2 s** quiet window. |

### 1.8 Language-specific behaviour downstream of the decision

* **Fast path**: the cue table is chosen by `language_of_script(text)` of *this sentence*, not by the call's reply language. It abstains for a language it has no cues for. `LANGUAGE_GAP_MARGIN = 0.25`: a serve-rate gap between two languages wider than this (only judged once each has **>= 20** turns, `MIN_TURNS_FOR_GAP`) is reported as a defect in the weaker language's cue data.
* **Model-composed text**: only **English** small talk may be model-written, and only if it is speakable, passes `persona_clean`, and makes no claim about the caller's history. Bengali and Hindi always use the clinic's own wording.
* **Speech rate** (multiplied by the caller policy rate and by `FIGURE_SPEECH_SPEED = 0.8` on a clause that carries a price, number or reference): `bn` **1.32**, `hi` **1.28**, `en` **1.38**, other **1.06**. Question clause pitch x **1.08**; apology clause energy x **0.9**.
* **Names and entities**: clinic-api `did_you_mean` suggestions are returned in Bengali and Hindi script as well; matching compares written forms first, and a sound-alike match is only ever a suggestion that needs a yes.

### 1.9 Gaps in this section

I read `lang_select.py`, `lid.py` (router), `language_policy.py`, the top of `language_switch.py`, the reply-language and routing functions in `main.py`, `hindi_in_bengali.py`, `english_in_bengali.py` and `asr.py`. I did **not** read the per-language branches inside `speech_norm.verbalize`, `bn_normalize`, `fast_path_cues`, `reply_templates_i18n`, `phrases` or the full phrase tables of `language_switch`; their *numbers* are in Parts 2 to 6, their *wording rules* are not described here.


## Part 2. Named constants by pipeline stage


### Transport, admission and call limits

| File:line | Name | Value | Note |
|---|---|---|---|
| agent/admission.py:48 | `DEFAULT_MAX_CALLS` | `28` | ADR section 5: AI cap 28-30 for the 30-call design point |
| agent/admission.py:49 | `DEFAULT_LATENCY_WINDOW` | `30` | turns considered when judging p95 |
| agent/admission.py:50 | `DEFAULT_MIN_LATENCY_SAMPLES` | `10` | too few samples -> do not shed on noise |
| agent/admission.py:52 | `DEFAULT_LATENCY_HORIZON_S` | `90.0` | only turns this recent count towards latency_shed: with no new calls there are no new turns, and old slow ones must not keep the door shut |
| agent/call_record.py:40 | `FINISH_DEADLINE_S` | `25.0` |  |
| agent/call_record.py:48 | `BATCH_DELAY_S` | `2.0` |  |
| agent/latency_metrics.py:18 | `_WINDOW` | `200` |  |
| agent/llm.py:55 | `OLLAMA_NUM_CTX` | env `OLLAMA_NUM_CTX` = `0` |  |
| agent/llm.py:294 | `DEFAULT_DEADLINE_S` | `12.0` |  |
| agent/llm.py:295 | `_MAX_ATTEMPTS_BACKSTOP` | `5` | defence in depth only -- see extract_intent's docstring |
| agent/messages.py:31 | `REFRESH_AFTER_S` | `60.0` |  |
| agent/pcm_buffer.py:38 | `SAMPLE_RATE` | `16000` |  |
| agent/pcm_buffer.py:39 | `BYTES_PER_SAMPLE` | `2` | int16 mono |
| agent/tools_client.py:45 | `DEFAULT_TIMEOUT_S` | `4.0` | a phone caller will not wait much longer than this per lookup |
| agent/twilio_bridge.py:77 | `TWILIO_RATE` | `8000` | Twilio Media Streams are always 8 kHz mu-law |
| agent/twilio_bridge.py:78 | `AGENT_RATE` | `16000` | the PCM agent (agent/pcm_buffer.py SAMPLE_RATE) listens at 16 kHz int16 |
| agent/twilio_bridge.py:79 | `OUT_CHUNK_BYTES` | `800` | 100 ms of 8 kHz mu-law per outgoing "media" message (Twilio accepts any size and buffers in order) |
| agent/twilio_bridge.py:80 | `START_TIMEOUT_S` | `10.0` | how long a new stream may take to send its "start" event |
| agent/twilio_bridge.py:81 | `TOKEN_MAX_AGE_S` | `120` | a stream token is only good for this long after the webhook issued it |
| agent/twilio_bridge.py:82 | `DRAIN_CLOSE_S` | `2.0` | close() waits at most this long for queued audio to finish playing |
| agent/twilio_bridge.py:83 | `_CONVERT_CACHE_MAX` | `128` | converted reply clips kept (pinned catalogue answers repeat constantly) |
| agent/twilio_bridge.py:90 | `_MULAW_BIAS` | `132` |  |
| agent/twilio_bridge.py:91 | `_MULAW_CLIP` | `32635` |  |
| agent/ws_guard.py:13 | `MAX_CALL_SECONDS` | env `MAX_CALL_SECONDS` = `str(30 * 60)` | a call longer than this is closed (a clinic call is minutes) |
| agent/ws_guard.py:14 | `MAX_CALL_BYTES` | env `MAX_CALL_BYTES` = `str(128 * 1024 * 1024)` | audio bytes per call: 30 minutes of 16 kHz PCM is 58 MB, of 48 kHz 173 MB |
| agent/ws_guard.py:15 | `MAX_CHUNK_BYTES` | env `MAX_CHUNK_BYTES` = `str(1024 * 1024)` | one audio message |
| agent/ws_guard.py:16 | `MAX_CONTROL_BYTES` | env `MAX_CONTROL_BYTES` = `8192` | one control (text) message |

### Turn detection, endpointing, barge-in, echo

| File:line | Name | Value | Note |
|---|---|---|---|
| agent/barge_in.py:60 | `FRAME_S` | `0.04` |  |
| agent/barge_in.py:61 | `HOP_S` | `0.01` |  |
| agent/clip_chunks.py:19 | `MAX_CLIP_S` | env `ASR_MAX_CLIP_S` = `11` |  |
| agent/clip_chunks.py:20 | `_SEARCH_FROM` | `0.6` | a cut is searched for between 60% and 100% of MAX_CLIP_S after the previous one |
| agent/clip_chunks.py:21 | `_QUIET_WINDOW_S` | `0.2` |  |
| agent/echo_cancel.py:63 | `BLOCK` | `256` |  |
| agent/endpoint_calibration.py:45 | `MIN_RECORDINGS` | `200` |  |
| agent/full_duplex.py:41 | `MIN_TRUSTED_ERLE_DB` | `5.0` |  |
| agent/full_duplex.py:46 | `PHONE_MIN_SPEECH_S` | `0.3` |  |
| agent/full_duplex.py:51 | `HEADPHONES_FLOOR_DBFS` | env `HEADPHONES_BARGE_FLOOR_DBFS` = `-34` |  |
| agent/full_duplex.py:52 | `HEADPHONES_MIN_SPEECH_S` | env `HEADPHONES_BARGE_MIN_SPEECH_S` = `0.45` |  |
| agent/full_duplex.py:53 | `PHONE_FLOOR_DBFS` | env `PHONE_BARGE_FLOOR_DBFS` = `-40` |  |
| agent/full_duplex.py:56 | `TAIL_S` | `0.4` |  |
| agent/full_duplex.py:63 | `VOICE_CHANGE_INHIBIT_S` | `2.0` |  |
| agent/pause_profile.py:40 | `MIN_GAPS` | `4` | do not adapt on fewer observed gaps than this |
| agent/pause_profile.py:41 | `MAX_GAPS_KEPT` | `40` | the most recent gaps; a caller's rhythm can change during a call |
| agent/pause_profile.py:42 | `MAX_GAP_S` | `3.0` | a longer silence inside "one utterance" is not a pause, it is the end |
| agent/pause_profile.py:43 | `MIN_GAP_S` | `0.08` | below the detector's own hangover it is not a gap |
| agent/pause_profile.py:44 | `MARGIN` | `1.3` | wait this much longer than the caller's own long pauses |
| agent/pause_profile.py:45 | `COMPLETE_MARGIN` | `1.2` |  |
| agent/pause_profile.py:48 | `INCOMPLETE_FACTOR` | `1.5` |  |
| agent/pause_profile.py:49 | `FALSE_CUT_WINDOW_S` | `1.2` | speech resuming this soon after a cut means the cut was early |
| agent/pause_profile.py:50 | `FALSE_CUT_STEP` | `1.15` |  |
| agent/pause_profile.py:51 | `RELAX_AFTER_CLEAN_TURNS` | `5` |  |
| agent/pause_profile.py:52 | `RELAX_STEP` | `0.95` |  |
| agent/playback_gate.py:36 | `PLAYBACK_GUARD_S` | `3.0` |  |
| agent/playback_gate.py:41 | `RESYNC_REWIND_S` | `0.8` |  |

### Audio quality, conditioning, speaker / voice cues

| File:line | Name | Value | Note |
|---|---|---|---|
| agent/attention.py:40 | `NOISE_DELTA_DB` | `20.0` | an unvoiced frame this far below the caller's level is noise |
| agent/attention.py:41 | `PROTECT_HOPS` | `8` | ...unless it is within 80 ms of the caller's voiced speech (a consonant) |
| agent/attention.py:42 | `ATTENUATION_DB` | `18.0` |  |
| agent/attention.py:43 | `RAMP_S` | `0.03` |  |
| agent/attention.py:44 | `MAX_FRACTION` | `0.6` |  |
| agent/attention.py:45 | `MIN_FRAMES` | `20` |  |
| agent/audio_quality.py:44 | `FRAME_S` | `0.04` |  |
| agent/audio_quality.py:45 | `HOP_S` | `0.01` |  |
| agent/audio_quality.py:49 | `MIN_SPEECH_DURATION_S` | `0.6` |  |
| agent/audio_quality.py:50 | `QUIET_RMS_DBFS` | `-38.0` | active-speech RMS below this is "low audible" |
| agent/audio_quality.py:51 | `QUIET_PEAK_DBFS` | `-22.0` |  |
| agent/audio_quality.py:52 | `NOISY_SNR_DB` | `10.0` |  |
| agent/audio_quality.py:53 | `VERY_NOISY_SNR_DB` | `5.0` |  |
| agent/audio_quality.py:54 | `CLIPPING_FRACTION` | `0.01` |  |
| agent/audio_quality.py:55 | `VOICED_HARMONICITY` | `0.45` | normalised autocorrelation peak for a voiced frame |
| agent/audio_quality.py:56 | `MUMBLE_VOICED_RATIO` | `0.2` | of active frames; speech is normally 0.4-0.7 |
| agent/audio_quality.py:57 | `TWO_PITCH_RESIDUAL_FRACTION` | `0.1` |  |
| agent/audio_quality.py:58 | `TWO_PITCH_RESIDUAL_HARMONICITY` | `0.5` |  |
| agent/audio_quality.py:67 | `CROSSTALK_RATIO` | `0.05` |  |
| agent/audio_quality.py:68 | `CROSSTALK_MIN_FRAMES` | `8` | 80 ms of overlapped speech, so one glitch cannot trip it |
| agent/audio_quality.py:69 | `_LAG_EXCLUSION` | `0.07` | a "second" pitch within 7% of k*T is the same voice |
| agent/channel_quality.py:41 | `_TELEPHONY_CUTOFF_HZ` | `3400` |  |
| agent/channel_quality.py:42 | `_NARROWBAND_HIGH_ENERGY_RATIO` | `0.02` | below this fraction above cutoff -> narrowband |
| agent/channel_quality.py:50 | `_NOISY_SNR_RATIO_FLOOR` | `0.15` |  |
| agent/channel_quality.py:51 | `_FRAME_MS` | `20` |  |
| agent/channel_quality.py:89 | `_CROSSTALK_MAX_SPECTRAL_FLATNESS` | `0.1` |  |
| agent/conditioning.py:44 | `NOISY_BELOW_DB` | `18.0` | apply suppression only under this frame-energy SNR (REASONED) |
| agent/conditioning.py:45 | `MIN_RETENTION` | `0.9` | share of the original's voiced frames still voiced (REASONED) |
| agent/conditioning.py:46 | `MAX_F0_ERROR` | `0.03` | median relative pitch error allowed (REASONED) |
| agent/conditioning.py:47 | `F0_MATCH` | `0.05` | a pitch counts as the same within 5% |
| agent/distress.py:46 | `LOUD_DB` | `8.0` | louder than the caller's own opening turns by this much ... |
| agent/distress.py:47 | `HIGH_PITCH` | `1.2` | ... and this much higher (ratio of the voice's fundamental) |
| agent/distress.py:48 | `BASELINE_TURNS` | `2` |  |
| agent/distress.py:49 | `WINDOW` | `3` |  |
| agent/distress.py:50 | `NEEDED` | `2` | soft turns out of the last WINDOW |
| agent/distress.py:51 | `QUIET_TO_CLEAR` | `3` |  |
| agent/distress.py:52 | `REPEAT_SIMILARITY` | `0.8` |  |
| agent/level.py:46 | `TARGET_RMS_DBFS` | `-24.0` |  |
| agent/level.py:47 | `MAX_GAIN_DB` | `30.0` |  |
| agent/level.py:48 | `MAX_CUT_DB` | `15.0` |  |
| agent/level.py:49 | `CEILING_DBFS` | `-1.0` |  |
| agent/level.py:50 | `LIMITER_THRESHOLD_DBFS` | `-6.0` |  |
| agent/level.py:51 | `CLIPPED_FRACTION` | `0.005` | above this the input is treated as already clipped |
| agent/near_end.py:55 | `BACKGROUND_DELTA_DB` | `20.0` | owner, 2026-10-29: was 12 -- a clear answer in a softer or slightly different voice was thrown away |
| agent/near_end.py:59 | `DIFFERENT_VOICE_F0_RATIO` | `1.35` | was 1.15 |
| agent/near_end.py:60 | `MIN_OVERLAP_S` | `0.08` |  |
| agent/near_end.py:61 | `MERGE_GAP_S` | `0.1` |  |
| agent/near_end.py:62 | `PROFILE_ALPHA` | `0.3` |  |
| agent/near_end.py:70 | `ALTERNATION_WINDOW` | `41` |  |
| agent/near_end.py:71 | `ALTERNATION_RATIO` | `1.4` |  |
| agent/near_end.py:72 | `CLUSTER_TOL` | `0.08` |  |
| agent/near_end.py:73 | `CLUSTER_MIN_SHARE` | `0.25` |  |
| agent/near_end.py:74 | `CLUSTER_MAX_BETWEEN` | `0.15` |  |
| agent/senior_voice.py:71 | `MIN_VOICED_SECONDS` | `2.0` | below this there is not enough to judge |
| agent/senior_voice.py:73 | `MAX_GAP_S` | `0.25` | unvoiced gap the pitch track is bridged across |
| agent/senior_voice.py:74 | `MIN_TREMOR_SPAN_S` | `1.0` | continuous stretch needed to resolve a 4-12 Hz modulation |
| agent/senior_voice.py:75 | `PAUSE_MIN_S` | `0.2` | a silence shorter than this is a syllable dip, not a pause |
| agent/senior_voice.py:95 | `SENIOR_SCORE` | `0.4` |  |
| agent/senior_voice.py:96 | `DECISION_CLIPS` | `2` | clips with enough speech that must agree |
| agent/senior_voice.py:97 | `EVIDENCE_DECAY` | `0.6` | weight of history vs the newest clip |
| agent/senior_voice.py:289 | `SENIOR_AGE` | `60` |  |
| agent/speaker_change.py:41 | `N_BANDS` | `24` |  |
| agent/speaker_change.py:43 | `MIN_VOICED_S` | `0.6` | less voiced speech than this and the turn abstains |
| agent/speaker_change.py:44 | `FFT` | `512` |  |
| agent/speaker_change.py:48 | `SPEC_DB_SCALE` | `1.0` |  |
| agent/speaker_change.py:49 | `PITCH_OCTAVE_SCALE` | `0.06` |  |
| agent/speaker_change.py:56 | `CHANGE_HIGH` | `5.0` | one turn this far from the verified voice is a change |
| agent/speaker_change.py:57 | `CHANGE_LOW` | `3.8` | two consecutive turns this far are a change |
| agent/speaker_change.py:67 | `PITCH_JUMP_OCTAVES` | `0.32` |  |
| agent/speaker_change.py:68 | `PITCH_SOME_OCTAVES` | `0.15` |  |
| agent/speaker_change.py:69 | `LEVEL_JUMP_DB` | `8.0` |  |
| agent/telephony_augment.py:31 | `_MU` | `255.0` |  |

### Language ID, ASR agreement, language selection

| File:line | Name | Value | Note |
|---|---|---|---|
| agent/asr.py:147 | `SPACING_AGREEMENT_MIN` | `0.8` | character similarity (spaces ignored) from which it counts as agreement |
| agent/asr.py:148 | `RNNT_DROP_MIN_CTC_WORDS` | `8` | CTC must have heard at least this many words for a comparison to mean anything |
| agent/asr.py:149 | `RNNT_DROP_RATIO` | `0.6` | RNNT keeping 60% or fewer of CTC's words = it dropped speech |
| agent/clinical_terms.py:23 | `_STRICT` | `0.88` |  |
| agent/clinical_terms.py:24 | `_IN_CONTEXT` | `0.78` |  |
| agent/confidence_gate.py:45 | `LOW_CONFIDENCE_FLOOR` | `0.5` |  |
| agent/lang_select.py:74 | `SECOND_LANGUAGE_FLOOR` | `0.03` |  |
| agent/lang_select.py:113 | `OTHER_INDIC_MIN_LID` | `0.16` |  |
| agent/lang_select.py:156 | `ENGLISH_MIN_AGREEMENT` | `0.6` |  |
| agent/lang_select.py:165 | `INDIC_MIN_LID` | `0.1` |  |
| agent/lang_select.py:171 | `ENGLISH_MIN_LID` | `0.05` |  |
| agent/lang_select.py:172 | `ENGLISH_MIN_WORD_SHARE` | `0.5` |  |
| agent/lang_select.py:173 | `STABLE_CALL_LID` | `0.8` | language ID this sure of the call's language ... |
| agent/lang_select.py:174 | `STABLE_CALL_ENGLISH_SHARE` | `0.75` | ... and English must be at least this plainly English (and its decoders agree this well) to take the turn |
| agent/lang_select.py:175 | `STABLE_CALL_ENGLISH_AGREEMENT` | `0.7` |  |
| agent/lang_select.py:184 | `SHORT_UTTERANCE_WORDS` | `2` |  |
| agent/lang_select.py:185 | `SHORT_ENGLISH_MIN_LID` | `0.35` |  |
| agent/lang_select.py:242 | `SWITCH_MIN_LID` | `0.5` |  |
| agent/lang_select.py:251 | `OVERRULE_MIN_WORDS` | `3` |  |
| agent/lang_select.py:252 | `OVERRULE_MIN_WORD_SHARE` | `0.6` |  |
| agent/lang_select.py:275 | `ENGLISH_SWITCH_MIN_AGREEMENT` | `0.2` |  |
| agent/language_policy.py:33 | `_FOREIGN_TOLERANCE` | `0.34` |  |
| agent/language_switch.py:319 | `_MAX_WORDS` | `12` |  |
| agent/lid.py:44 | `DEFAULT_CONFIDENCE_FLOOR` | `0.55` |  |
| agent/lid.py:50 | `DEFAULT_MAX_AMBIGUOUS_STREAK` | `3` |  |
| agent/nbest_rescore.py:45 | `DEFAULT_MAX_PROMOTE_RANK` | `4` |  |

### Entity matching and fast path (no model)

| File:line | Name | Value | Note |
|---|---|---|---|
| agent/booking_carryover.py:17 | `MAX_GAP_TURNS` | `6` | was 3 (same distance agent/enquiry_followup.FOLLOWUP_MAX_GAP treats as "just now"): a doctor just discussed stays the subject across a couple of side questions |
| agent/call_end.py:248 | `_ACK_MAX_WORDS` | `7` |  |
| agent/confusables.py:44 | `MIN_SKELETON` | `3` | a shorter skeleton is not evidence by itself (agent/gazetteer.py) |
| agent/confusables.py:45 | `NEAR_MIN_SKELETON` | `4` |  |
| agent/confusables.py:46 | `SPELLING_FLOOR` | `0.75` | same-script similarity a merely similar spelling must reach to be listed |
| agent/confusables.py:50 | `SAME_SOUND_FLOOR` | `0.5` |  |
| agent/confusables.py:54 | `STRONG_RATIO` | `0.7` |  |
| agent/confusables.py:55 | `MIN_WORD_CHARS` | `3` | "বি", "सी", "का": a spoken letter or a particle, shared by many names and identifying none |
| agent/dialogue_state.py:16 | `MAX_LAST` | `300` |  |
| agent/doctor_search.py:190 | `NIGHT_FROM` | `20` |  |
| agent/enquiry_followup.py:52 | `FOLLOWUP_MAX_GAP` | `3` |  |
| agent/fast_path.py:85 | `ENTITY_MATCH_FLOOR` | `0.55` |  |
| agent/fast_path.py:94 | `COMMIT_FLOOR` | `0.72` |  |
| agent/fast_path.py:102 | `FAQ_COMMIT_FLOOR` | `0.72` |  |
| agent/fast_path.py:103 | `FAQ_COMPLEX_FLOOR` | `0.9` | owner, 2026-10-26: the stricter floor for an FAQ answered although the sentence holds a complexity word |
| agent/fast_path.py:109 | `AMBIGUITY_MARGIN` | `0.2` |  |
| agent/fast_path.py:113 | `LANGUAGE_GAP_MARGIN` | `0.25` |  |
| agent/fast_path.py:115 | `MIN_TURNS_FOR_GAP` | `20` |  |
| agent/form_index.py:36 | `SHORT_FORM_CHARS` | `6` |  |
| agent/form_index.py:40 | `MIN_PAIR_SHARE` | `0.4` |  |
| agent/form_index.py:43 | `INDEX_MIN_FORMS` | `400` |  |
| agent/gazetteer.py:56 | `SOUND_MIN_RATIO` | `0.4` |  |
| agent/gazetteer.py:59 | `SOUND_NEAR_MIN_RATIO` | `0.45` |  |
| agent/gazetteer.py:62 | `SPELLING_MIN_RATIO` | `0.5` |  |
| agent/gazetteer.py:65 | `MIN_SKELETON` | `3` |  |
| agent/gazetteer.py:67 | `NEAR_MIN_SKELETON` | `4` |  |
| agent/gazetteer.py:69 | `SHORTLIST` | `40` |  |
| agent/gazetteer.py:71 | `STOP_GRAM_SHARE` | `0.03` |  |
| agent/gazetteer.py:72 | `STOP_GRAM_FLOOR` | `60` |  |
| agent/gazetteer.py:76 | `SPELLING_WITH_SOUND_MIN_RATIO` | `0.7` |  |
| agent/gazetteer.py:79 | `SHORT_FORM_CHARS` | `5` |  |
| agent/gazetteer.py:80 | `SPELLING_SHORT_MIN_RATIO` | `0.65` |  |
| agent/gazetteer.py:85 | `TIE_MARGIN` | `0.08` |  |
| agent/intent_schema.py:78 | `_MAX_AGE` | `130` |  |
| agent/multi_question.py:19 | `MAX_PARTS` | `4` |  |
| agent/multi_question.py:20 | `MIN_WORDS` | `2` |  |
| agent/name_groups.py:20 | `MAX_PER_GROUP` | `4` |  |
| agent/off_topic.py:24 | `CLOSE_AT` | `2` |  |
| agent/phrase_proximity.py:22 | `DEFAULT_MAX_GAP_WORDS` | `2` |  |
| agent/semantic_cache.py:62 | `EMBED_TIMEOUT_S` | `45` |  |
| agent/semantic_cache.py:89 | `DEFAULT_THRESHOLD` | `0.78` |  |
| agent/semantic_cache.py:127 | `ENTITY_MATCH_FLOOR` | `0.55` |  |
| agent/symptom_repair.py:16 | `_MAX_WORDS` | `6` |  |
| agent/transcript_rules.py:38 | `YES_NO_MAX_TOKENS` | `4` |  |
| agent/unrelated_caller.py:53 | `CLOSE_AT` | `2` |  |
| agent/unrelated_caller.py:56 | `_MAX_WORDS` | `8` |  |

### Booking, slots, verification, safety

| File:line | Name | Value | Note |
|---|---|---|---|
| agent/age_cues.py:13 | `PAEDIATRIC_MAX_AGE` | `12` | 13 and above: the normal doctor (same constant as clinic-api/lay_departments.py) |
| agent/booking_capture.py:1115 | `_PS_MAX_REASKS` | `2` |  |
| agent/booking_flow.py:45 | `STATE_IDLE_TIMEOUT_S` | `180.0` |  |
| agent/booking_flow.py:316 | `_NEGATION_LOOKBACK` | `2` | "not really sure", "don't think so" style gaps |
| agent/call_score.py:28 | `BASE_SCORE` | `80` |  |
| agent/call_score.py:32 | `SLOW_REPLY_S` | `1.5` |  |
| agent/call_score.py:33 | `MIN_TURNS_TO_SCORE` | `2` | a call with fewer caller turns says too little to score |
| agent/call_state.py:27 | `SCHEMA_VERSION` | `1` |  |
| agent/call_summary.py:16 | `MAX_TRANSCRIPT_CHARS` | `300` | long enough for a sentence or two, short enough that this never becomes a transcript dump |
| agent/clinical_safety.py:368 | `_GLUED_VALUE_DIGITS` | `3` | ... unless the run is long enough to be a value that was merely run together |
| agent/figures.py:22 | `_MOBILE_LEN` | `10` |  |
| agent/identity.py:41 | `VERIFICATION_TTL_S` | `900` |  |
| agent/patient_context.py:35 | `STALE_AFTER_HOURS` | `24` |  |
| agent/patient_context.py:36 | `MAX_APPOINTMENTS_SPOKEN` | `3` |  |
| agent/reask_policy.py:46 | `DEFAULT_MAX_REASKS` | `2` |  |
| agent/security_check.py:114 | `MAX_PARSE_FAILURES` | `2` |  |
| agent/security_check.py:115 | `MAX_EVALUATIONS` | `3` | the server's own limit (registry.MAX_ATTEMPTS_PER_CALL) |
| agent/senior_care.py:27 | `SENIOR_AGE` | `60` |  |
| agent/senior_care.py:50 | `MIN_WORDS_FOR_CLOSING` | `4` |  |
| agent/senior_care.py:51 | `CLOSING_EVERY` | `2` | a closing on every second substantive reply |
| agent/serial_lookup.py:19 | `MAX_TRIES` | `3` | asking for / confirming the number: after this many misses the caller is pointed to the counter instead of being asked forever |
| agent/slot_grouping.py:42 | `MAX_FIELDS_PER_QUESTION` | `4` |  |
| agent/slot_proposal.py:23 | `LEAD_MINUTES` | `30` | a same-day slot must start at least this long from now (time to get there; the caller is also asked to come 15 min early) |
| agent/slot_proposal.py:24 | `COME_EARLY_MINUTES` | `15` |  |
| agent/visit_cues.py:167 | `SEVEN_DAYS` | `7` |  |
| agent/visit_cues.py:319 | `AVG_MINUTES_PER_PATIENT` | `15` |  |
| agent/visit_cues.py:389 | `BOOKING_WINDOW_DAYS` | env `BOOKING_MAX_ADVANCE_DAYS` = `3` | the clinic API's own limit (clinic-api/main.py MAX_ADVANCE_DAYS) -- same environment name |

### Reply wording and speech output

| File:line | Name | Value | Note |
|---|---|---|---|
| agent/clause_split.py:26 | `MIN_CHARS_TO_SPLIT` | `60` |  |
| agent/humanize.py:25 | `TIMEOUT_S` | env `HUMANIZE_TIMEOUT_S` = `1.5` |  |
| agent/pronunciation.py:42 | `LEXICON_TARGET` | `200` |  |
| agent/reply_templates.py:519 | `_NAMES_PER_GROUP` | `5` |  |
| agent/reply_templates_i18n.py:649 | `_NAMES_PER_GROUP` | `5` |  |
| agent/speech_policy.py:217 | `SPEECH_RATE_BOOST` | env `SPEECH_RATE_BOOST` = `1.06` |  |
| agent/speech_policy.py:222 | `SPEECH_RATE_BOOST_BN` | env `SPEECH_RATE_BOOST_BN` = `1.32` |  |
| agent/speech_policy.py:223 | `SPEECH_RATE_BOOST_HI` | env `SPEECH_RATE_BOOST_HI` = `1.28` |  |
| agent/speech_policy.py:225 | `SPEECH_RATE_BOOST_EN` | env `SPEECH_RATE_BOOST_EN` = `1.38` |  |
| agent/tts.py:68 | `TTS_TIMEOUT_S` | env `TTS_TIMEOUT_S` = `20` |  |
| agent/tts.py:77 | `FIGURE_SPEECH_SPEED` | `0.8` |  |
| agent/tts.py:109 | `AUDIO_CACHE_MAX` | `400` |  |
| agent/tts.py:111 | `MAX_PINNED_CLIPS` | `3000` |  |
| agent/turn_ack.py:35 | `MAX_ACK_WORDS` | `3` |  |
| agent/turn_ack.py:36 | `MIN_TURNS_BETWEEN` | `2` | an acknowledgement at most every other reply |
| agent/turn_ack.py:37 | `MIN_REPLY_WORDS` | `3` | a one- or two-word reply needs no preamble |
| agent/turn_ack.py:72 | `MAX_THANKS_WORDS` | `8` |  |
| tts_server.py:113 | `DEFAULT_LENGTH_SCALE` | env `TTS_LENGTH_SCALE` = `1.08` |  |

### Clinic API (the source of facts)

| File:line | Name | Value | Note |
|---|---|---|---|
| clinic-api/agent_messages.py:26 | `MAX_TEXT_CHARS` | `600` |  |
| clinic-api/backfill_doctor_fees.py:22 | `DEFAULT_FEE` | `500` | models.Doctor.consultation_fee_inr's own column default |
| clinic-api/booking_service.py:58 | `HOLD_TTL_SECONDS` | `900` | sourav, 2026-10-24: was 90, then 300 -- both still expired live on a slow multi-turn call (name/ |
| clinic-api/booking_service.py:63 | `DRAFT_BOOKING_TTL_MINUTES` | `30` |  |
| clinic-api/booking_service.py:64 | `SMS_RESEND_MIN_INTERVAL_S` | `60` |  |
| clinic-api/booking_service.py:66 | `SMS_DEDUP_WINDOW_S` | `60` |  |
| clinic-api/booking_service.py:84 | `SLOT_STEP_MIN` | env `SLOT_STEP_MIN` = `10` | owner, 2026-10-17: one booking per 10-minute slot (env override: the older test-suite pins a 15-minute grid) |
| clinic-api/booking_service.py:553 | `CHANGE_MAX_FAILS` | env `CHANGE_MAX_FAILS` = `5` |  |
| clinic-api/booking_service.py:554 | `CHANGE_LOCK_MINUTES` | env `CHANGE_LOCK_MINUTES` = `15` |  |
| clinic-api/booking_service.py:1052 | `MAX_SUGGESTED_DOCTORS` | `3` |  |
| clinic-api/enquiry_service.py:47 | `REPORT_OTP_TTL_MINUTES` | `10` |  |
| clinic-api/enquiry_service.py:49 | `OTP_REISSUE_WINDOW_S` | `60` |  |
| clinic-api/enquiry_service.py:50 | `REPORT_LINK_TTL_HOURS` | `48` |  |
| clinic-api/enquiry_service.py:51 | `CALLBACK_MIN_LEAD_MINUTES` | `30` |  |
| clinic-api/gazetteer.py:56 | `SOUND_MIN_RATIO` | `0.4` |  |
| clinic-api/gazetteer.py:59 | `SOUND_NEAR_MIN_RATIO` | `0.45` |  |
| clinic-api/gazetteer.py:62 | `SPELLING_MIN_RATIO` | `0.5` |  |
| clinic-api/gazetteer.py:65 | `MIN_SKELETON` | `3` |  |
| clinic-api/gazetteer.py:67 | `NEAR_MIN_SKELETON` | `4` |  |
| clinic-api/gazetteer.py:69 | `SHORTLIST` | `40` |  |
| clinic-api/gazetteer.py:71 | `STOP_GRAM_SHARE` | `0.03` |  |
| clinic-api/gazetteer.py:72 | `STOP_GRAM_FLOOR` | `60` |  |
| clinic-api/gazetteer.py:76 | `SPELLING_WITH_SOUND_MIN_RATIO` | `0.7` |  |
| clinic-api/gazetteer.py:79 | `SHORT_FORM_CHARS` | `5` |  |
| clinic-api/gazetteer.py:80 | `SPELLING_SHORT_MIN_RATIO` | `0.65` |  |
| clinic-api/gazetteer.py:85 | `TIE_MARGIN` | `0.08` |  |
| clinic-api/geo_service.py:32 | `GEO_TTL_S` | `30.0` |  |
| clinic-api/geo_service.py:35 | `SOUND_CONFIDENT` | `0.78` |  |
| clinic-api/idempotency.py:44 | `MAX_KEY_CHARS` | `200` |  |
| clinic-api/lay_departments.py:25 | `PAEDIATRIC_MAX_AGE` | `12` | 13 and above go to the normal doctor (owner, 2026-10-24) |
| clinic-api/main.py:69 | `SLOT_STEP_MIN` | env `SLOT_STEP_MIN` = `10` | owner, 2026-10-17: one booking per 10-minute slot (same env as booking_service.SLOT_STEP_MIN) |
| clinic-api/main.py:403 | `GAZETTEER_TTL_S` | `30.0` |  |
| clinic-api/main.py:660 | `FUZZY_SURNAME_FLOOR` | `0.6` |  |
| clinic-api/main.py:671 | `PHONETIC_ASSISTED_FLOOR` | `0.45` |  |
| clinic-api/main.py:701 | `MIN_SUBSTRING_CHARS` | `3` |  |
| clinic-api/main.py:925 | `_SCHEDULE_CACHE_TTL_S` | env `SCHEDULE_CACHE_TTL_S` = `20` |  |
| clinic-api/main.py:1219 | `MAX_ADVANCE_DAYS` | env `BOOKING_MAX_ADVANCE_DAYS` = `3` |  |
| clinic-api/patient_context.py:79 | `STALE_AFTER_HOURS` | `24` |  |
| clinic-api/patient_context.py:323 | `MIN_PHONETIC_KEY_LEN` | `3` |  |
| clinic-api/payments.py:24 | `BOOKING_FEE_INR` | env `BOOKING_FEE_INR` = `40` |  |
| clinic-api/payments.py:25 | `LINK_EXPIRY_MINUTES` | env `PAYMENT_LINK_EXPIRY_MINUTES` = `15` |  |
| clinic-api/phrase_proximity.py:22 | `DEFAULT_MAX_GAP_WORDS` | `2` |  |
| clinic-api/registry.py:47 | `MAX_ATTEMPTS_PER_CALL` | `3` |  |
| clinic-api/registry.py:48 | `MAX_FAILED_PER_PATIENT_24H` | `6` |  |
| clinic-api/registry.py:49 | `VERIFICATION_TTL_MIN` | `15` |  |
| clinic-api/registry.py:50 | `CACHE_TTL_HOURS` | `24` |  |
| clinic-api/registry.py:51 | `SENIOR_AGE` | `60` | India's definition of a senior citizen |
| clinic-api/registry.py:57 | `MIN_ADDRESS_TOKEN_LEN` | `3` |  |

### Orchestrator (main.py; main_pcm.py is generated from it)

| File:line | Name | Value | Note |
|---|---|---|---|
| main.py:278 | `POLL_INTERVAL_S` | `0.5` |  |
| main.py:279 | `IDLE_TIMEOUT_S` | `90.0` |  |
| main.py:280 | `UTTERANCE_PAD_S` | `0.15` | small trailing pad so ASR doesn't clip the last phoneme |
| main.py:288 | `HEARTBEAT_INTERVAL_S` | `15.0` |  |
| main.py:295 | `PLAYBACK_GUARD_S` | `3.0` |  |
| main.py:301 | `RESYNC_REWIND_S` | `0.8` | 2026-10-17: was 0.25 and measured from the poll tick; see agent/playback_gate.py |
| main.py:310 | `ACTIVE_POLL_INTERVAL_S` | env `ACTIVE_POLL_INTERVAL_S` = `0.2` |  |
| main.py:311 | `MIN_WAKE_S` | `0.02` |  |
| main.py:312 | `WAKE_SLACK_S` | `0.005` |  |
| main.py:326 | `ENDPOINT_INCOMPLETE_S` | env `ENDPOINT_INCOMPLETE_S` = `3.5` |  |
| main.py:330 | `ENDPOINT_CERTAIN_S` | env `ENDPOINT_CERTAIN_S` = `0.45` |  |
| main.py:331 | `ENDPOINT_COMPLETE_S` | env `ENDPOINT_COMPLETE_S` = `1.2` |  |
| main.py:332 | `SPECULATIVE_ASR_TIMEOUT_S` | `1.5` |  |
| main.py:333 | `MAX_SPECULATIONS_PER_TURN` | `3` |  |
| main.py:334 | `SPECULATION_MATCH_TOLERANCE_S` | `0.25` |  |
| main.py:339 | `TURN_TAIL_GUARD_S` | env `TURN_TAIL_GUARD_S` = `0.3` |  |
| main.py:346 | `TURN_SILENCE_CONFIRM_S` | env `TURN_SILENCE_CONFIRM_S` = `2.0` |  |
| main.py:355 | `BARGE_IN_PREROLL_S` | `0.35` |  |
| main.py:370 | `HISTORY_TEST_MATCH_MIN` | `0.85` |  |
| main.py:382 | `NOISE_SUPPRESS_AFTER_ASKS` | env `NOISE_SUPPRESS_AFTER_ASKS` = `3` |  |
| main.py:400 | `FILLER_THRESHOLD_S` | env `FILLER_THRESHOLD_S` = `1.0` | was 2.5 s of silence, then 0.9 s, then 0.7 s |
| main.py:403 | `FILLER_MIN_WAIT_S` | env `FILLER_MIN_WAIT_S` = `0.25` |  |
| main.py:411 | `NATURAL_PAUSE_S` | env `NATURAL_PAUSE_S` = `0.15` |  |
| main.py:415 | `SILENCE_PROMPT_S` | env `SILENCE_PROMPT_S` = `5` |  |
| main.py:416 | `SILENCE_CLOSE_S` | env `SILENCE_CLOSE_S` = `5` |  |
| main.py:417 | `BOOKING_CLOSE_FACTOR` | env `BOOKING_CLOSE_FACTOR` = `1` | Owner, 2026-11-04: same 5 s after the prompt inside a booking as outside (was 4) |
| main.py:418 | `SILENCE_HELLOS` | env `SILENCE_HELLOS` = `3` | "hello?" this many times to a caller who has said nothing at all, then the call is cut |
| main.py:426 | `CHANNEL_QUALITY_BUDGET_S` | `0.08` |  |
| main.py:432 | `AUDIO_ANALYSIS_BUDGET_S` | `0.5` |  |
| main.py:435 | `ASR_REFINE` | env `ASR_REFINE` = `off` |  |
| main.py:461 | `ADMISSION_MAX_CALLS` | env `ADMISSION_MAX_CALLS` = `36` |  |
| main.py:568 | `CATALOGUE_CACHE_TTL_S` | `300.0` |  |
| main.py:581 | `ANSWER_WARM_INTERVAL_S` | env `ANSWER_WARM_INTERVAL_S` = `600` |  |
| main.py:585 | `AVAILABILITY_PRELOAD_INTERVAL_S` | env `AVAILABILITY_PRELOAD_INTERVAL_S` = `60` |  |
| main.py:667 | `STATIC_RELOAD_HOUR` | env `STATIC_RELOAD_HOUR` = `5` | clinic time; the day's one reload of prices, preparation and FAQ answers |
| main.py:755 | `INTENT_WARMUP_DEADLINE_S` | env `INTENT_WARMUP_DEADLINE_S` = `300` |  |
| main.py:1490 | `QUESTION_PITCH_SCALE` | env `QUESTION_PITCH_SCALE` = `1.08` |  |
| main.py:1491 | `APOLOGY_ENERGY_SCALE` | env `APOLOGY_ENERGY_SCALE` = `0.9` |  |
| main.py:2224 | `INTENT_BUDGET_S` | env `INTENT_TURN_BUDGET_S` = `12` |  |
| main.py:2226 | `CACHE_HEAD_START_S` | env `INTENT_CACHE_HEAD_START_S` = `0.15` |  |
| main.py:2228 | `CACHE_LOOKUP_MAX_S` | env `INTENT_CACHE_MAX_S` = `1.5` |  |
| main.py:2230 | `MIN_MODEL_BUDGET_S` | `0.5` |  |
| main.py:2542 | `LOW_SCORE_REASK` | env `LOW_SCORE_REASK` = `0.45` | decoder agreement below this (and at least 0.25, the garbled line) is asked to be said again, once |
| main.py:4246 | `_PICK_MEMORY_TURNS` | `1000000` |  |
| main.py:5559 | `UTT_RING_KEEP` | env `UTT_RING_KEEP` = `40` |  |
| main.py:8890 | `LOW_AGREEMENT_FOR_LOCK` | `0.5` |  |
| main.py:10289 | `INGRESS_MAX_S` | env `INGRESS_MAX_S` = `10` |  |
| main.py:10290 | `INGRESS_SETTLE_MS` | env `INGRESS_SETTLE_MS` = `60` |  |
| main.py:10291 | `INGRESS_BATCH_MAX` | env `INGRESS_BATCH_MAX` = `40` | at most this many queued chunks are joined into one append (about 0.8 s of 20 ms frames) |
| main.py:10317 | `INGRESS_SHED_MS` | env `INGRESS_SHED_MS` = `500` | a backlog above this for two seconds closes the door to NEW calls |
| main.py:10318 | `INGRESS_SHED_LAG_MS` | env `INGRESS_SHED_LAG_MS` = `400` | so does an event loop that sleeps this much longer than asked |
| main.py:10319 | `SPECULATE_MAX_CALLS` | env `SPECULATE_MAX_CALLS` = `10` | above this many live calls the extra "has the caller finished?" transcriptions are not made |

**343 named constants.**


## Part 3. Class-field defaults and function-argument defaults (float)

| File:line | Where | |
|---|---|---|
| agent/admission.py:212 | `__init__(interval_s=5.0)` | |
| agent/admission.py:250 | `http_probe(timeout_s=3.0)` | |
| agent/asr.py:156 | `ASRResult.decoder_agreement=1.0` | |
| agent/asr_metrics.py:92 | `bootstrap_interval(level=0.95)` | |
| agent/asr_router.py:78 | `__init__(timeout_s=15.0)` | |
| agent/audio_quality.py:275 | `enhance(floor_gain=0.12)` | |
| agent/audio_quality.py:275 | `enhance(max_gain_db=24.0)` | |
| agent/barge_in.py:66 | `BargeInConfig.min_speech_s=0.11` | |
| agent/barge_in.py:67 | `BargeInConfig.above_floor_db=9.0` | |
| agent/barge_in.py:72 | `BargeInConfig.miss_penalty=0.4` | |
| agent/barge_in.py:78 | `BargeInConfig.echo_like_similarity=0.7` | |
| agent/barge_in.py:79 | `BargeInConfig.echo_like_below_db=6.0` | |
| agent/barge_in.py:83 | `BargeInConfig.strong_above_echo_db=6.0` | |
| agent/barge_in.py:84 | `BargeInConfig.strong_weight=2.0` | |
| agent/barge_in.py:87 | `BargeInConfig.pure_tone_fraction=0.85` | |
| agent/call_state.py:69 | `CallState.speech_rate=1.0` | |
| agent/dept_talk.py:119 | `match_doctor(floor=0.62)` | |
| agent/dept_talk.py:119 | `match_doctor(margin=0.08)` | |
| agent/dept_talk.py:149 | `close_doctors(floor=0.55)` | |
| agent/dept_talk.py:208 | `named_doctors(floor=0.62)` | |
| agent/echo_cancel.py:78 | `estimate_delay(max_delay_s=0.6)` | |
| agent/echo_cancel.py:104 | `__init__(dt_mu_fraction=0.02)` | |
| agent/echo_cancel.py:104 | `__init__(mu=0.5)` | |
| agent/echo_cancel.py:299 | `__init__(delay_update_s=0.5)` | |
| agent/echo_cancel.py:299 | `__init__(history_s=4.0)` | |
| agent/echo_cancel.py:299 | `__init__(lead_s=0.032)` | |
| agent/echo_cancel.py:299 | `__init__(max_delay_s=0.6)` | |
| agent/echo_cancel.py:299 | `__init__(min_confidence=6.0)` | |
| agent/endpoint_calibration.py:69 | `wilson_interval(z=1.96)` | |
| agent/endpoint_calibration.py:81 | `commit_time(step_s=0.02)` | |
| agent/endpoint_calibration.py:96 | `evaluate(cut_tolerance_s=0.3)` | |
| agent/endpoint_calibration.py:126 | `calibrate(target_false_cut=0.02)` | |
| agent/endpointing.py:43 | `EndpointConfig.silence_confirm_s=1.0` | |
| agent/endpointing.py:46 | `EndpointConfig.tail_guard_s=0.3` | |
| agent/endpointing.py:48 | `EndpointConfig.min_speech_s=0.35` | |
| agent/endpointing.py:50 | `EndpointConfig.max_utterance_s=45.0` | |
| agent/endpointing.py:54 | `EndpointConfig.complete_confirm_s=0.45` | |
| agent/endpointing.py:55 | `EndpointConfig.incomplete_confirm_s=1.5` | |
| agent/endpointing.py:59 | `EndpointConfig.speculate_after_s=0.3` | |
| agent/endpointing.py:62 | `EndpointConfig.certain_confirm_s=0.45` | |
| agent/endpointing.py:81 | `TurnDecision.trailing_silence_s=0.0` | |
| agent/endpointing.py:82 | `TurnDecision.confirm_s=0.0` | |
| agent/endpointing.py:500 | `energy_spans(frame_s=0.02)` | |
| agent/endpointing.py:500 | `energy_spans(hang_s=0.12)` | |
| agent/endpointing.py:500 | `energy_spans(margin_db=12.0)` | |
| agent/lid.py:320 | `__init__(timeout_s=20.0)` | |
| agent/near_end.py:152 | `dominant_span(drop_db=12.0)` | |
| agent/near_end.py:152 | `dominant_span(min_len_s=0.3)` | |
| agent/near_end.py:152 | `dominant_span(smooth_s=0.25)` | |
| agent/pause_profile.py:59 | `PauseProfile.bump=1.0` | |
| agent/prosody.py:43 | `ProsodyParams.pause_sentence_s=0.28` | |
| agent/prosody.py:44 | `ProsodyParams.pause_clause_s=0.14` | |
| agent/prosody.py:45 | `ProsodyParams.pause_none_s=0.06` | |
| agent/prosody.py:49 | `ProsodyParams.trim_threshold=0.012` | |
| agent/prosody.py:50 | `ProsodyParams.target_peak=0.89` | |
| agent/prosody.py:52 | `ProsodyParams.lead_in_s=0.04` | |
| agent/prosody.py:59 | `ProsodyParams.compress_threshold=0.55` | |
| agent/prosody.py:60 | `ProsodyParams.compress_ceiling=0.92` | |
| agent/prosody.py:65 | `ProsodyParams.room_tone_level=0.0012` | |
| agent/speech_policy.py:54 | `SpeechPolicy.speech_rate=1.0` | |
| agent/telephony_augment.py:41 | `band_limit(high_hz=3400.0)` | |
| agent/telephony_augment.py:41 | `band_limit(low_hz=300.0)` | |
| agent/telephony_augment.py:94 | `clip(threshold=0.9)` | |
| agent/telephony_augment.py:104 | `packet_loss(burst_ms=20.0)` | |
| agent/telephony_augment.py:104 | `packet_loss(loss_rate=0.02)` | |
| agent/vad_stream.py:55 | `__init__(max_utterance_s=45.0)` | |
| agent/vad_stream.py:55 | `__init__(min_speech_s=0.35)` | |
| agent/vad_stream.py:55 | `__init__(tail_guard_s=0.3)` | |
| english_asr_server.py:91 | `ASRResult.decoder_agreement=1.0` | |

## Part 4. Environment variables read inside functions (not module level)

| File:line | Variable | Default |
|---|---|---|
| agent/asr.py:183 | `ASR_MAX_BATCH` | `'16'` |
| agent/asr.py:184 | `ASR_BATCH_WAIT_S` | `'0.015'` |
| agent/bn_respell.py:220 | `BN_RESPELL_RULES` | `'1'` |
| agent/bn_respell.py:227 | `BN_RESPELL` | `'1'` |
| agent/phrases.py:193 | `CALL_RECORDING_NOTICE` | `'0'` |
| agent/tools_client.py:185 | `AVAILABILITY_TTL_S` | `'120'` |
| agent/twilio_bridge.py:285 | `TWILIO_VALIDATE_SIGNATURE` | `'1'` |
| agent/twilio_bridge.py:597 | `TWILIO_BRIDGE` | `'1'` |
| agent/vad_stream.py:95 | `VAD_POOL` | `'6'` |
| clinic-api/main.py:220 | `CLINIC_SEED_SAMPLE_PATIENTS` | `'1'` |
| clinic-api/seed.py:646 | `SEED_EXTRA_DOCTORS` | `'1'` |
| indic_asr_server.py:38 | `INDIC_ASR_LID` | `'1'` |
| main.py:780 | `OLLAMA_NUM_PARALLEL` | `'8'` |
| main.py:807 | `AGENT_TORCH_THREADS` | `'6'` |
| tts_server.py:138 | `TTS_WHATSAPP_CLIP` | `'1'` |

## Part 5. Float thresholds written inline in a comparison

Numerical-noise epsilons (`1e-6` and smaller) are listed too, so the list is complete; they are not decision thresholds.

| File:line | Value | Source line |
|---|---|---|
| agent/audio_quality.py:161 | `1e-12` | `return float(lag) + (0.5 * (a - c) / denom if abs(denom) > 1e-12 else 0.0)` |
| agent/audio_quality.py:182 | `1e-09` | `if ex < 1e-9 or ee / (2.0 * ex) < TWO_PITCH_RESIDUAL_FRACTION:` |
| agent/audio_quality.py:207 | `0.99` | `clipping = float(np.mean(np.abs(x) >= 0.99)) if x.size else 0.0` |
| agent/audio_quality.py:392 | `0.0` | `if tokens and decoder_agreement is not None and 0.0 < decoder_agreement < 0.25:` |
| agent/audio_quality.py:392 | `0.25` | `if tokens and decoder_agreement is not None and 0.0 < decoder_agreement < 0.25:` |
| agent/audio_quality.py:399 | `2.5` | `and audio_duration_s >= 2.5` |
| agent/audio_quality.py:408 | `0.4` | `if sum(1 for c in letters if script.match(c)) / len(letters) < 0.4:` |
| agent/audio_quality.py:411 | `0.5` | `if sum(1 for t in tokens if len(t) == 1) / len(tokens) >= 0.5:` |
| agent/audio_quality.py:414 | `0.4` | `if len(set(lowered)) / len(lowered) <= 0.4:` |
| agent/audio_quality.py:416 | `0.0` | `if decoder_agreement is not None and 0.0 < decoder_agreement < 0.25:` |
| agent/audio_quality.py:416 | `0.25` | `if decoder_agreement is not None and 0.0 < decoder_agreement < 0.25:` |
| agent/barge_in.py:129 | `1e-08` | `rel = 10 * np.log10(p / pe) if pe > 1e-8 else float("inf")` |
| agent/barge_in.py:171 | `0.0` | `hit = weight > 0.0` |
| agent/barge_in.py:185 | `0.0` | `if self._score == 0.0:` |
| agent/booking_capture.py:243 | `0.6` | `pure = total > 0 and hits / total >= 0.6` |
| agent/channel_quality.py:131 | `0.05` | `if quiet_frame_fraction >= 0.05:` |
| agent/confidence_gate.py:94 | `0.0` | `return 0.0 < decoder_agreement < LOW_CONFIDENCE_FLOOR` |
| agent/dept_talk.py:66 | `0.7` | `if score < 0.7:` |
| agent/echo_cancel.py:87 | `1e-10` | `if np.sum(r**2) < 1e-8 or np.sum(m**2) < 1e-10:` |
| agent/echo_cancel.py:87 | `1e-08` | `if np.sum(r**2) < 1e-8 or np.sum(m**2) < 1e-10:` |
| agent/echo_cancel.py:168 | `1e-08` | `ref_active = ref_peak > 1e-4 and float(np.mean(ref**2)) > 1e-8` |
| agent/echo_cancel.py:168 | `0.0001` | `ref_active = ref_peak > 1e-4 and float(np.mean(ref**2)) > 1e-8` |
| agent/echo_cancel.py:179 | `0.0001` | `geigel_hit = float(np.max(np.abs(mic))) > self.geigel * ref_peak and ref_peak > 1e-4` |
| agent/echo_cancel.py:190 | `3.0` | `collapse = self._erle_best > 3.0 and block_erle < self._erle_best - margin` |
| agent/echo_cancel.py:203 | `3.0` | `instant_collapse = self._erle_best > 3.0 and 10 * np.log10(pm / pe) < self._erle_best - margin` |
| agent/echo_cancel.py:409 | `1e-07` | `if float(np.mean(self._ref_slice(start, end) ** 2)) < 1e-7:` |
| agent/echo_cancel.py:454 | `1e-10` | `if np.sum(ref_long**2) < 1e-8 or np.sum(mic**2) < 1e-10:` |
| agent/echo_cancel.py:454 | `1e-08` | `if np.sum(ref_long**2) < 1e-8 or np.sum(mic**2) < 1e-10:` |
| agent/endpointing.py:94 | `0.2` | `if duration_s < 0.2:` |
| agent/fast_path.py:331 | `0.75` | `idx = next((i for i, t in enumerate(tokens) if t == f or (len(f) >= 3 and (t.startswith(f) or difflib.SequenceMatcher(None, f, t).ratio() >= 0.75))), ` |
| agent/fast_path.py:534 | `0.95` | `if not (score >= 0.95 and said not in _COMMON_WORD_ALIASES and any(tok == said or tok.startswith(said) for tok in text.split())):` |
| agent/fast_path.py:554 | `0.75` | `if not any(t == f or t.startswith(f) or difflib.SequenceMatcher(None, f, t).ratio() >= 0.75 for t in others):` |
| agent/fast_path.py:685 | `1.0` | `if score >= 1.0:` |
| agent/fast_path.py:689 | `1.0` | `if first is None or first_score >= 1.0:` |
| agent/form_index.py:110 | `0.8` | `hit = any(difflib.SequenceMatcher(None, token, g).ratio() >= 0.8 for g in self._generic)` |
| agent/form_index.py:148 | `0.0` | `order = self._candidates(text) if (self.indexed and floor > 0.0) else range(len(self._forms))` |
| agent/form_index.py:171 | `0.0` | `if floor > 0.0:` |
| agent/form_index.py:200 | `0.0` | `if floor > 0.0 and best_score < floor:` |
| agent/humanize.py:67 | `0.85` | `if _script_share(new, lang) < 0.85 and _script_share(old, lang) >= 0.85:` |
| agent/humanize.py:67 | `0.85` | `if _script_share(new, lang) < 0.85 and _script_share(old, lang) >= 0.85:` |
| agent/imaging_words.py:53 | `0.7` | `if len(core) >= 5 and not core.isascii() and (core == "অ্যাবডোমেন" or clinical_terms._best("abdomen", core) >= 0.7):  # a scan was just named, so the ` |
| agent/lang_select.py:38 | `0.6` | `if script_share(text, lang) >= 0.6:` |
| agent/lang_select.py:260 | `0.9` | `if len(words) < 2 or agreement < ENGLISH_MIN_AGREEMENT or script_share(text, "en") < 0.9:` |
| agent/lang_select.py:265 | `0.8` | `return share == 1.0 and agreement >= 0.8  # two words ("you take"): every word real English and the decoders agree` |
| agent/lang_select.py:265 | `1.0` | `return share == 1.0 and agreement >= 0.8  # two words ("you take"): every word real English and the decoders agree` |
| agent/lang_select.py:307 | `0.9` | `and script_share(r.text, "en") >= 0.9` |
| agent/lang_select.py:312 | `0.9` | `if lang == "en" and r.decoder_agreement >= ENGLISH_MIN_AGREEMENT and script_share(r.text, "en") >= 0.9:` |
| agent/lang_select.py:345 | `0.85` | `and any(l2 != "en" and getattr(r2, "text", "").strip() and r2.decoder_agreement >= 0.85 for l2, r2 in usable)` |
| agent/level.py:103 | `0.99` | `clipped = bool(x.size and float(np.mean(np.abs(x) >= 0.99)) >= CLIPPED_FRACTION)` |
| agent/name_groups.py:48 | `0.75` | `return len(ka) >= 2 and ka == kb and difflib.SequenceMatcher(None, a, b).ratio() >= 0.75` |
| agent/name_script.py:64 | `0.75` | `return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75` |
| agent/name_script.py:69 | `0.8` | `return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8` |
| agent/owner_answers.py:120 | `0.85` | `if 4 <= len(snd) <= 6 and difflib.SequenceMatcher(None, snd, _SONOSCAN_SOUND).ratio() >= 0.85:` |
| agent/pause_profile.py:105 | `1.0` | `if not self.adapted and self.bump == 1.0:` |
| agent/prosody.py:219 | `1e-06` | `return wav * (target / peak) if peak > 1e-6 else wav` |
| agent/senior_voice.py:207 | `0.1` | `kept = [p for j, p in enumerate(peak_idx) if j == 0 or (p - peak_idx[j - 1]) * HOP_S >= 0.10]` |
| agent/slot_grounding.py:155 | `0.8` | `if window and difflib.SequenceMatcher(None, v, window).ratio() >= 0.8:` |
| agent/tts.py:212 | `1.0` | `if speed != 1.0:` |
| agent/twilio_bridge.py:176 | `0.0` | `window = np.where((t >= 0.0) & (t <= 1.0), 0.42 - 0.5 * np.cos(2 * np.pi * t) + 0.08 * np.cos(4 * np.pi * t), 0.0)` |
| agent/twilio_bridge.py:176 | `1.0` | `window = np.where((t >= 0.0) & (t <= 1.0), 0.42 - 0.5 * np.cos(2 * np.pi * t) + 0.08 * np.cos(4 * np.pi * t), 0.0)` |
| agent/vad_stream.py:129 | `0.001` | `if st is None or abs(st["start"] - start_abs) > 1e-3 or st["windows"] > n_full:` |
| agent/vad_stream.py:151 | `0.2` | `if duration_s < 0.2:` |
| agent/vad_stream.py:163 | `0.2` | `if duration_s < 0.2:` |
| clinic-api/clinic_extras.py:310 | `0.75` | `pick = "yes" if _rng.random() < 0.75 else "no"  # drawn for every doctor, so a doctor's value does not depend on who else has one` |
| clinic-api/main.py:802 | `0.8` | `and not any(difflib.SequenceMatcher(None, _bare(w), n).ratio() >= 0.8 for n in noise if len(n) >= 3)` |
| clinic-api/main.py:808 | `0.72` | `return all(any(difflib.SequenceMatcher(None, w.lower(), t).ratio() >= 0.72 for t in own) for w in extra)` |
| clinic-api/main.py:895 | `0.05` | `return [d for r, d in scored if top - r <= 0.05]` |
| main.py:4828 | `0.55` | `top = next((c for c in found.get("candidates") or [] if c.get("kind") in ("district", "police_station") and c.get("score", 0) >= 0.55), None)` |
| main.py:5475 | `0.6` | `if getattr(session, "last_agreement", 1.0) >= 0.6:  # a garbled turn does not move the department being discussed` |
| main.py:5671 | `0.05` | `if wholly and lid_ok and agree(other) - agree(est) >= 0.05:` |
| main.py:5678 | `0.75` | `if r_est is not None and agree(est) >= 0.75 and agree(est) >= agree(lang) - 0.15 and (getattr(r_est, "text", "") or "").strip():` |
| main.py:5700 | `0.5` | `if wholly and hi_agree >= 0.5:` |
| main.py:5711 | `0.6` | `if en_text.isascii() and len(en_text.split()) >= 3 and en_agree >= 0.6:` |
| main.py:5846 | `0.95` | `and lid.confidence >= 0.95` |
| main.py:5847 | `0.05` | `and (lid.scores or {}).get("en", 0.0) < 0.05` |
| main.py:5848 | `0.95` | `and float(getattr(result, "decoder_agreement", 0.0) or 0.0) >= 0.95` |
| main.py:5886 | `0.75` | `if bn_agree >= 0.75 and bn_agree >= agree + margin:` |
| main.py:6085 | `0.85` | `and script_share(_heard, detected_lang) >= 0.85` |
| main.py:6086 | `0.85` | `and asr_result.decoder_agreement >= 0.85` |
| main.py:6099 | `0.85` | `and script_share(_heard, detected_lang) >= 0.85` |
| main.py:6100 | `0.85` | `and asr_result.decoder_agreement >= 0.85` |
| main.py:6213 | `0.5` | `or ((getattr(session, "last_route", None) is not None or getattr(session, "dept_pending", None) is not None) and float(asr_result.decoder_agreement or` |
| main.py:6229 | `0.25` | `if 0.25 <= _agr < LOW_SCORE_REASK and not _slot_ctx and len(text.split()) >= 2 and session.low_score_reasks < 1 and classify_yes_no(text, lang) is Non` |
| main.py:8596 | `0.85` | `if answer is None and target != lang and len(text.split()) >= 3 and script_share(text, lang) >= 0.85:` |
| main.py:8600 | `0.85` | `if answer in (None, "no") and not fresh_sentence and target != lang and len(text.split()) >= 4 and script_share(text, target) >= 0.85:` |
| main.py:8828 | `0.75` | `return len(words) >= 2 and script_share(text, "hi") >= 0.95 and agreement >= 0.75` |
| main.py:8828 | `0.95` | `return len(words) >= 2 and script_share(text, "hi") >= 0.95 and agreement >= 0.75` |
| main.py:8859 | `0.6` | `session.lang_lock_weak = agreement < 0.6` |
| main.py:8884 | `0.5` | `if script_share(text, candidate) >= 0.5:` |
| main.py:9103 | `0.08` | `return len(close) > 1 and abs(best(close[0]) - best(close[1])) < 0.08` |
| main.py:9117 | `0.6` | `return any(difflib.SequenceMatcher(None, a, name_script.name_skeleton(g)).ratio() >= 0.6 for g in given)` |
| main.py:10088 | `0.85` | `if len(text.split()) < 4 or getattr(asr_result, "decoder_agreement", 0.0) < 0.85 or off_topic.has_health_word(text):` |

## Part 6. Integer thresholds written inline in a comparison (word counts, lengths, streaks)

Values `0`, `1`, `-1` are skipped. Most are `len(words) >= N`-style rules.


#### agent/abuse.py

* `agent/abuse.py:148` **2**: `return "abuse_first" if count <= 1 else "abuse_second" if count == 2 else "abuse_final"`
* `agent/abuse.py:152` **3**: `return count >= 3`

#### agent/admission.py

* `agent/admission.py:255` **200**: `return r.status_code == 200`

#### agent/age_cues.py

* `agent/age_cues.py:43` **120**: `if m and 0 < int(m.group(1)) <= 120:`

#### agent/apology.py

* `agent/apology.py:108` **4**: `return len(re.sub(r"[\s,।.!?،-]+", "", stripped)) <= 4`

#### agent/asr.py

* `agent/asr.py:189` **2**: `if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], list):`

#### agent/asr_metrics.py

* `agent/asr_metrics.py:99` **2**: `if len(groups) < 2:`

#### agent/asr_refine.py

* `agent/asr_refine.py:71` **2**: `if alt_ambiguous or len(alt_exact) >= 2:`

#### agent/audio_quality.py

* `agent/audio_quality.py:210` **5**: `if frames.shape[0] < 5:`
* `agent/audio_quality.py:401` **3**: `and len(tokens[0]) <= 3`
* `agent/audio_quality.py:407` **4**: `if script and letters and len(letters) >= 4:`
* `agent/audio_quality.py:410` **5**: `if len(tokens) >= 5:`

#### agent/bn_normalize.py

* `agent/bn_normalize.py:157` **100**: `if n < 100:`
* `agent/bn_normalize.py:159` **1000**: `if n < 1000:`
* `agent/bn_normalize.py:240` **4**: `if 4 <= hour24 < 12:`
* `agent/bn_normalize.py:240` **12**: `if 4 <= hour24 < 12:`
* `agent/bn_normalize.py:242` **12**: `if 12 <= hour24 < 16:`
* `agent/bn_normalize.py:242` **16**: `if 12 <= hour24 < 16:`
* `agent/bn_normalize.py:244` **16**: `if 16 <= hour24 < 18:`
* `agent/bn_normalize.py:244` **18**: `if 16 <= hour24 < 18:`
* `agent/bn_normalize.py:246` **18**: `if 18 <= hour24 < 20:`
* `agent/bn_normalize.py:246` **20**: `if 18 <= hour24 < 20:`
* `agent/bn_normalize.py:259` **30**: `if mm == 30:`
* `agent/bn_normalize.py:261` **15**: `if mm == 15:`
* `agent/bn_normalize.py:263` **45**: `if mm == 45:`
* `agent/bn_normalize.py:288` **12**: `if not 1 <= m <= 12:`

#### agent/bn_respell.py

* `agent/bn_respell.py:185` **3**: `if len(rest) < 3 or rest[0] not in _CONSONANTS or rest[1] == _VIRAMA:`
* `agent/bn_respell.py:187` **2**: `if sum(1 for ch in rest if ch in _CONSONANTS and ch not in ("\u0982", "\u0983")) < 2:`

#### agent/body_imaging.py

* `agent/body_imaging.py:74` **40**: `if not t or len(t.split()) > 40:  # a caller who has forgotten the test's name talks around it: price, when to come, what the doctor said`

#### agent/booking_capture.py

* `agent/booking_capture.py:93` **3**: `_LOAN_DIGIT_WORDS = {w: d for w, d in _EXTRA_DIGIT_WORD.items() if not w.isascii() and len(w) >= 3 and w != "এইট"}  # "এইটা" is "this one", never an eight`
* `agent/booking_capture.py:105` **2**: `if tok.startswith(word) and len(tok) - len(word) <= 2:`
* `agent/booking_capture.py:161` **10**: `if digits.startswith(prefix) and len(digits) - len(prefix) == 10:`
* `agent/booking_capture.py:164` **10**: `return digits if len(digits) == 10 and digits[0] in "6789" else None`
* `agent/booking_capture.py:202` **6**: `short = len(t.split()) <= 6`
* `agent/booking_capture.py:206` **3**: `return digits if 1 <= len(digits) <= 3 else ""`
* `agent/booking_capture.py:224` **10**: `if len(buffer) + len(extra) > 10 and buffer.endswith(extra):`
* `agent/booking_capture.py:240` **6**: `if said_as_number and asked and total <= 6:`
* `agent/booking_capture.py:245` **3**: `if said_as_number and not whole and (asked or buffer or len(digits) >= 3):`
* `agent/booking_capture.py:257` **7**: `elif buffer and len(buffer) + len(digits) > 10 and len(digits) >= 7:`
* `agent/booking_capture.py:257` **10**: `elif buffer and len(buffer) + len(digits) > 10 and len(digits) >= 7:`
* `agent/booking_capture.py:264` **10**: `if len(candidate) < 10:`
* `agent/booking_capture.py:270` **10**: `if candidate.startswith(prefix) and len(candidate) - len(prefix) == 10:`
* `agent/booking_capture.py:273` **10**: `if len(body) == 10:`
* `agent/booking_capture.py:344` **3**: `if len(phone_words) >= 3:`
* `agent/booking_capture.py:347` **4**: `if not 1 <= len(words) <= 4:`
* `agent/booking_capture.py:354` **2**: `if sum(1 for ch in name if ch.isalpha()) < 2:`
* `agent/booking_capture.py:472` **24**: `if 0 <= hour <= 24 and (m.group(2) is None or int(m.group(2)) < 60):`
* `agent/booking_capture.py:472` **60**: `if 0 <= hour <= 24 and (m.group(2) is None or int(m.group(2)) < 60):`
* `agent/booking_capture.py:519` **24**: `if hour > 24 or hour < 0 or minute > 59:`
* `agent/booking_capture.py:519` **59**: `if hour > 24 or hour < 0 or minute > 59:`
* `agent/booking_capture.py:521` **13**: `if hour >= 13 or hour == 0:`
* `agent/booking_capture.py:534` **8**: `pick = hour if 8 <= hour <= 12 else hour % 12 + 12`
* `agent/booking_capture.py:534` **12**: `pick = hour if 8 <= hour <= 12 else hour % 12 + 12`
* `agent/booking_capture.py:536` **8**: `pick = hour if hour >= 8 else hour + 12`
* `agent/booking_capture.py:588` **31**: `if n and 1 <= n <= 31:`
* `agent/booking_capture.py:591` **12**: `year, month = (year + 1, 1) if month == 12 else (year, month + 1)`
* `agent/booking_capture.py:639` **2**: `if i >= 2 and words[i - 2 : i] == ["day", "after"]:`
* `agent/booking_capture.py:658` **2**: `if i in used or len(w) < 2 or w.isdigit() or w in _FILLER or w in _HOUR_WORDS:`
* `agent/booking_capture.py:665` **2**: `if base and len(base) >= 2 and key.startswith(base) and key[len(base) :] in ("", "3", "6", "36", "33", "63"):`
* `agent/booking_capture.py:687` **2**: `if i in used or (w.isdigit() and len(w) > 2):`
* `agent/booking_capture.py:741` **3**: `if hours and len(words) <= 3 and rest_is_tail:`
* `agent/booking_capture.py:761` **13**: `if period is not None or hour < 13 and hour != 0 and _inside(hour * 60 + minute, window):`
* `agent/booking_capture.py:763` **12**: `flipped = (hour + 12) % 24 if hour < 12 else hour - 12`
* `agent/booking_capture.py:777` **12**: `return f"{(h % 12) or 12}:{mi:02d} {'AM' if h < 12 else 'PM'}"`
* `agent/booking_capture.py:1006` **4**: `if len(ws) == 1 and ws[0] and len(ws[0]) <= 4 and ws[0].lower() not in _NOT_YES_OR_NO:  # (a short sound: a longer word is a name being corrected)`
* `agent/booking_capture.py:1100` **120**: `if m and 0 < int(m.group(1)) <= 120:`
* `agent/booking_capture.py:1146` **2**: `if len(t) < 2 or t in _NO_ADDRESS or t in _PS_BARE_NO:`
* `agent/booking_capture.py:1188` **13**: `return 13 <= int(age_value) <= 17`
* `agent/booking_capture.py:1188` **17**: `return 13 <= int(age_value) <= 17`
* `agent/booking_capture.py:1197` **3**: `return 0 < len(t.split()) <= 3 and re.match(r"(?:ইংলিশ|ইংরেজ|ইংরাজ|ইংলীশ|english|इंग्लिश|अंग्रेज)", t, re.I) is not None`
* `agent/booking_capture.py:1270` **5**: `refused = not matched and (_refuses_station(station) or len(station.split()) > 5)`
* `agent/booking_capture.py:1319` **2**: `if len(candidates) >= 2:  # a number-sounding word that fits two ages (7 or 60): ask, never pick`
* `agent/booking_capture.py:1396` **2**: `prompt("phone_partial_two" if len(step.buffer) == 2 else "phone_partial_long", lang, n=len(step.buffer), digits=spoken_digit_groups(step.buffer))`
* `agent/booking_capture.py:1397` **2**: `if len(step.buffer) == 2 or len(step.buffer) >= 6`
* `agent/booking_capture.py:1397` **6**: `if len(step.buffer) == 2 or len(step.buffer) >= 6`
* `agent/booking_capture.py:1480` **20**: `if n % 10 == 0 and n >= 20 and i + 1 < len(toks):`
* `agent/booking_capture.py:1492` **120**: `if m and 0 < int(m.group(1)) <= 120:`
* `agent/booking_capture.py:1497` **120**: `if spoken and 0 < spoken <= 120:`
* `agent/booking_capture.py:1504` **120**: `if digits is not None and 0 < int(digits) <= 120:`
* `agent/booking_capture.py:1510` **120**: `if n and 0 < n <= 120:`
* `agent/booking_capture.py:1537` **3**: `if len(t) < 3 or t.lower() in _NO_ADDRESS:`
* `agent/booking_capture.py:1589` **7**: `if age and _active(st) and st.action == "book_appointment" and st.slots.get("_phone_pending") and not st.slots.get("patient_age") and confirm_answer(text, lang) is None a`
* `agent/booking_capture.py:1689` **7**: `new_number = read_digits(text)[1] >= 7  # a whole new number in this sentence`
* `agent/booking_capture.py:1716` **2**: `if len(candidates) >= 2:`
* `agent/booking_capture.py:1768` **2**: `if len(step.buffer) >= 6 or len(step.buffer) == 2:`
* `agent/booking_capture.py:1768` **6**: `if len(step.buffer) >= 6 or len(step.buffer) == 2:`
* `agent/booking_capture.py:1769` **6**: `spoken = prompt("phone_partial_long" if len(step.buffer) >= 6 else "phone_partial_two", lang, n=len(step.buffer), digits=spoken_digit_groups(step.buffer))`
* `agent/booking_capture.py:1806` **7**: `when = read_when(text, asked_time, window=window, today=today, want_day=(not st.slots.get("date")) or len(text.split()) <= 7)`
* `agent/booking_capture.py:1820` **2**: `if asked_time or asked_day or len(found) == 2:`
* `agent/booking_capture.py:1923` **5**: `if not tokens or len(tokens) > 5:`

#### agent/booking_flow.py

* `agent/booking_flow.py:371` **3**: `if len(tokens) > 3 and any(tok in _QUESTION_TOKENS for tok in tokens):`

#### agent/call_end.py

* `agent/call_end.py:199` **5**: `if " " in cue or len(cue) >= 5:`

#### agent/call_later.py

* `agent/call_later.py:73` **4**: `if len(s) >= 4 and _GIVE_TIME_RE.search(s) and _WILL_GIVE_RE.search(s) and not _VISIT_RE.search(s):`
* `agent/call_later.py:75` **4**: `if len(s) < 4 or not _LATER_RE.search(s):`

#### agent/catalogue_forms.py

* `agent/catalogue_forms.py:42` **2**: `return len(word) >= 2 and word.isalnum() and word.upper() == word and any(c.isalpha() for c in word)`

#### agent/channel_quality.py

* `agent/channel_quality.py:65` **8000**: `if sample_rate <= 8000:`
* `agent/channel_quality.py:67` **32**: `if len(samples) < 32:`
* `agent/channel_quality.py:80` **5**: `if len(energies) < 5:`
* `agent/channel_quality.py:125` **10**: `if len(energies) < 10:`

#### agent/clinical_terms.py

* `agent/clinical_terms.py:25` **3**: `_SKELETONS = {term: [s for s in (skeleton(f) for f in forms) if len(s) >= 3] for term, forms in TERMS.items()}`
* `agent/clinical_terms.py:31` **4**: `if len(sk) < 4:`

#### agent/clip_chunks.py

* `agent/clip_chunks.py:45` **2**: `if w.getsampwidth() != 2 or w.getnchannels() != 1:`

#### agent/combined_question.py

* `agent/combined_question.py:48` **4**: `if (" " + c.strip() + " ") in padded or (len(c.strip()) > 4 and c.strip() in norm_text):`

#### agent/conditioning.py

* `agent/conditioning.py:65` **5**: `if n < 5:`

#### agent/confusables.py

* `agent/confusables.py:147` **2**: `return {w: sorted(c) for w, c in sorted(by_word.items()) if len(c) >= 2}`

#### agent/date_phrase.py

* `agent/date_phrase.py:30` **10**: `suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")`
* `agent/date_phrase.py:30` **20**: `suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")`

#### agent/dept_list.py

* `agent/dept_list.py:58` **16**: `return bool(t) and len(t.split()) <= 16 and _has(t, _LIST) and (_has(t, _SITS) or _has(t, _AVAILABLE))`
* `agent/dept_list.py:63` **16**: `return bool(t) and len(t.split()) <= 16 and ((_has(t, _DOCTOR) and _has(t, _LIST)) or asks_who_sits(text))`
* `agent/dept_list.py:83` **20**: `return bool(t) and len(t.split()) <= 20 and _DOCTOR_REQUEST_RE.search(t) is not None`

#### agent/dept_talk.py

* `agent/dept_talk.py:61` **5**: `if t == wl or (len(wl) >= 5 and len(t) >= 5 and (t.startswith(wl) or wl.startswith(t))):`
* `agent/dept_talk.py:61` **5**: `if t == wl or (len(wl) >= 5 and len(t) >= 5 and (t.startswith(wl) or wl.startswith(t))):`
* `agent/dept_talk.py:63` **5**: `elif len(wl) >= 5 and len(t) >= 5 and not (t.isascii() and wl.isascii()):`
* `agent/dept_talk.py:63` **5**: `elif len(wl) >= 5 and len(t) >= 5 and not (t.isascii() and wl.isascii()):`
* `agent/dept_talk.py:65` **4**: `score = difflib.SequenceMatcher(None, a, b).ratio() if len(a) >= 4 and len(b) >= 4 else 0.0`
* `agent/dept_talk.py:65` **4**: `score = difflib.SequenceMatcher(None, a, b).ratio() if len(a) >= 4 and len(b) >= 4 else 0.0`
* `agent/dept_talk.py:90` **30**: `return len(t.split()) <= 30 and bool(_SIT.search(t)) and bool(_YESNO.search(t)) and not _WHO_WHEN_NAME.search(t)`
* `agent/dept_talk.py:134` **2**: `if len(parts) >= 2:`
* `agent/dept_talk.py:138` **3**: `cands = {c for c in cands if len(c) >= 3 and not c.isascii()}`
* `agent/dept_talk.py:139` **2**: `best = max((difflib.SequenceMatcher(None, w, c).ratio() for w in windows for c in cands if w and len(w) >= 2), default=0.0)`
* `agent/dept_talk.py:161` **2**: `if len(parts) >= 2:`
* `agent/dept_talk.py:164` **2**: `if len(alias.split()) >= 2:`
* `agent/dept_talk.py:166` **3**: `cands = {c for c in cands if len(c) >= 3 and not c.isascii()}`
* `agent/dept_talk.py:167` **3**: `best = max((difflib.SequenceMatcher(None, w, c).ratio() for w in windows for c in cands if w and len(w) >= 3), default=0.0)`
* `agent/dept_talk.py:218` **2**: `if len(parts) >= 2:`
* `agent/dept_talk.py:220` **3**: `cands = {c for c in cands if len(c) >= 3 and not c.isascii()}`
* `agent/dept_talk.py:227` **3**: `if not w or len(w) < 3:`
* `agent/dept_talk.py:307` **12**: `part_bn = "সকাল" if h < 12 else "দুপুর" if h < 15 else "বিকেল" if h < 18 else "সন্ধ্যা" if h < 20 else "রাত"`
* `agent/dept_talk.py:307` **15**: `part_bn = "সকাল" if h < 12 else "দুপুর" if h < 15 else "বিকেল" if h < 18 else "সন্ধ্যা" if h < 20 else "রাত"`
* `agent/dept_talk.py:307` **18**: `part_bn = "সকাল" if h < 12 else "দুপুর" if h < 15 else "বিকেল" if h < 18 else "সন্ধ্যা" if h < 20 else "রাত"`
* `agent/dept_talk.py:307` **20**: `part_bn = "সকাল" if h < 12 else "দুপুর" if h < 15 else "বিকেল" if h < 18 else "সন্ধ্যা" if h < 20 else "রাত"`
* `agent/dept_talk.py:308` **12**: `part_hi = "सुबह" if h < 12 else "दोपहर" if h < 15 else "शाम" if h < 20 else "रात"`
* `agent/dept_talk.py:308` **15**: `part_hi = "सुबह" if h < 12 else "दोपहर" if h < 15 else "शाम" if h < 20 else "रात"`
* `agent/dept_talk.py:308` **20**: `part_hi = "सुबह" if h < 12 else "दोपहर" if h < 15 else "शाम" if h < 20 else "रात"`
* `agent/dept_talk.py:311` **30**: `if m == 30:`
* `agent/dept_talk.py:317` **30**: `if m == 30:`
* `agent/dept_talk.py:322` **12**: `return f"{h12}:{m:02d} {'AM' if h < 12 else 'PM'}"`

#### agent/disclosure.py

* `agent/disclosure.py:66` **2**: `if len(parts) < 2:`

#### agent/distress.py

* `agent/distress.py:74` **3**: `if len(wa) < 3 or len(wb) < 3:`
* `agent/distress.py:74` **3**: `if len(wa) < 3 or len(wb) < 3:`
* `agent/distress.py:112` **2**: `if unanswered_in_a_row >= 2:`

#### agent/doctor_cues.py

* `agent/doctor_cues.py:120` **4**: `if len(parts[0]) >= 4:`
* `agent/doctor_cues.py:123` **2**: `return list(dict.fromkeys(c for c in (_clean(f) for f in forms) if len(c) >= 2))`

#### agent/doctor_facts.py

* `agent/doctor_facts.py:53` **4**: `return 1 <= len(toks) <= 4 and any(t in _QUALITY_WORDS for t in toks) and all(t in _QUALITY_WORDS or t in _QUALITY_FILLER for t in toks)`
* `agent/doctor_facts.py:58` **8**: `return len(t.split()) <= 8 and _WHICH_DOCTOR.search(t) is not None`

#### agent/doctor_origin.py

* `agent/doctor_origin.py:24` **30**: `if not t or len(t.split()) > 30 or _NOT_ABOUT_DOCTOR.search(t):`

#### agent/doctor_search.py

* `agent/doctor_search.py:122` **2**: `if len(options) < 2:`
* `agent/doctor_search.py:148` **4**: `if idx < len(options) and _has(t, words) and len(t.split()) <= 4:`
* `agent/doctor_search.py:205` **12**: `return "morning" if h < 12 else "noon" if h < 15 else "afternoon" if h < NIGHT_FROM else "night"`
* `agent/doctor_search.py:205` **15**: `return "morning" if h < 12 else "noon" if h < 15 else "afternoon" if h < NIGHT_FROM else "night"`
* `agent/doctor_search.py:379` **12**: `return "morning" if h < 12 else "afternoon" if h < 16 else "evening"`
* `agent/doctor_search.py:379` **16**: `return "morning" if h < 12 else "afternoon" if h < 16 else "evening"`
* `agent/doctor_search.py:449` **2**: `hit = [p for p in parts if len(p) >= 2 and any(_token_is(w, p) for w in words)]`
* `agent/doctor_search.py:451` **3**: `if n == 1 and len(hit[0]) < 3 and len(parts) > 1:`
* `agent/doctor_search.py:469` **3**: `said = [(w, k) for w, k in said if len(k) >= 3]`
* `agent/doctor_search.py:478` **3**: `if len(key) >= 3 and any(same_given_name(w, part) for w, _ in said):`

#### agent/echo_cancel.py

* `agent/echo_cancel.py:394` **3**: `if self._since_delay >= self.delay_update * (4 if self._stable_updates >= 3 else 1):`
* `agent/echo_cancel.py:452` **3200**: `if n < 3200 or ref_long.size < n:`

#### agent/echo_check.py

* `agent/echo_check.py:76` **3**: `if len(sk) >= 3:`
* `agent/echo_check.py:85` **3**: `return any((c in words) if len(c) <= 3 and c != "?" else (c in t) for c in _CUES)`
* `agent/echo_check.py:94` **8**: `if not 1 <= len(said) <= 8 or not asks_back(user_text):`
* `agent/echo_check.py:105` **4**: `need = 1.0 if min(len(sk), len(sk2)) <= 4 else 0.86`

#### agent/endpointing.py

* `agent/endpointing.py:424` **3**: `return len(last) <= 3 and ("\u09cd" in last or "\u094d" in last)`
* `agent/endpointing.py:438` **2**: `if tokens and tokens[-1] in _TEST_NOUNS and len(tokens) >= 2:`
* `agent/endpointing.py:466` **10**: `return "complete" if n_digits >= 10 else "incomplete"`
* `agent/endpointing.py:491` **3**: `if low in _YES_NO and len(low.split()) <= 3:`
* `agent/endpointing.py:494` **10**: `return bool(only_digits and n_digits >= 10)`

#### agent/english_in_bengali.py

* `agent/english_in_bengali.py:91` **2**: `return len(found) >= 2 and bool(found - _WEAK) and hits * 4 >= len(toks)`

#### agent/fast_path.py

* `agent/fast_path.py:331` **3**: `idx = next((i for i, t in enumerate(tokens) if t == f or (len(f) >= 3 and (t.startswith(f) or difflib.SequenceMatcher(None, f, t).ratio() >= 0.75))), None)`
* `agent/fast_path.py:346` **3**: `if len(prev) <= 3:`
* `agent/fast_path.py:379` **6**: `+ ([k for k in f.get("keywords_en", []) if " " in k.strip() or len(k.strip()) >= 6] if lang in ("bn", "hi") else [])  # sourav 2026-10-16: no short English words (cash/gp`
* `agent/fast_path.py:475` **2**: `if len(eligible) >= 2:`
* `agent/fast_path.py:549` **4**: `if len(f) <= 4:`
* `agent/fast_path.py:986` **4**: `if table.greeting_reply and table.any(text, table.greeting) and len(text.split()) <= 4:`
* `agent/fast_path.py:989` **4**: `if table.thanks_reply and table.any(text, table.thanks) and len(text.split()) <= 4:`

#### agent/fastpath_guards.py

* `agent/fastpath_guards.py:61` **4**: `if f" {c} " in padded or (len(c) > 4 and c in norm_text):`
* `agent/fastpath_guards.py:161` **2**: `if named < 2:`

#### agent/figures.py

* `agent/figures.py:31` **4**: `if len(digits) <= 4:`
* `agent/figures.py:34` **2**: `if len(groups[-1]) < 2 and len(groups) > 1:`
* `agent/figures.py:48` **4**: `if len(segment) <= 4:`

#### agent/form_index.py

* `agent/form_index.py:106` **3**: `if not fuzzy or len(token) < 3:`

#### agent/full_duplex.py

* `agent/full_duplex.py:170` **2**: `if width != 2:`

#### agent/hindi_in_bengali.py

* `agent/hindi_in_bengali.py:33` **3**: `if len(sk) >= 3:  # one or two consonants collide with half the Bengali dictionary`
* `agent/hindi_in_bengali.py:51` **3**: `if len(sk) >= 3 and sk in _SKELETONS and sk not in _BENGALI_COLLISIONS:`

#### agent/humanize.py

* `agent/humanize.py:35` **4**: `return MIN_CHARS <= len(t) <= MAX_CHARS and len(runs) <= 6 and all(len(r) <= 4 for r in runs)  # times and dates are fine; a phone number, an id or a long price is read e`
* `agent/humanize.py:35` **6**: `return MIN_CHARS <= len(t) <= MAX_CHARS and len(runs) <= 6 and all(len(r) <= 4 for r in runs)  # times and dates are fine; a phone number, an id or a long price is read e`

#### agent/imaging_words.py

* `agent/imaging_words.py:53` **5**: `if len(core) >= 5 and not core.isascii() and (core == "অ্যাবডোমেন" or clinical_terms._best("abdomen", core) >= 0.7):  # a scan was just named, so the bar is lower than an`

#### agent/lang_select.py

* `agent/lang_select.py:260` **2**: `if len(words) < 2 or agreement < ENGLISH_MIN_AGREEMENT or script_share(text, "en") < 0.9:`
* `agent/lang_select.py:342` **3**: `and len(r.text.split()) <= 3`

#### agent/language_switch.py

* `agent/language_switch.py:244` **3**: `if len(words) >= 3 and words[-1] in _NEG_ENDS_CLAUSE and any(n in words[-2] for names in _LANGUAGE_NAMES.values() for n in names):`
* `agent/language_switch.py:364` **4**: `short = len(words) <= 4`

#### agent/level.py

* `agent/level.py:69` **5**: `if frames.shape[0] < 5:`

#### agent/lid.py

* `agent/lid.py:213` **16000**: `if sr != 16000:`

#### agent/lost_found.py

* `agent/lost_found.py:65` **3**: `elif any(tok == p or (len(p) >= 3 and tok.startswith(p)) for tok in tokens):`

#### agent/multi_test_confirm.py

* `agent/multi_test_confirm.py:36` **2**: `if len(results) < 2:`
* `agent/multi_test_confirm.py:57` **2**: `if len(pairs) < 2:`
* `agent/multi_test_confirm.py:117` **2**: `if not expected or expected < 2:`

#### agent/name_groups.py

* `agent/name_groups.py:32` **2**: `if len(toks) >= 2:`
* `agent/name_groups.py:39` **2**: `return len(name_script.name_skeleton(a)) >= 2 and len(name_script.name_skeleton(b)) >= 2 and name_script.same_given_name(a, b)`
* `agent/name_groups.py:39` **2**: `return len(name_script.name_skeleton(a)) >= 2 and len(name_script.name_skeleton(b)) >= 2 and name_script.same_given_name(a, b)`
* `agent/name_groups.py:48` **2**: `return len(ka) >= 2 and ka == kb and difflib.SequenceMatcher(None, a, b).ratio() >= 0.75`
* `agent/name_groups.py:57` **2**: `given_word = toks[0] if len(toks) >= 2 else ""`
* `agent/name_groups.py:105` **2**: `return hits if best >= 2 else []`

#### agent/nato_letters.py

* `agent/nato_letters.py:64` **2**: `if pairs < 2:`
* `agent/nato_letters.py:80` **3**: `return "".join(best).upper() if len(best) >= 3 else None`

#### agent/near_end.py

* `agent/near_end.py:83` **5**: `if frames.shape[0] < 5:`
* `agent/near_end.py:109` **12**: `if v.size < 12:`
* `agent/near_end.py:161` **5**: `if frames.shape[0] < 5:`

#### agent/off_topic.py

* `agent/off_topic.py:94` **4**: `if tok == w or (tok.startswith(w) and (len(w) >= 4 or tok[len(w):] in _WORD_ENDINGS)):`
* `agent/off_topic.py:108` **6**: `return bool(t) and len(t.split()) <= 6 and _HOW_ARE_YOU.search(t) is not None`

#### agent/owner_answers.py

* `agent/owner_answers.py:116` **3**: `if width > 1 and any(len(_sound(w)) > 3 for w in tokens[i : i + width]):`
* `agent/owner_answers.py:120` **4**: `if 4 <= len(snd) <= 6 and difflib.SequenceMatcher(None, snd, _SONOSCAN_SOUND).ratio() >= 0.85:`
* `agent/owner_answers.py:120` **6**: `if 4 <= len(snd) <= 6 and difflib.SequenceMatcher(None, snd, _SONOSCAN_SOUND).ratio() >= 0.85:`
* `agent/owner_answers.py:135` **10**: `if not t or len(t.split()) > 10 or not (_has(t, _SONOSCAN) or _mentions_sonoscan(t)):`
* `agent/owner_answers.py:142` **6**: `if place is None and len(t.split()) > 6 and not _has(t, _IDENTITY_CUES):`
* `agent/owner_answers.py:248` **16**: `return bool(t) and len(t.split()) <= 16 and _has(t, _HOW) and _has(t, _GO)`
* `agent/owner_answers.py:266` **24**: `return bool(t) and len(t.split()) <= 24 and _has(t, _PHONE_WORDS) and _has(t, _BOOKING_WORDS)`
* `agent/owner_answers.py:306` **14**: `if not t or len(t.split()) > 14:`
* `agent/owner_answers.py:433` **300**: `return n if 1 <= n <= 300 else None`
* `agent/owner_answers.py:453` **10**: `return tens[w] + (unit if unit and unit < 10 else 0)`
* `agent/owner_answers.py:492` **4**: `part = "সকাল" if 4 <= h24 < 12 else "দুপুর" if 12 <= h24 < 16 else "বিকেল" if 16 <= h24 < 18 else "সন্ধ্যা" if 18 <= h24 < 20 else "রাত"`
* `agent/owner_answers.py:492` **12**: `part = "সকাল" if 4 <= h24 < 12 else "দুপুর" if 12 <= h24 < 16 else "বিকেল" if 16 <= h24 < 18 else "সন্ধ্যা" if 18 <= h24 < 20 else "রাত"`
* `agent/owner_answers.py:492` **12**: `part = "সকাল" if 4 <= h24 < 12 else "দুপুর" if 12 <= h24 < 16 else "বিকেল" if 16 <= h24 < 18 else "সন্ধ্যা" if 18 <= h24 < 20 else "রাত"`
* `agent/owner_answers.py:492` **16**: `part = "সকাল" if 4 <= h24 < 12 else "দুপুর" if 12 <= h24 < 16 else "বিকেল" if 16 <= h24 < 18 else "সন্ধ্যা" if 18 <= h24 < 20 else "রাত"`
* `agent/owner_answers.py:492` **16**: `part = "সকাল" if 4 <= h24 < 12 else "দুপুর" if 12 <= h24 < 16 else "বিকেল" if 16 <= h24 < 18 else "সন্ধ্যা" if 18 <= h24 < 20 else "রাত"`
* `agent/owner_answers.py:492` **18**: `part = "সকাল" if 4 <= h24 < 12 else "দুপুর" if 12 <= h24 < 16 else "বিকেল" if 16 <= h24 < 18 else "সন্ধ্যা" if 18 <= h24 < 20 else "রাত"`
* `agent/owner_answers.py:492` **18**: `part = "সকাল" if 4 <= h24 < 12 else "দুপুর" if 12 <= h24 < 16 else "বিকেল" if 16 <= h24 < 18 else "সন্ধ্যা" if 18 <= h24 < 20 else "রাত"`
* `agent/owner_answers.py:492` **20**: `part = "সকাল" if 4 <= h24 < 12 else "দুপুর" if 12 <= h24 < 16 else "বিকেল" if 16 <= h24 < 18 else "সন্ধ্যা" if 18 <= h24 < 20 else "রাত"`
* `agent/owner_answers.py:495` **4**: `part = "सुबह" if 4 <= h24 < 12 else "दोपहर" if 12 <= h24 < 16 else "शाम" if 16 <= h24 < 20 else "रात"`
* `agent/owner_answers.py:495` **12**: `part = "सुबह" if 4 <= h24 < 12 else "दोपहर" if 12 <= h24 < 16 else "शाम" if 16 <= h24 < 20 else "रात"`
* `agent/owner_answers.py:495` **12**: `part = "सुबह" if 4 <= h24 < 12 else "दोपहर" if 12 <= h24 < 16 else "शाम" if 16 <= h24 < 20 else "रात"`
* `agent/owner_answers.py:495` **16**: `part = "सुबह" if 4 <= h24 < 12 else "दोपहर" if 12 <= h24 < 16 else "शाम" if 16 <= h24 < 20 else "रात"`
* `agent/owner_answers.py:495` **16**: `part = "सुबह" if 4 <= h24 < 12 else "दोपहर" if 12 <= h24 < 16 else "शाम" if 16 <= h24 < 20 else "रात"`
* `agent/owner_answers.py:495` **20**: `part = "सुबह" if 4 <= h24 < 12 else "दोपहर" if 12 <= h24 < 16 else "शाम" if 16 <= h24 < 20 else "रात"`
* `agent/owner_answers.py:497` **12**: `return f"{h12} {'AM' if h24 < 12 else 'PM'}"`
* `agent/owner_answers.py:607` **14**: `return bool(t) and len(t.split()) <= 14 and _has(t, _LINK) and _has(t, _LINK_TIME) and not _has(t, _OTHER_NUMBER)`
* `agent/owner_answers.py:633` **24**: `return bool(t) and len(t.split()) <= 24 and _has(t, _MONEY) and _has(t, _WHICH_NUMBER)`
* `agent/owner_answers.py:643` **6**: `return bool(t) and len(t.split()) <= 6 and _has(t, _BARE_COST)`

#### agent/phrases.py

* `agent/phrases.py:195` **2**: `if len(parts) < 2:`

#### agent/rare_test_cues.py

* `agent/rare_test_cues.py:73` **3**: `return len(tok) >= 3 and any(tok.startswith(s) for s in latin_stems)`
* `agent/rare_test_cues.py:86` **2**: `if len(tokens) < 2:`

#### agent/reask_policy.py

* `agent/reask_policy.py:89` **2**: `return ReaskDecision("reask", reason, key, self.consecutive >= 2, self.consecutive)`

#### agent/repeat_request.py

* `agent/repeat_request.py:112` **12**: `if not words or len(words) > 12:`
* `agent/repeat_request.py:137` **3**: `negated = "NOT" in m or any(re.search(r"(?:নি|নাই|ini|nai|नि)$", w) and len(w) > 3 for w in words)  # "না" apart, or fused into the verb ("বুঝিনি", "পাইনি")`
* `agent/repeat_request.py:143` **2**: `if "WHAT" in m and len(words) <= 2 and all(_classes(w) & {"WHAT", "SOFT"} for w in words):  # "ki?" / "কি" / "what?" alone`

#### agent/report_time_wording.py

* `agent/report_time_wording.py:27` **12**: `if hours <= 12:`
* `agent/report_time_wording.py:29` **24**: `if hours <= 24:`

#### agent/reschedule_request.py

* `agent/reschedule_request.py:78` **40**: `if not t or len(t.split()) > 40:`

#### agent/security_check.py

* `agent/security_check.py:184` **2**: `if len(name.split()) >= 2:  # a full name, not one word`
* `agent/security_check.py:188` **2**: `if len(addr.split()) >= 2:`
* `agent/security_check.py:199` **2**: `return len(self.answers) >= 2 and bool({"dob", "patient_id"} & set(self.answers))`
* `agent/security_check.py:228` **2**: `return self.finds >= 2`

#### agent/security_input.py

* `agent/security_input.py:417` **10**: `and units < 10`
* `agent/security_input.py:459` **100**: `if pending and cur and item < 100 and cur % 100 == 0:`
* `agent/security_input.py:461` **10**: `elif cur and cur % 10 == 0 and cur >= 20 and item < 10 and cur < 100:`
* `agent/security_input.py:461` **20**: `elif cur and cur % 10 == 0 and cur >= 20 and item < 10 and cur < 100:`
* `agent/security_input.py:461` **100**: `elif cur and cur % 10 == 0 and cur >= 20 and item < 10 and cur < 100:`
* `agent/security_input.py:471` **2**: `if len(numbers) == 2 and numbers[0] in (19, 20) and 0 <= numbers[1] < 100:`
* `agent/security_input.py:471` **100**: `if len(numbers) == 2 and numbers[0] in (19, 20) and 0 <= numbers[1] < 100:`
* `agent/security_input.py:490` **3**: `if len(ints) == 3 and ints[2] >= 1000 and 1 <= ints[0] <= 31 and 1 <= ints[1] <= 12:`
* `agent/security_input.py:490` **12**: `if len(ints) == 3 and ints[2] >= 1000 and 1 <= ints[0] <= 31 and 1 <= ints[1] <= 12:`
* `agent/security_input.py:490` **31**: `if len(ints) == 3 and ints[2] >= 1000 and 1 <= ints[0] <= 31 and 1 <= ints[1] <= 12:`
* `agent/security_input.py:490` **1000**: `if len(ints) == 3 and ints[2] >= 1000 and 1 <= ints[0] <= 31 and 1 <= ints[1] <= 12:`
* `agent/security_input.py:494` **1000**: `years = [x for x in ints if x >= 1000]`
* `agent/security_input.py:495` **31**: `days = [x for x in ints if 1 <= x <= 31]`
* `agent/security_input.py:531` **5**: `if 5 <= len(digits) <= 10 and digits == re.sub(r"[^\d]", "", joined) and not re.search(r"[a-z]", joined)`
* `agent/security_input.py:531` **10**: `if 5 <= len(digits) <= 10 and digits == re.sub(r"[^\d]", "", joined) and not re.search(r"[a-z]", joined)`

#### agent/semantic_cache.py

* `agent/semantic_cache.py:326` **64**: `if len(self._pending) > 64:`

#### agent/senior_voice.py

* `agent/senior_voice.py:137` **50**: `if frames.shape[0] < 50:`

#### agent/serial_lookup.py

* `agent/serial_lookup.py:45` **40**: `if not t or len(t.split()) > 40:`
* `agent/serial_lookup.py:60` **30**: `if not t or len(t.split()) > 30:`
* `agent/serial_lookup.py:103` **10**: `if spoken is None and len(flow["buf"]) >= 10:`

#### agent/slot_grounding.py

* `agent/slot_grounding.py:76` **3**: `if f" {c} " in padded or (len(c) > 3 and c in norm_text):  # whole word; longer stems also inside a word`
* `agent/slot_grounding.py:100` **3**: `return len(letters) >= 3`

#### agent/slot_grouping.py

* `agent/slot_grouping.py:154` **2**: `if len(fields) < 2:`

#### agent/speaker_change.py

* `agent/speaker_change.py:85` **20**: `if frames.shape[0] < 20:`
* `agent/speaker_change.py:199` **2**: `if self._streak >= 2:`

#### agent/speech_norm.py

* `agent/speech_norm.py:151` **100**: `if n < 100:`
* `agent/speech_norm.py:153` **1000**: `if n < 1000:`
* `agent/speech_norm.py:198` **4**: `if 4 <= hour24 < 12:`
* `agent/speech_norm.py:198` **12**: `if 4 <= hour24 < 12:`
* `agent/speech_norm.py:200` **12**: `if 12 <= hour24 < 16:`
* `agent/speech_norm.py:200` **16**: `if 12 <= hour24 < 16:`
* `agent/speech_norm.py:202` **16**: `if 16 <= hour24 < 19:`
* `agent/speech_norm.py:202` **19**: `if 16 <= hour24 < 19:`
* `agent/speech_norm.py:212` **30**: `if mm == 30:`
* `agent/speech_norm.py:215` **2**: `if h12 == 2:`
* `agent/speech_norm.py:218` **15**: `if mm == 15:`
* `agent/speech_norm.py:220` **45**: `if mm == 45:`
* `agent/speech_norm.py:251` **12**: `if 1 <= int(m.group(2)) <= 12`
* `agent/speech_norm.py:307` **20**: `if n < 20:`
* `agent/speech_norm.py:309` **100**: `if n < 100:`
* `agent/speech_norm.py:312` **1000**: `if n < 1000:`
* `agent/speech_norm.py:402` **12**: `suffix = "AM" if hh < 12 else "PM"`
* `agent/speech_norm.py:406` **10**: `minutes = f"oh {number_to_en_words(mm)}" if mm < 10 else number_to_en_words(mm)`
* `agent/speech_norm.py:437` **12**: `if 1 <= int(m.group(2)) <= 12`

#### agent/spelled_letters.py

* `agent/spelled_letters.py:31` **2**: `if len(run) >= 2:`
* `agent/spelled_letters.py:40` **2**: `if 2 <= len(tok) <= 6 and tok.isalpha():`
* `agent/spelled_letters.py:40` **6**: `if 2 <= len(tok) <= 6 and tok.isalpha():`
* `agent/spelled_letters.py:65` **3**: `if not spelled or len(cand) < 3:`
* `agent/spelled_letters.py:67` **3**: `near = [name for code, name in codes.items() if len(code) >= 3 and _one_apart(cand, code)]`
* `agent/spelled_letters.py:105` **3**: `return "".join(letters).upper() if 3 <= len(letters) <= 5 else None`
* `agent/spelled_letters.py:105` **5**: `return "".join(letters).upper() if 3 <= len(letters) <= 5 else None`
* `agent/spelled_letters.py:171` **3**: `if not any(taken) and 3 <= j - i <= 5:  # a whole run that is not a code but is one letter from exactly one`
* `agent/spelled_letters.py:171` **5**: `if not any(taken) and 3 <= j - i <= 5:  # a whole run that is not a code but is one letter from exactly one`
* `agent/spelled_letters.py:173` **3**: `near = {c for c in codes if len(c) >= 3 and _one_apart(word, c)}`
* `agent/spelled_letters.py:234` **3**: `elif tok.isupper() and tok.isalpha() and len(up) >= 3:`
* `agent/spelled_letters.py:235` **3**: `near = {c for c in codes if len(c) >= 3 and _one_apart(up, c)}`
* `agent/spelled_letters.py:271` **3**: `if len(snd) >= 3:`
* `agent/spelled_letters.py:278` **3**: `if len(core) >= 3 and not core.isascii() and not _MATRA.search(core):`

#### agent/spoken_codes.py

* `agent/spoken_codes.py:86` **10**: `if digits.startswith(prefix) and len(digits) - len(prefix) == 10:`
* `agent/spoken_codes.py:89` **10**: `return digits if len(digits) == 10 and digits[0] in "6789" else None`

#### agent/test_availability.py

* `agent/test_availability.py:99` **3**: `return " ".join(x) if x and sum(len(w) for w in x) >= 3 else None`
* `agent/test_availability.py:124` **9**: `if have_frame_name(text) is not None and len(t.split()) <= 9:  # "<your place> X <is done>": the intent layer decides whether X is a test`
* `agent/test_availability.py:127` **14**: `if len(words) > 14:`
* `agent/test_availability.py:131` **9**: `if len(words) <= 9:`

#### agent/test_days.py

* `agent/test_days.py:45` **22**: `if not t or len(t.split()) > 22 or _ta._contains_cue(t, _ta._NOT_AVAILABILITY):`
* `agent/test_days.py:70` **6**: `return _join([names[d] for d in days if 0 <= d <= 6], lang)`
* `agent/test_days.py:75` **3**: `if len(closed) <= 3:`

#### agent/test_overview.py

* `agent/test_overview.py:43` **25**: `if not t or len(t.split()) > 25 or not _TEST_WORD.search(t):`

#### agent/tools_client.py

* `agent/tools_client.py:138` **409**: `if r.status_code == 409 and guarded and waits:`

#### agent/translit_frames.py

* `agent/translit_frames.py:35` **4**: `if len(words) < 4 or words[0] not in _DO or words[1] not in _YOU or words[2] not in _VERB:`
* `agent/translit_frames.py:39` **3**: `return name if sum(c.isalpha() for c in name) >= 3 else None`

#### agent/twilio_bridge.py

* `agent/twilio_bridge.py:208` **2**: `if width == 2:`
* `agent/twilio_bridge.py:212` **4**: `elif width == 4:`
* `agent/twilio_bridge.py:259` **2**: `if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":`

#### agent/unrelated_caller.py

* `agent/unrelated_caller.py:308` **4**: `if not norm or len(norm.split()) > 4:`
* `agent/unrelated_caller.py:342` **2**: `if len(name) >= 2 and not name.isdigit() and name not in _NOT_A_NAME:`

#### agent/vad_stream.py

* `agent/vad_stream.py:134` **64**: `if len(self._streams) > 64:  # forgotten calls`
* `agent/vad_stream.py:135` **300**: `for k in [k for k, v in self._streams.items() if time.monotonic() - v["used"] > 300]:`
* `agent/vad_stream.py:149` **16000**: `if key is not None and start_abs is not None and sr == 16000 and self._template is not None:`
* `agent/vad_stream.py:154` **16000**: `if sr != 16000:`

#### agent/visit_cues.py

* `agent/visit_cues.py:70` **2**: `if s not in ("late", "later", "baad", "pore", "porer", "পরে", "পরের", "একটু পরে", "बाद में", "बाद", "noon") and len(s) > 2`
* `agent/visit_cues.py:91` **20**: `if not toks or len(toks) > 20:`
* `agent/visit_cues.py:134` **30**: `if not toks or len(toks) > 30:`
* `agent/visit_cues.py:231` **4**: `if len(toks) > 4:`
* `agent/visit_cues.py:261` **30**: `if not toks or len(toks) > 30:`
* `agent/visit_cues.py:296` **30**: `if not toks or len(toks) > 30:`
* `agent/visit_cues.py:405` **25**: `if not toks or len(toks) > 25:`

#### agent/weekday_cues.py

* `agent/weekday_cues.py:111` **2**: `if len(tokens) < 2 or weekday_of(text) is None:`
* `agent/weekday_cues.py:118` **5**: `if len(tokens) <= 5 and (_has(tokens, _NEXT, ("আসছ", "সামনের", "আগামী", "आने", "अगल")) or any(t in _THIS for t in tokens)):`

#### agent/where_doctor_sits.py

* `agent/where_doctor_sits.py:57` **25**: `return len(t.split()) <= 25 and _STATED_FLOOR.search(t) is not None`
* `agent/where_doctor_sits.py:66` **25**: `if len(t.split()) > 25:`

#### clinic-api/booking_migrate.py

* `clinic-api/booking_migrate.py:293` **500**: `for doc in db.query(Doctor).filter(Doctor.consultation_fee_inr == 500).all():`
* `clinic-api/booking_migrate.py:295` **500**: `if fee and fee != 500:`

#### clinic-api/booking_service.py

* `clinic-api/booking_service.py:560` **10**: `return digits[-10:] if len(digits) >= 10 else ""`
* `clinic-api/booking_service.py:1205` **3**: `words = [w for w in _dept_fold(d.name).split() if w not in _DEPT_NAME_STOP and len(w) >= 3]`
* `clinic-api/booking_service.py:1207` **4**: `if len(w) <= 4:`
* `clinic-api/booking_service.py:1432` **4**: `if len(n) <= 4:`
* `clinic-api/booking_service.py:1572` **3**: `if len(out) == 3:`

#### clinic-api/geo_service.py

* `clinic-api/geo_service.py:207` **3**: `elif len(words) <= 3 and n == len(words):`

#### clinic-api/lab_days.py

* `clinic-api/lab_days.py:28` **6**: `if part.isdigit() and 0 <= int(part) <= 6:`

#### clinic-api/main.py

* `clinic-api/main.py:579` **7**: `"every_day": len(days) == 7,`
* `clinic-api/main.py:800` **3**: `if len(_bare(w)) > 3  # a very short word beside a surname is a misheard initial ("দেড় হক"), not a different first name`
* `clinic-api/main.py:802` **3**: `and not any(difflib.SequenceMatcher(None, _bare(w), n).ratio() >= 0.8 for n in noise if len(n) >= 3)`

#### clinic-api/patient_context.py

* `clinic-api/patient_context.py:118` **4**: `if v and v != NOT_PROVIDED_PHONE and len(str(v)) >= 4:`
* `clinic-api/patient_context.py:167` **100**: `int(score) if isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 100 else None`
* `clinic-api/patient_context.py:173` **2**: `if isinstance(r, (list, tuple)) and len(r) == 2 and isinstance(r[1], (int, float))`
* `clinic-api/patient_context.py:600` **200**: `if isinstance(v, str) and len(v) > 200:`

#### clinic-api/registry.py

* `clinic-api/registry.py:156` **5**: `return a.isdigit() and len(a) >= 5 and b.endswith(a) and b[: len(b) - len(a)].isalpha()`
* `clinic-api/registry.py:193` **6**: `if len(t) >= MIN_ADDRESS_TOKEN_LEN and t not in _ADDRESS_STOPWORDS and not (t.isdigit() and len(t) != 6)`
* `clinic-api/registry.py:206` **2**: `return len(words_shared) >= 2 or (pin_ok and len(words_shared) >= 1)`
* `clinic-api/registry.py:291` **2**: `if len(given) < 2:`
* `clinic-api/registry.py:301` **2**: `if len(matched) >= 2 and matched & STRONG_FACTORS:`

#### clinic-api/spelled_forms.py

* `clinic-api/spelled_forms.py:25` **2**: `return len(word) >= 2 and word.isalpha() and word.isascii() and word.upper() == word`

#### clinic-api/symptom_lexicon.py

* `clinic-api/symptom_lexicon.py:223` **2**: `if len(table_word) >= 2 and sentence_word.startswith(table_word):`
* `clinic-api/symptom_lexicon.py:227` **4**: `if len(table_word) >= 5 and len(sentence_word) >= 4 and _edit1(sentence_word, table_word):`
* `clinic-api/symptom_lexicon.py:227` **5**: `if len(table_word) >= 5 and len(sentence_word) >= 4 and _edit1(sentence_word, table_word):`
* `clinic-api/symptom_lexicon.py:229` **5**: `if len(table_word) >= 5 and len(sentence_word) > len(table_word):`
* `clinic-api/symptom_lexicon.py:288` **2**: `w = weight if q == 2 else weight - 0.25  # a near match never ties with an exact one (মাসিক "period" is one letter from মানসিক "mental")`

#### main.py

* `main.py:1026` **2**: `if sampwidth != 2:`
* `main.py:1039` **2**: `if width != 2:`
* `main.py:1107` **44**: `return proc.returncode == 0 and os.path.exists(wav_path) and os.path.getsize(wav_path) > 44`
* `main.py:1533` **3**: `if len(w) >= 3 and w.lower() not in ("dr", "doctor"):`
* `main.py:1548` **25**: `if repeat_ok or session.speaking_filler or session.booking is not None or len(text) < 25 or not text.rstrip().endswith(("?", "？")):`
* `main.py:1556` **2**: `if session.same_question_repeats >= 2:`
* `main.py:1733` **2**: `asked = bool(pend) and session.turn_count - pend[1] <= 2`
* `main.py:1771` **3**: `if not route or session.turn_count - route["turn"] > 3:`
* `main.py:2254` **3**: `if pend and session.turn_count - pend.get("turn", -99) <= 3:`
* `main.py:2262` **2**: `if oq is None and chk and session.turn_count - chk.get("turn", -99) <= 2:`
* `main.py:2407` **30**: `and len(text.split()) <= 30  # (was 6, then 12 -- a real sentence is never skipped for its length: "বলছি কি এক ডাক্তার ধন বাবুর চেম্বারে বসছে" has eight)`
* `main.py:2409` **2**: `and booking_capture.read_digits(text)[1] < 2`
* `main.py:2530` **2**: `if i == 0 or not (t == name or (t.startswith(name) and len(t) - len(name) <= 2)):`
* `main.py:2534` **3**: `len(prev) > 3 and prev.isalpha() and prev.lower() not in not_given`
* `main.py:2563` **2**: `if len(words) < 2 or not words[-1].lower() in _PRESENCE_WORDS:`
* `main.py:2568` **2**: `if not name or len(name) > 3 or (len(name) < 2 and not titled):`
* `main.py:2568` **3**: `if not name or len(name) > 3 or (len(name) < 2 and not titled):`
* `main.py:2630` **3**: `names = sep.join(found) if len(found) <= 3 else sep.join(found[:3])`
* `main.py:2728` **2**: `if len(parts) < 2:`
* `main.py:2759` **2**: `if not answered or (len(answered) < 2 and not rest):`
* `main.py:2791` **16**: `if not last or not _asks_when(text) or len(text.split()) > 16 or not any(w in last for w in _SITTING_WORDS):`
* `main.py:2835` **3**: `if pend is not None and session.turn_count - pend <= 3:`
* `main.py:2837` **10**: `if len(digits) >= 10:`
* `main.py:2838` **10**: `number = booking_capture.phone_from_digits(digits[-10:] if len(digits) > 10 else digits) or digits[:10]`
* `main.py:3335` **3**: `if not text or len(text.split()) < 3 or result.get("found") or result.get("ambiguous"):  # a bare one- or two-word answer to "which test?" is left to the "no such test" r`
* `main.py:3724` **4**: `if multi and session.turn_count - multi[1] <= 4 and any(w in low for w in _THESE):`
* `main.py:3735` **2**: `if lapsed and session.turn_count - lapsed[1] <= 2:`
* `main.py:3738` **2**: `if asked and session.turn_count - asked[1] <= 4 and getattr(session, "reasked_pending", 0) < 2:`
* `main.py:3738` **4**: `if asked and session.turn_count - asked[1] <= 4 and getattr(session, "reasked_pending", 0) < 2:`
* `main.py:3823` **600**: `if _relationship_cache["rules"] is None or now - _relationship_cache["at"] > 600:`
* `main.py:4029` **7**: `elif 0 < (d - today).days <= 7:`
* `main.py:4060` **16**: `return len(low.split()) <= 16 and any(w in low for w in _WHEN_ASK)`
* `main.py:4111` **2**: `if getattr(session, "unclear_streak", 0) >= 2:`
* `main.py:4160` **2**: `if skipped_days >= 2:  # today and the days after have nobody: the NEXT day that has somebody is told, with its date`
* `main.py:4197` **2**: `if len(sitting) >= 2:`
* `main.py:4260` **3**: `if pend and session.turn_count - pend["turn"] <= 3 and pend.get("say") and pend["kind"] in ("confirm_one", "pick") and _asks_when(text) and booking_capture.confirm_answer`
* `main.py:4285` **6**: `_names_him = doctor_search.choose_by_name(text, [[pend["doctor"].get("name", ""), pend["doctor"].get("full_name", "")]]) == 0 and len(text.split()) <= 6  # saying the off`
* `main.py:4313` **4**: `if idx < len(pend["doctors"]) and doctor_search._has(doctor_search._norm(text), words) and len(text.split()) <= 4:  # noqa: SLF001`
* `main.py:4331` **6**: `if chosen is not None and (booking_carryover.asks_to_book(text) or len(text.split()) <= 6 or _asks_when(text)):`
* `main.py:4352` **40**: `if wants_when and not wants_book and not sex and len(text.split()) <= 40:  # was 12: a real caller's sentence ("... একটা জেনারেল মেডিসিন এর একটা ডাক্তার দেখাতে চাই আজকে ক`
* `main.py:4480` **14**: `if n is None or not (1 <= n <= 31) or not wds or len(text.split()) > 14:`
* `main.py:4480` **31**: `if n is None or not (1 <= n <= 31) or not wds or len(text.split()) > 14:`
* `main.py:4536` **10**: `if not last or len(low.split()) > 10:`
* `main.py:4542` **2**: `if booking_capture.read_digits(text)[1] >= 2:`
* `main.py:4815` **3**: `if not text or len(text.split()) > 3:`
* `main.py:4970` **2**: `if len(toks) < 2 or len(name_script.name_skeleton(toks[0])) < 2:`
* `main.py:4970` **2**: `if len(toks) < 2 or len(name_script.name_skeleton(toks[0])) < 2:`
* `main.py:4988` **3**: `if booking is None and _offer and _offer.get("kind") == "confirm_one" and session.turn_count - _offer.get("turn", -99) <= 3:`
* `main.py:5077` **2**: `if flow["tries"] >= 2:`
* `main.py:5356` **2**: `if len(names) < 2:`
* `main.py:5486` **2**: `elif len(_sit) >= 2:`
* `main.py:5541` **2**: `if not marks or len(marks) < 2:`
* `main.py:5584` **2**: `if code.isalpha() and code.isascii() and code.upper() == code and len(code) >= 2:`
* `main.py:5668` **2**: `wholly = language_of_script(r_other.text, "?") == other and len(r_other.text.split()) >= 2`
* `main.py:5695` **2**: `wholly = language_of_script(getattr(r_hi, "text", ""), "?") == "hi" and len((r_hi.text or "").split()) >= 2`
* `main.py:5711` **3**: `if en_text.isascii() and len(en_text.split()) >= 3 and en_agree >= 0.6:`
* `main.py:5729` **2**: `if _lid is None or len(_languages_active) < 2:`
* `main.py:5828` **2**: `if len(both) == 2:`
* `main.py:5849` **3**: `and len((getattr(result, "text", "") or "").split()) >= 3`
* `main.py:6040` **6**: `and len(_heard.split()) < 6`
* `main.py:6055` **3**: `if len(_digits_said) >= 3 and _digit_hits * 2 >= _digit_total:`
* `main.py:6084` **4**: `and len(_heard.split()) >= 4`
* `main.py:6098` **4**: `and len(_heard.split()) >= 4`
* `main.py:6229` **2**: `if 0.25 <= _agr < LOW_SCORE_REASK and not _slot_ctx and len(text.split()) >= 2 and session.low_score_reasks < 1 and classify_yes_no(text, lang) is None and not any(ch.isd`
* `main.py:6245` **3**: `len(session.lang_history) >= 3`
* `main.py:6294` **2**: `and len(session.lang_history) >= 2`
* `main.py:6319` **5**: `bare_no = answer == "no" and len(text.split()) <= 5`
* `main.py:6334` **5**: `if answer == "yes" and len(text.split()) <= 5:`
* `main.py:6487` **2**: `if _prev_enquiry and session.turn_count - _prev_enquiry["turn"] <= 2:`
* `main.py:6538` **5**: `elif answer == "no" and len(text.split()) <= 5:`
* `main.py:6571` **2**: `if session.turn_count - asked_turn <= 2 and session.booking is None:`
* `main.py:6743` **10**: `if getattr(session, "last_spoken", "") and len(text.split()) <= 10:`
* `main.py:6790` **2**: `and booking_capture.read_digits(text)[1] < 2`
* `main.py:6805` **2**: `if pending_referral is not None and session.turn_count - pending_referral <= 2:`
* `main.py:6823` **2**: `if pending_weekdays is not None and session.turn_count - pending_weekdays <= 2:`
* `main.py:6831` **2**: `if pending_serial is not None and session.turn_count - pending_serial[0] <= 2:`
* `main.py:6838` **2**: `if pending_hours is not None and session.turn_count - pending_hours <= 2:`
* `main.py:6847` **2**: `if pending_day is not None and session.turn_count - pending_day[0] <= 2:`
* `main.py:6855` **2**: `if pending_when is not None and session.turn_count - pending_when <= 2:`
* `main.py:6865` **2**: `if intent in ("unclear", "smalltalk") and session.booking is None and _tools is not None and 2 <= len(text.split()) <= 20 and pending is None:`
* `main.py:6865` **20**: `if intent in ("unclear", "smalltalk") and session.booking is None and _tools is not None and 2 <= len(text.split()) <= 20 and pending is None:`
* `main.py:7060` **3**: `len(text.split()) >= 3`
* `main.py:7109` **3**: `if session.unclear_streak >= 3:`
* `main.py:7273` **6**: `if not _held_day or len(text.split()) <= 6:`
* `main.py:7524` **3**: `if field_name == "phone" and not capture_plan.digits and st.note_retry("phone") >= 3:`
* `main.py:7531` **2**: `elif field_name == "doctor_name" and st.note_retry("doctor_name") >= 2:`
* `main.py:7615` **6**: `if _wish and session.turn_count - _wish.get("turn", 0) > 6:`
* `main.py:7748` **3**: `if not missing or st.note_retry("model_failure") > 3:`
* `main.py:8008` **2**: `if len(text.split()) > 2:`
* `main.py:8163` **3**: `if reason == "too_many_attempts" or (reason == "not_authorized" and st.note_retry("change_denied") >= 3):`
* `main.py:8563` **3**: `if words and len(words) <= 3:`
* `main.py:8596` **3**: `if answer is None and target != lang and len(text.split()) >= 3 and script_share(text, lang) >= 0.85:`
* `main.py:8600` **4**: `if answer in (None, "no") and not fresh_sentence and target != lang and len(text.split()) >= 4 and script_share(text, target) >= 0.85:`
* `main.py:8748` **10**: `if len(phone) < 10:`
* `main.py:8749` **2**: `if session.history_attempts >= 2:`
* `main.py:8783` **2**: `elif session.history_attempts >= 2:`
* `main.py:8828` **2**: `return len(words) >= 2 and script_share(text, "hi") >= 0.95 and agreement >= 0.75`
* `main.py:9100` **2**: `c = name_skeleton("".join(parts[:-1])) if len(parts) >= 2 else ""`
* `main.py:9111` **2**: `if len(toks) < 2:`
* `main.py:9161` **2**: `if tok.endswith(suf) and len(tok) - len(suf) >= 2:`
* `main.py:9170` **14**: `if _fast_path is None or session.booking is not None or len(text.split()) > 14 or _DOCTOR_CUE.search(text) is None:`
* `main.py:9179` **2**: `if a in _NAME_FILLER or b in _NAME_FILLER or len(name_script.name_skeleton(a)) < 2:`
* `main.py:9212` **4**: `if pd and pd.get("kind") == "confirm_one" and pd.get("doctor") and session.turn_count - pd.get("turn", -99) <= 4:`
* `main.py:9244` **14**: `if _fast_path is None or _tools is None or not (text or "").strip() or len(text.split()) > 14:`
* `main.py:9250` **3**: `if pick and session.turn_count - pick["turn"] <= 3:`
* `main.py:9263` **3**: `elif ctx_info is not None and (len(text.split()) <= 3 or _text_has_surname_of(text, ctx_info)):`
* `main.py:9298` **16**: `if _fast_path is None or _tools is None or not (text or "").strip() or len(text.split()) > 16:`
* `main.py:9304` **8**: `if not ((when and sits) or nxt or (_asks_when(text) and sits and len(text.split()) <= 8)):`
* `main.py:9337` **3**: `return len((text or "").split()) <= 3 and greeting_words.is_greeting(text)`
* `main.py:9347` **3**: `if len(words) < 3 or session.booking is not None or _fast_path is None:`
* `main.py:9351` **2**: `open_chk = bool(chk) and session.turn_count - chk["turn"] <= 2`
* `main.py:9352` **3**: `open_one = bool(pend) and pend.get("kind") == "confirm_one" and session.turn_count - pend["turn"] <= 3`
* `main.py:9353` **3**: `open_pick = bool(pend) and pend.get("kind") == "pick" and session.turn_count - pend["turn"] <= 3`
* `main.py:9365` **2**: `if len(rest.split()) < 2:`
* `main.py:9392` **2**: `if not chk or session.turn_count - chk["turn"] > 2 or _fast_path is None:`
* `main.py:9395` **3**: `if len(words) < 3:`
* `main.py:9430` **2**: `if not name or len(name) > 3 or (len(name) < 2 and not titled):`
* `main.py:9430` **3**: `if not name or len(name) > 3 or (len(name) < 2 and not titled):`
* `main.py:9470` **20**: `if _tools is None or not (text or "").strip() or len(text.split()) > 20:`
* `main.py:9473` **2**: `if asked and session.turn_count - asked["turn"] <= 2:`
* `main.py:9505` **8**: `if not pend or len((text or "").split()) > 8:`
* `main.py:9525` **2**: `return " ".join(left) if 2 <= len(left) <= 3 and len(toks) <= 8 else ""`
* `main.py:9525` **3**: `return " ".join(left) if 2 <= len(left) <= 3 and len(toks) <= 8 else ""`
* `main.py:9525` **8**: `return " ".join(left) if 2 <= len(left) <= 3 and len(toks) <= 8 else ""`
* `main.py:9532` **14**: `if _fast_path is None or not (text or "").strip() or len(text.split()) > 14 or _names_offered_doctor(session, text):`
* `main.py:9622` **30**: `if _fast_path is None or _tools is None or _booking_open(session) or len(text.split()) > 30 or _names_offered_doctor(session, text):`
* `main.py:9626` **2**: `if chk and session.turn_count - chk["turn"] <= 2:`
* `main.py:9628` **4**: `answer = booking_capture.confirm_answer(text, lang) if len(text.split()) <= 4 else None  # a longer sentence is a new question, not a "yes"`
* `main.py:9675` **8**: `if (asks_good and asks_when) or (asks_when and not doctor_in_mind and not _text_names_a_doctor(text, lang) and len(text.split()) <= 8 and (mention is None)):`
* `main.py:9688` **20**: `if told.get("names") and not (asks_names or asks_good or asks_when or asks_origin) and len(text.split()) <= 20 and not mention and not booking_carryover.asks_to_book(text`
* `main.py:9696` **14**: `if not (asks_names or asks_good or asks_when or asks_origin) and len(text.split()) <= 14 and not mention:`
* `main.py:9745` **12**: `if digits.isdigit() and 1 <= int(digits) <= 12 and tok != digits:`
* `main.py:9762` **6**: `if last and last.get("dept") == topic and session.turn_count - last.get("turn", -99) <= 6:`
* `main.py:9768` **6**: `if _last and _last.get("dept") == topic and session.turn_count - _last.get("turn", -99) <= 6 and not _text_names_a_doctor(text, lang) and not booking_carryover.commits_to`
* `main.py:9837` **2**: `if len(items) < 2 or doctor_search.choose_by_name(text, [[d.get("name", ""), d.get("full_name", "")] for d in items]) is not None:`
* `main.py:9932` **12**: `if ap == "pm" and h < 12:`
* `main.py:9934` **7**: `elif not ap and 1 <= h <= 7:`
* `main.py:9936` **23**: `if 0 <= h <= 23:`
* `main.py:9944` **60**: `if _fast_path is None or _tools is None or session.booking is not None or len(text.split()) > 60:`
* `main.py:9953` **16**: `if not after and len(text.split()) <= 16:`
* `main.py:10088` **4**: `if len(text.split()) < 4 or getattr(asr_result, "decoder_agreement", 0.0) < 0.85 or off_topic.has_health_word(text):`
* `main.py:10342` **2**: `if bad >= 2:`
* `main.py:10344` **5**: `elif good >= 5:`


## Part 7. Counts

* named module-level numeric constants: 343
* float class fields and float function defaults: 69
* in-function env defaults: 15
* inline float comparisons: 92
* inline integer comparisons (not 0/1/-1): 513
