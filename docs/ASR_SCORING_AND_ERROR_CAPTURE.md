# Speech-to-text scoring and saving the wrongly heard word

Written 2026-11-02 from the code on `main`. Nothing here was built or run. Read with [transcription-rulebook.md](transcription-rulebook.md) (how the existing scoring works), [TEST_GUIDE.md](TEST_GUIDE.md) (layer L6) and [DASHBOARD_DATA_CONNECTION.md](DASHBOARD_DATA_CONNECTION.md).

## 1. What "perfect" can and cannot mean

A transcript is only wrong **relative to what was actually said**, and nothing in a live call knows that. So there are three levels of truth, and the design keeps them apart:

| Level | Truth comes from | Exact? | Where it applies |
|---|---|---|---|
| **Gold** | a human wrote the verbatim transcript from the original audio, by the rulebook | yes: the scoring arithmetic is exact and reproducible | a sampled, consented, locked set |
| **Caller-verified** | the caller corrected or confirmed the system (a "no, Sen" at a read-back, a "yes" to "did you mean...") | the *entity* is verified; the exact word spoken is inferred | every live call, no human needed |
| **Proxy** | the system's own disagreement (CTC vs RNNT, low agreement, a repair table firing, a refinement suggestion) | no: a signal that something was probably wrong | every live call |

What is achievable: **exact scoring on the gold set** (this exists), a **caller-verified error stream on live calls** (new), and a **calibration of the proxy against gold** (new: it tells you whether "agreement 0.8" really means 8% errors, which would replace several thresholds the code itself labels REASONED).

## 2. What exists today

| Piece | What it does | What it does not do |
|---|---|---|
| `agent/asr_metrics.py` | corpus WER and CER (total edits over total reference length, not a mean of rates); 95% interval that resamples **callers**; entity scores for doctor, test, number, yes/no: said, correct, missed, **wrong**, ambiguous | `align()` returns only the **counts** of substitutions, deletions and insertions. **It does not keep which word became which.** |
| `agent/transcript_rules.py`, `docs/transcription-rulebook.md` | the verbatim rule (write what was said, in the script it was said in), the normalisation applied to both sides, doctors and tests collapsed to one catalogue token | dates and times are not scored (the rulebook says so) |
| `agent/asr_manifest.py` | one row per utterance: audio path, opaque speaker id, split, real or synthetic, language, verbatim, difficulty tags, `locked`, `consent`; refuses a speaker in two splits, a changed locked set, a real row without consent | |
| `tools/asr_eval.py` | prints the tables above by language and by difficulty tag | writes no per-word error list |
| `ASRResult.alternatives`, `agent/asr_refine.py` (shadow mode) | the other decoder's text; a keep / switch / ask decision against the catalogue, **logged without the words** | not joined with an outcome yet (ADR 0004 names this as the next step) |
| Hand-kept confusion tables | `symptom_repair` (জাত, জার, জর mean জ্বর), `lang_select._EN_ASR_CONFUSABLES` (tame means time), `confusables`, `bn_respell`, `hindi_in_bengali`, `english_in_bengali`, `clinical_terms` | each entry was found by a person from a real call and typed in; nothing records how often it fires or whether it was right |
| `UTT_RING_DIR` (`/tmp/utt_ring`) | the last 40 utterances' audio, for debugging | on the container disk (wiped on restart), 40 files, no transcript beside it |

So the question "which word was wrongly detected?" is answered today **only by a person, reading a log, and typing a rule**.

## 3. Scoring: what to measure

Headline order for this product (WER is not the headline, because a clinic call turns on a handful of words):

1. **Critical-entity error**, per kind: doctor, test, number, yes/no, **plus** department/symptom words, place/police-station words, and the language-switch words. Report **wrong** (heard as another real entity) separately from **missed**; wrong is the dangerous one.
2. **CER** and **normalised WER** (the rulebook form).
3. **WER** on the raw verbatim form, for comparability.
4. **Language/script correctness**: right language chosen, text in the right script (a Bengali sentence written in Devanagari is a different failure from a wrong word).

Score **four texts**, not one, because the repair layers hide ASR errors from the caller and from the metrics:

| Text | Why |
|---|---|
| RNNT, CTC (each decoder) | which decoder, and the value of the second one |
| the text the router **chose** (`decoder_used`, language picked) | the ASR product |
| the text the agent **acted on** (after `fix_asr_confusables`, `symptom_repair`, spelled-code rescue, name repair, refine) | what actually reached intent and lookup |
| the **outcome** | was the right fact spoken, the right slot filled |

The gap between "chosen" and "acted on" is the contribution of the hand-written repair tables; the gap between "acted on" and "outcome" is what the intent and grounding layers lose or recover.

Always slice by: language heard, channel bucket (clean 16 k, narrowband 8 k, noisy, cross-talk), difficulty tag, speaker class (senior, child), decoder, ASR model version, call position (first turn vs later), flow state (booking name, phone, free question), and entity kind.

**Gold-set hygiene** (already enforced by the manifest; keep it): score against the **original telephone audio** (8 kHz through the Twilio path), never a cleaned copy; split by speaker; lock the test set by digest; never mix synthetic with real; report an interval over callers and say when there is only one caller.

## 4. Saving the wrongly heard word

### 4.1 What counts as a recorded error, and how sure we are

| Evidence | Strength | Example | Gives |
|---|---|---|---|
| **Human gold** | gold | reviewer transcript differs from the hypothesis | exact (reference word, heard word) with position |
| **Caller correction** | strong | at the read-back the caller says no and gives a new value (`correction_acknowledgement` already knows which fields changed) | (heard value, corrected value) for that field |
| **Caller confirmation of a suggestion** | strong | "did you mean Dr. Sen?" answered yes after the first reading was something else | (heard form, confirmed catalogue entry) |
| **Caller rejection** | medium | "did you mean...?" answered no | the heard form was **not** that entity |
| **Repair fired** | medium | `symptom_repair` replaced জাত with জ্বর; `fix_asr_confusables` replaced tame | (heard word, repaired word), but the repair itself could be wrong |
| **Decoder disagreement** | weak | CTC and RNNT differ on a catalogue word; refine says switch or ask | two candidate words, neither verified |
| **Re-ask or low agreement** | weak | agreement under 0.45 with a re-ask | "something in this utterance was wrong", no word |

Only gold and strong evidence should be allowed to change a rule or train anything. Medium and weak evidence select **what a human reviews first**.

### 4.2 The record (proposed)

```json
{ "id": "...", "ts": "...", "day": "2026-11-02", "call": "<day+id>", "turn": 4,
  "evidence": "caller_confirm", "strength": "strong", "status": "pending_review",
  "model": {"asr": "<name+version>", "lid": "<version>", "build": "<git sha>", "decode": "rnnt"},
  "audio": {"clip": "<durable ref or none>", "word_start_s": 1.42, "word_end_s": 1.91, "channel": "narrowband_8k",
            "issues": ["noisy"], "level_dbfs": -33, "speaker_class": "senior"},
  "language": {"heard": "bn", "reply": "bn", "lid_top": "hi", "lid_conf": 0.91, "engines_run": ["hi","en","bn"]},
  "asr": {"agreement": 0.62, "chosen_from": "rnnt", "ctc_word": "...", "rnnt_word": "..."},
  "op": "sub",
  "heard": "<word or masked>", "meant": "<word or catalogue token or masked>",
  "context": ["<up to 3 words before>", "<up to 3 after>"],
  "entity_kind": "doctor|test|number|yesno|symptom|place|name|phone|other",
  "catalogue_entry": "DOCTOR:Dr._A._Sen",
  "error_class": "phonetic_sub|merge|split|script|transliteration|code_switch|number_format|hallucination|truncation",
  "stage_hidden_by": "symptom_repair",
  "impact": {"reached_lookup": true, "wrong_fact_spoken": false, "recovered_by": "did_you_mean", "extra_turns": 1} }
```

* `heard` and `meant` are the *words*. For `entity_kind` in `{name, phone, address}` they are **masked** (section 5).
* `stage_hidden_by` names the repair layer that fixed it before the agent acted, which is the figure that tells you how much the tables are carrying.
* `impact` ties the error to the failure taxonomy (QUERY_AND_FAILURE_TAXONOMY): an error that was recovered with one extra turn is S2; one that put a wrong fact in the caller's ear is S0.
* Linked to the per-turn event by (day, call, turn).

### 4.3 What the store gives you

| View | Question |
|---|---|
| **Confusion table** | which (meant, heard) pairs are most frequent, per language, channel and decoder |
| **Cost ranking** | words ranked by frequency x severity x recovery cost, not by frequency alone |
| **Error class mix** | is it mostly phonetic substitution, merged or split words, wrong script, code-switching, number format |
| **Repair-table audit** | how often each hand-kept entry fires, how often it was right, and entries that never fire (candidates for removal) |
| **Decoder value** | when CTC and RNNT disagree, which one was right, and how often the second decoder saved the turn |
| **Threshold calibration** | actual error rate by decoder-agreement band and by LID-confidence band, to replace the REASONED values (agreement floors 0.25, 0.45, 0.5, 0.6, 0.85; LID 0.55) |
| **Refine shadow scoring** | of the switch/ask decisions, how many were right (the ADR 0004 follow-up) |
| **Release comparison** | the same confusion table, before and after a model, decode or prompt change |
| **Review queue** | strong-evidence and entity-wrong items first, then a stratified random sample per bucket per day |

### 4.4 The code change that unlocks the offline half

`align()` keeps only counts. A small pure function that returns the **operation list** (for each edit: op, reference word, heard word, positions) would let `tools/asr_eval.py` write a `--pairs-out` file for every gold utterance. It lives in `agent/asr_metrics.py` (a pure module, no orchestrator import) and is tested in `tests/test_asr_evaluation.py`. This needs no live data and no consent decision, so it can be done first. The existing `Edits` result must stay unchanged so current callers and tests are unaffected.

### 4.5 Where live capture would hook in (all seen in `main.py`)

* after recognition in `_dispatch_turn`: raw text, `decoder_used`, `decoder_agreement`, `alternatives`, engines run, language picked;
* each repair point: `fix_asr_confusables`, `symptom_repair`, `_with_spelled_tests` / `_normalise_spelled`, `_name_answer_repair`, `_asr_refine_shadow`;
* the correction path: `correction_acknowledgement` (`changed` fields with prior and new values);
* the pending-entity yes or no (`entity_confirmation`);
* the "did you say forty-four?" word check (`_answer_word_check`).

Each hook writes an event through the existing call recorder, so it costs a queue put (no new blocking work in the call path).

## 5. Privacy, consent and retention: decide before saving anything

| Fact (checked) | Consequence |
|---|---|
| The greeting's recording notice is **off by default** (`CALL_RECORDING_NOTICE` defaults to `0`). The agent has no consent capture; `consent` exists only as a field in the evaluation manifest. | Saving **audio** of live callers has no consent behind it today. |
| `HANDOVER.md` section 9: consent for using call audio is "the programme-ending risk" (DPDP purpose limitation); quality-monitoring recordings are not automatically training data. | Keep the review/audit purpose and any model-training purpose separate in the record. |
| The agent log already contains recognised text and phone digits (`main.py:5947`, `6921`). | A new store must not copy that habit: it needs access control and retention of its own. |
| The call journal holds unredacted names, phones and addresses. | The error store reads only the allow-listed fields. |

Proposed tiers:

| Tier | What is stored | Condition |
|---|---|---|
| **A, always** | the pair for **catalogue entities, yes/no, symptom words, language words, department words**, plus all metadata, no audio | no personal data in these words |
| **B, masked** | for names, phone numbers, addresses: only the error **class and position** (for example "digit 7 heard as 1 at position 4", "name: 2 of 5 characters differ"), never the string | always |
| **C, audio and exact personal words** | the clip and the exact strings | only with a recorded notice and consent, a stated purpose, a retention limit, and a named access list |

Also: retention limits per tier, a delete-by-call path, and a rule that audio never leaves the India-resident deployment.

## 6. Build order

1. **Offline pairs** (no agent change, no consent question): `align` returns operations; `asr_eval --pairs-out`; a confusion report on the gold set. Includes seeding the store with the hand-kept tables so their history is not lost.
2. **Live tier-A events** from the hooks in 4.5, through the call recorder, for catalogue entities and repair firings. Review queue for strong evidence.
3. **Calibration report** (agreement and LID bands against measured error) once a few hundred gold utterances exist; this is the first time the REASONED thresholds can become measured.
4. **Tier-C audio** only after the consent and notice decision (section 7).
5. **Join with refine shadow** and decide whether `ASR_REFINE=on` is ever warranted.

## 7. Questions for the owner

1. Is call audio to be saved at all? If yes, who gives the notice and consent, for what purpose, how long is it kept, and who may listen? (Today the answer in the code is "nobody has agreed to anything".)
2. Who transcribes? The rulebook is written; the cost note in HANDOVER section 9 suggests a stratified gold subset of about 300 hours, not full transcription. How many labelled hours or utterances are planned first?
3. Is a masked record (tier B) acceptable for names and phone numbers, given that those are exactly the words most often misheard?
4. Which bucket matters most to report first: rural Bengali, elderly callers, Hindi, or telephone noise?
