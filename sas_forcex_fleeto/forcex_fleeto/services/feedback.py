"""
Customer Feedback Desk logic (Screens 7, 8 and 9).

    Questionnaire versions   effective dating, read-only once answered
    Queue                    who is due a call, strict FIFO by invoice date
    Attempts                 retry / hold / give-up rules
    Answers                  mandatory gate, value checks, detractor alert
    WhatsApp text            safe placeholder rendering
"""

from __future__ import annotations

import datetime as dt
import string
from dataclasses import dataclass

from .constants import AnswerType
from .constants import CallOutcome as O
from .constants import CallStatus as CS


class FeedbackError(ValueError):
    pass


# ==========================================================================
# Questionnaire versions (Screen 9)
# ==========================================================================
@dataclass
class QuestionnaireVersion:
    code: str
    effective_from: dt.date
    effective_to: dt.date | None = None
    status: str = "Active"          # Draft | Active | Superseded
    response_count: int = 0


def effective_version(versions: list[QuestionnaireVersion], on: dt.date) -> QuestionnaireVersion:
    """Version in force on `on`. Drafts never count. Latest start wins on overlap."""
    live = [
        v for v in versions
        if v.status in ("Active", "Superseded")
        and v.effective_from <= on
        and (v.effective_to is None or on <= v.effective_to)
    ]
    if not live:
        raise FeedbackError(f"No feedback questionnaire is effective on {on:%d-%b-%Y}")
    return max(live, key=lambda v: v.effective_from)


def close_previous(prev: QuestionnaireVersion, new_from: dt.date) -> None:
    """Activating a new version ends the old one the day before."""
    if new_from <= prev.effective_from:
        raise FeedbackError("New version must start after the current version's Effective From date")
    prev.effective_to = new_from - dt.timedelta(days=1)
    prev.status = "Superseded"


def is_read_only(v: QuestionnaireVersion) -> bool:
    """Answered versions are frozen so old responses keep their meaning."""
    return v.response_count > 0


# ==========================================================================
# Queue (Screen 7)
# ==========================================================================
@dataclass
class InvoiceForCall:
    invoice_no: str
    invoice_date: dt.date


@dataclass
class QueuedCall:
    invoice_no: str
    invoice_date: dt.date
    status: str = CS.QUEUED
    attempts: int = 0
    hold_until: dt.datetime | None = None


OPEN_STATUSES = {CS.QUEUED, CS.ON_HOLD}


def call_due_date(invoice_date: dt.date, call_after_days: int) -> dt.date:
    return invoice_date + dt.timedelta(days=call_after_days)


def invoices_to_enqueue(invoices: list[InvoiceForCall], call_after_days: int, today: dt.date,
                        already_queued: set[str]) -> list[InvoiceForCall]:
    """Invoices whose call is due and that don't yet have a call row."""
    due = [
        i for i in invoices
        if i.invoice_no not in already_queued and call_due_date(i.invoice_date, call_after_days) <= today
    ]
    return sorted(due, key=lambda i: (i.invoice_date, i.invoice_no))


def next_call(calls: list[QueuedCall], now: dt.datetime) -> QueuedCall | None:
    """Strict FIFO: oldest invoice first. Held calls are skipped until their
    hold time passes, then they jump back to their natural (old) position."""
    callable_ = [
        c for c in calls
        if c.status == CS.QUEUED or (c.status == CS.ON_HOLD and c.hold_until and c.hold_until <= now)
    ]
    return min(callable_, key=lambda c: (c.invoice_date, c.invoice_no), default=None)


def register_attempt(call: QueuedCall, outcome: str, max_attempts: int,
                     callback_at: dt.datetime | None = None) -> QueuedCall:
    """Apply one call outcome. CONNECTED is finished by `complete` in the
    Frappe layer after answers are validated, so it only counts an attempt."""
    if call.status not in OPEN_STATUSES:
        raise FeedbackError(f"Call for {call.invoice_no} is already '{call.status}'")

    call.attempts += 1
    if outcome == O.NOT_REACHABLE:
        call.status = CS.UNREACHABLE if call.attempts >= max_attempts else CS.QUEUED
        call.hold_until = None
    elif outcome == O.CALL_BACK_LATER:
        if not callback_at:
            raise FeedbackError("Call Back Later needs a callback date & time")
        call.status, call.hold_until = CS.ON_HOLD, callback_at
    elif outcome == O.DECLINED:
        call.status = CS.DECLINED
    elif outcome == O.CONNECTED:
        call.status = CS.COMPLETED
    else:
        raise FeedbackError(f"Unknown call outcome '{outcome}'")
    return call


# ==========================================================================
# Answers (Screen 8)
# ==========================================================================
@dataclass
class Question:
    idx: int
    text: str
    answer_type: str
    mandatory: bool = False
    is_recommend_question: bool = False


_CHOICES = {AnswerType.YES_NO_MAYBE: {"Yes", "No", "Maybe"}, AnswerType.YES_NO: {"Yes", "No"}}
DETRACTOR_MAX_STAR = 2


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def missing_mandatory(questions: list[Question], answers: dict) -> list[int]:
    return [q.idx for q in questions if q.mandatory and _blank(answers.get(q.idx))]


def validate_answers(questions: list[Question], answers: dict) -> None:
    missing = missing_mandatory(questions, answers)
    if missing:
        raise FeedbackError(f"Please answer mandatory question(s): {missing}")
    for q in questions:
        a = answers.get(q.idx)
        if _blank(a):
            continue
        if q.answer_type == AnswerType.STAR and not (isinstance(a, int) and 1 <= a <= 5):
            raise FeedbackError(f"Q{q.idx}: star rating must be 1-5, got {a!r}")
        if q.answer_type in _CHOICES and a not in _CHOICES[q.answer_type]:
            raise FeedbackError(f"Q{q.idx}: answer must be one of {sorted(_CHOICES[q.answer_type])}")


def is_detractor(questions: list[Question], answers: dict) -> bool:
    """Rating <= 2 on any star question, or 'No' to the recommend question."""
    for q in questions:
        a = answers.get(q.idx)
        if q.answer_type == AnswerType.STAR and isinstance(a, int) and a <= DETRACTOR_MAX_STAR:
            return True
        if q.is_recommend_question and a == "No":
            return True
    return False


# ==========================================================================
# WhatsApp text
# ==========================================================================
def render_message(template: str, context: dict) -> str:
    """str.format with a clear error for unknown placeholders.

    We deliberately avoid Jinja here: templates are edited by business
    users in the master, and {customer_name} style is harder to break.
    """
    fields = {f for _, f, _, _ in string.Formatter().parse(template) if f}
    unknown = fields - context.keys()
    if unknown:
        raise FeedbackError(f"Template uses unknown placeholder(s): {', '.join(sorted(unknown))}")
    return template.format(**context)
