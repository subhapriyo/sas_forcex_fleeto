"""Scheduled jobs (wired in hooks.py -> scheduler_events)."""

import frappe
from frappe.utils import add_days, getdate, nowdate

from sas_forcex_fleeto.forcex_fleeto.doctype.fx_feedback_questionnaire.fx_feedback_questionnaire import (
    get_effective,
)
from sas_forcex_fleeto.forcex_fleeto.services import feedback


def build_feedback_queue():
    """Daily: every synced invoice enters the queue once invoice_date + N days is reached.

    N ("Call After") comes from the questionnaire effective today.
    Safe to run many times — the unique invoice_no on FX Feedback Call
    plus the NOT EXISTS filter make it idempotent.
    """
    today = getdate(nowdate())
    q = get_effective(today)
    cutoff = add_days(today, -q.call_after_days)

    rows = frappe.db.sql(
        """
        select r.name, r.konnect_invoice_no, r.invoice_date
        from `tabFX Vehicle Registry` r
        where r.invoice_date <= %(cutoff)s and ifnull(r.konnect_invoice_no, '') != ''
          and not exists (select 1 from `tabFX Feedback Call` c where c.invoice_no = r.konnect_invoice_no)
        """,
        {"cutoff": cutoff}, as_dict=True,
    )
    by_inv = {r.konnect_invoice_no: r for r in rows}
    due = feedback.invoices_to_enqueue(
        [feedback.InvoiceForCall(r.konnect_invoice_no, getdate(r.invoice_date)) for r in rows],
        q.call_after_days, today, already_queued=set(),
    )
    for inv in due:
        frappe.get_doc({
            "doctype": "FX Feedback Call", "invoice_no": inv.invoice_no, "invoice_date": inv.invoice_date,
            "vehicle": by_inv[inv.invoice_no].name, "status": "Queued",
        }).insert(ignore_permissions=True)
    # No frappe.db.commit() here: the scheduler's execute_job() commits on
    # success and rolls back on error (frappe/utils/background_jobs.py).
    # An explicit commit would also break test isolation.
    return len(due)
