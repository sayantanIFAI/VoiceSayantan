"""Turns a call summary into the few labels the dashboard counts.

Everything here is a rule on the events the agent already records; nothing is guessed from words. What the events cannot say is said in `notes`
instead of being invented:

  * a "did you mean" or "which one, A or B" question is not recorded, so clarifications are the re-asks ("I did not hear you") only;
  * a booking OFFERED by the agent is not recorded, so "booking after an enquiry" is the nearest honest count (an enquiry came first, then a booking);
  * the caller saying "that is wrong" is not detected; "went wrong" is the moments the caller visibly disagreed (a correction at the read-back,
    a complaint, a request for a person, the language put right) plus the system admitting a failure.
"""

from __future__ import annotations

import dataclasses

from dashboard.journal import CallSummary

BOOKING_INTENTS = frozenset({"book_appointment", "book_test", "add_test_booking"})
ENQUIRY_INTENTS = frozenset({"test_rate", "doctor_availability", "test_prep", "clinic_faq", "department_query"})
IGNORED_INTENTS = frozenset({"smalltalk", "unclear", "repeat_last"})
CONFIRM_ACTIONS = frozenset({"booking_confirmed", "tests_booked"})
CHANGE_ACTIONS = frozenset({"appointment_rescheduled", "appointment_cancelled", "test_added"})
QUIET_OUTCOMES = frozenset({"abusive_caller", "off_topic", "unrelated_caller"})
DROP_OUTCOMES = {
    "silence_timeout": "silence",
    "abandoned": "hung_up_before_first_turn",
    "dropped": "line_or_process_lost",
}
UNHAPPY_BANDS = frozenset({"unhappy", "very_unhappy"})

CALLER_ASKED = frozenset({"caller_requested", "history_requested_staff", "complaint", "lost_and_found"})
SYSTEM_FAILURE = frozenset({"audio_overrun"})

CATEGORIES = ("answered", "booked", "changed", "ended", "transferred", "dropped", "quiet", "live")


def transfer_group(reason: str) -> str:
    """Who caused a hand-off: the caller asked, a rule or safety policy required it, or the system could not cope."""
    if reason in CALLER_ASKED:
        return "caller_asked"
    if reason in SYSTEM_FAILURE or reason.startswith("unintelligible"):
        return "system"
    return "policy"


@dataclasses.dataclass
class Labels:
    category: str = "ended"
    transfer_reason: str = ""
    transfer_group: str = ""
    drop_cause: str = ""
    reasks: int = 0
    reask_reasons: dict = dataclasses.field(default_factory=dict)
    booking_intent: bool = False
    booking_origin: str = ""  # "requested" (the first real intent was a booking) or "after_enquiry"
    booking_confirmed: bool = False
    booking_changed: bool = False
    wrong_signals: list = dataclasses.field(default_factory=list)
    unhappy: bool = False
    tags: list = dataclasses.field(default_factory=list)


def classify(s: CallSummary) -> Labels:
    lab = Labels()
    sig = s.signals or {}
    real = [i for i in s.intents if i not in IGNORED_INTENTS]
    lab.booking_intent = any(i in BOOKING_INTENTS for i in real)
    if lab.booking_intent:
        first_booking = next(n for n, i in enumerate(real) if i in BOOKING_INTENTS)
        lab.booking_origin = "after_enquiry" if any(i in ENQUIRY_INTENTS for i in real[:first_booking]) else "requested"
    lab.booking_confirmed = any(a in CONFIRM_ACTIONS for a in s.actions)
    lab.booking_changed = any(a in CHANGE_ACTIONS for a in s.actions)
    for r in s.reasks:
        lab.reask_reasons[r["reason"]] = lab.reask_reasons.get(r["reason"], 0) + 1
    lab.reasks = len(s.reasks)

    if not s.finished:
        lab.category = "live"
    elif s.escalations or s.outcome in ("handed_off", "emergency", "audio_overrun"):
        lab.category = "transferred"
        lab.transfer_reason = s.escalations[-1] if s.escalations else s.outcome
        lab.transfer_group = transfer_group(lab.transfer_reason)
    elif s.outcome in DROP_OUTCOMES or sig.get("left_mid_task"):
        lab.category = "dropped"
        if s.outcome in DROP_OUTCOMES:
            lab.drop_cause = DROP_OUTCOMES[s.outcome]
        if lab.booking_intent and not lab.booking_confirmed:
            lab.drop_cause = "left_during_booking"
        elif not lab.drop_cause:
            lab.drop_cause = "left_after_reask" if s.last_kind == "reask" else "left_other"
        if lab.drop_cause == "silence" and s.last_kind == "reask":
            lab.drop_cause = "left_after_reask"  # silent after being asked to repeat says more than silent
    elif s.outcome in QUIET_OUTCOMES:
        lab.category = "quiet"
    elif lab.booking_confirmed:
        lab.category = "booked"
    elif lab.booking_changed:
        lab.category = "changed"
    elif sig.get("answers_given") or any(i in ENQUIRY_INTENTS for i in real):
        lab.category = "answered"

    if sig.get("corrections"):
        lab.wrong_signals.append("correction_at_readback")
    if sig.get("asked_for_person") or any(e == "caller_requested" for e in s.escalations):
        lab.wrong_signals.append("asked_for_a_person")
    if "complaint" in s.escalations:
        lab.wrong_signals.append("complaint")
    if sig.get("language_flips"):
        lab.wrong_signals.append("language_put_right")
    if s.failures or sig.get("system_failures"):
        lab.wrong_signals.append("system_error_heard")
    lab.unhappy = s.band in UNHAPPY_BANDS

    tags = [lab.category]
    if lab.reasks:
        tags.append("clarified")
    if lab.wrong_signals:
        tags.append("said_wrong")
    if lab.unhappy:
        tags.append("unhappy")
    if lab.booking_intent:
        tags.append("booking")
    if lab.category in ("dropped", "transferred") or lab.wrong_signals or lab.unhappy:
        tags.append("attention")
    lab.tags = tags
    return lab
