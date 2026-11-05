"""
FX Feedback Call — Screen 8 (one row per invoice in the FIFO queue).

The executive never edits status directly; they pick an outcome and press
submit_outcome(). That single method applies every rule from services/feedback.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from sas_forcex_fleeto.forcex_fleeto.adapters import whatsapp
from sas_forcex_fleeto.forcex_fleeto.services import feedback
from sas_forcex_fleeto.forcex_fleeto.services.constants import CallOutcome, CallStatus
from sas_forcex_fleeto.forcex_fleeto.utils import (
    business_rules,
    notify,
    settings,
    users_with_role,
)


class FXFeedbackCall(Document):
    def _questions(self) -> list[feedback.Question]:
        q = frappe.get_cached_doc("FX Feedback Questionnaire", self.questionnaire)
        return [feedback.Question(r.idx, r.question, r.answer_type, bool(r.mandatory), bool(r.is_recommend_question))
                for r in q.questions if r.active]

    def load_questions(self):
        """Copy the effective version's questions into the answers table."""
        if self.answers:
            return
        for q in self._questions():
            self.append("answers", {"question_idx": q.idx, "question": q.text,
                                    "answer_type": q.answer_type, "mandatory": int(q.mandatory)})

    @frappe.whitelist()
    def submit_outcome(self, outcome: str, answers: str | dict | None = None, callback_at: str | None = None):
        self.check_permission("write")
        q_doc = frappe.get_cached_doc("FX Feedback Questionnaire", self.questionnaire)
        call = feedback.QueuedCall(self.invoice_no, self.invoice_date, self.status, self.attempts or 0,
                                   get_datetime(self.hold_until) if self.hold_until else None)

        with business_rules("Cannot save call"):
            if outcome == CallOutcome.CONNECTED:
                parsed = _parse_answers(answers)
                feedback.validate_answers(self._questions(), parsed)       # mandatory gate
                for row in self.answers:
                    row.answer = str(parsed.get(row.question_idx, "") or "")
                self.is_detractor = int(feedback.is_detractor(self._questions(), parsed))
                self.completed_on = now_datetime()
            feedback.register_attempt(call, outcome, q_doc.max_attempts,
                                      get_datetime(callback_at) if callback_at else None)

        self.update({"status": call.status, "attempts": call.attempts, "hold_until": call.hold_until,
                     "call_outcome": outcome, "claimed_by": None})
        self.save()

        if call.status == CallStatus.COMPLETED:
            self._after_completed(q_doc)
        return self.status

    def _after_completed(self, q_doc):
        with business_rules("WhatsApp template error"):
            msg = feedback.render_message(q_doc.whatsapp_template, {
                "customer_name": self.customer_name, "invoice_no": self.invoice_no})
        # whatsapp_sent is set by the background job only when the provider accepts the
        # message, so the flag never claims a message that is merely queued.
        whatsapp.enqueue_send(self.whatsapp or self.mobile, msg, self.doctype, self.name)

        if self.is_detractor:
            role = settings().detractor_alert_role or "FX Warranty Service Head"
            notify(users_with_role(role), _("Detractor feedback on {0}").format(self.invoice_no), self.doctype, self.name)


def _parse_answers(answers) -> dict:
    """Client sends {"1": 4, "3": "Yes"}; star ratings must become ints."""
    raw = json.loads(answers) if isinstance(answers, str) else (answers or {})
    out = {}
    for k, v in raw.items():
        out[int(k)] = int(v) if isinstance(v, str) and v.isdigit() else v
    return out
