"""Screen 7 — Customer Feedback Desk: FIFO queue endpoints."""

import frappe
from frappe.utils import add_to_date, getdate, now_datetime, nowdate

from sas_forcex_fleeto.forcex_fleeto.doctype.fx_feedback_questionnaire.fx_feedback_questionnaire import (
    get_effective,
)
from sas_forcex_fleeto.forcex_fleeto.services import feedback
from sas_forcex_fleeto.forcex_fleeto.services.constants import CallStatus

CLAIM_TIMEOUT_MIN = 30   # a claimed call is released if untouched this long
CANDIDATES = 50          # rows locked per request; plenty for FIFO


@frappe.whitelist()
def open_next_call() -> str | None:
    """Give the current executive the oldest callable invoice (strict FIFO).

    Two executives pressing the button together must not get the same call,
    so candidate rows are locked (FOR UPDATE) before one is claimed.
    """
    frappe.has_permission("FX Feedback Call", "write", throw=True)
    user, now = frappe.session.user, now_datetime()
    stale = add_to_date(now, minutes=-CLAIM_TIMEOUT_MIN)

    rows = frappe.db.sql(
        """
        select name, invoice_no, invoice_date, status, attempts, hold_until, claimed_by, modified
        from `tabFX Feedback Call`
        where status in %(open)s
        order by invoice_date asc, invoice_no asc
        limit %(n)s
        for update
        """,
        {"open": (CallStatus.QUEUED, CallStatus.ON_HOLD), "n": CANDIDATES}, as_dict=True,
    )
    # Someone else is on it (and not stale) -> skip
    free = [r for r in rows if not r.claimed_by or r.claimed_by == user or r.modified < stale]
    calls = {r.invoice_no: r for r in free}
    pick = feedback.next_call(
        [feedback.QueuedCall(r.invoice_no, getdate(r.invoice_date), r.status, r.attempts, r.hold_until) for r in free],
        now,
    )
    if not pick:
        return None

    doc = frappe.get_doc("FX Feedback Call", calls[pick.invoice_no].name)
    doc.claimed_by = user
    if not doc.questionnaire:
        doc.questionnaire = get_effective(nowdate()).name   # version effective on the CALL date
    doc.load_questions()
    doc.save()
    return doc.name


@frappe.whitelist()
def queue_summary() -> dict:
    """Header tiles on Screen 7."""
    today = nowdate()
    count = lambda **f: frappe.db.count("FX Feedback Call", f)  # noqa: E731
    return {
        "pending": count(status=CallStatus.QUEUED),
        "on_hold": count(status=CallStatus.ON_HOLD),
        "completed_today": count(status=CallStatus.COMPLETED, completed_on=[">=", today]),
        "detractors_today": count(is_detractor=1, completed_on=[">=", today]),
    }
