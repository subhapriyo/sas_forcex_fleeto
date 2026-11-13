"""Screen 7 — Customer Feedback Desk: FIFO queue endpoints."""

import frappe
from frappe.utils import add_to_date, getdate, now_datetime, nowdate

from sas_forcex_fleeto.forcex_fleeto.doctype.fx_feedback_questionnaire.fx_feedback_questionnaire import (
    get_effective,
)
from sas_forcex_fleeto.forcex_fleeto.services import feedback
from sas_forcex_fleeto.forcex_fleeto.services.constants import CallStatus

CLAIM_TIMEOUT_MIN = 30   # a claimed call is released if untouched this long
CANDIDATES = 50          # rows locked per request; all are callable, so plenty for FIFO


@frappe.whitelist()
def open_next_call() -> str | None:
    """Give the current executive the oldest callable invoice (strict FIFO).

    Two executives pressing the button together must not get the same call,
    so candidate rows are locked (FOR UPDATE) before one is claimed.
    """
    frappe.has_permission("FX Feedback Call", "write", throw=True)
    user, now = frappe.session.user, now_datetime()
    stale = add_to_date(now, minutes=-CLAIM_TIMEOUT_MIN)

    # Only rows that can be called RIGHT NOW are fetched: queued, or on hold with the
    # call-back time reached, and not held by a colleague (claims go stale after
    # CLAIM_TIMEOUT_MIN). Filtering here, not in Python, means a long run of held
    # calls can never fill the candidate window and hide a due one.
    rows = frappe.db.sql(
        """
        select name, invoice_no, invoice_date, status, attempts, hold_until, claimed_by, modified
        from `tabFX Feedback Call`
        where (status = %(queued)s or (status = %(on_hold)s and hold_until <= %(now)s))
          and (ifnull(claimed_by, '') in ('', %(user)s) or modified < %(stale)s)
        order by invoice_date asc, invoice_no asc
        limit %(n)s
        for update
        """,
        {"queued": CallStatus.QUEUED, "on_hold": CallStatus.ON_HOLD, "now": now, "user": user,
         "stale": stale, "n": CANDIDATES}, as_dict=True,
    )
    # The FIFO choice itself stays in services/feedback.next_call (unit-tested).
    calls = {r.invoice_no: r for r in rows}
    pick = feedback.next_call(
        [feedback.QueuedCall(r.invoice_no, getdate(r.invoice_date), r.status, r.attempts, r.hold_until) for r in rows],
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


@frappe.whitelist()
def get_call(name: str) -> dict:
    """Everything the Feedback Desk shows for one call (Screen 8)."""
    doc = frappe.get_doc("FX Feedback Call", name)
    doc.check_permission("read")
    q = frappe.get_cached_doc("FX Feedback Questionnaire", doc.questionnaire) if doc.questionnaire else None
    v = frappe.db.get_value("FX Vehicle Registry", doc.vehicle, ["model", "product_name", "dealer", "chassis_no"],
                            as_dict=True) if doc.vehicle else None
    return {
        "name": doc.name, "invoice_no": doc.invoice_no, "invoice_date": str(doc.invoice_date),
        "customer_name": doc.customer_name, "mobile": doc.mobile, "whatsapp": doc.whatsapp,
        "status": doc.status, "attempts": doc.attempts or 0, "max_attempts": q.max_attempts if q else None,
        "hold_until": str(doc.hold_until) if doc.hold_until else None,
        "questionnaire": doc.questionnaire, "questionnaire_name": q.questionnaire_name if q else None,
        "vehicle": v or {},
        "answers": [{"idx": a.question_idx, "question": a.question, "answer_type": a.answer_type,
                     "mandatory": a.mandatory} for a in doc.answers],
    }


@frappe.whitelist()
def submit_call(name: str, outcome: str, answers: str | None = None, callback_at: str | None = None) -> dict:
    """Record the outcome from the Feedback Desk; every rule runs in submit_outcome()."""
    doc = frappe.get_doc("FX Feedback Call", name)
    if doc.claimed_by and doc.claimed_by != frappe.session.user:
        frappe.throw(frappe._("{0} has this call open. Press 'Next call' to get another one.").format(doc.claimed_by))
    status = doc.submit_outcome(outcome, answers, callback_at)
    return {"status": status, "is_detractor": doc.is_detractor}


@frappe.whitelist()
def release_call(name: str) -> None:
    """'Skip / release': hand the call back to the queue without an attempt."""
    doc = frappe.get_doc("FX Feedback Call", name)
    if doc.claimed_by == frappe.session.user:
        doc.check_permission("write")
        doc.db_set("claimed_by", None)
