"""
FX Feedback Questionnaire — Screen 9 (master with effective dating).

Rules (all from SOW Screen 9):
  * A version that already has answered calls is read-only -> "Copy as New Version".
  * Activating version N closes version N-1 the day before N starts.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from sas_forcex_fleeto.forcex_fleeto.services import feedback
from sas_forcex_fleeto.forcex_fleeto.utils import business_rules

LOCKED_FIELDS = ("questions", "call_after_days", "max_attempts", "effective_from")


class FXFeedbackQuestionnaire(Document):
    def validate(self):
        if not [q for q in self.questions if q.active]:
            frappe.throw(_("Add at least one active question"))
        self._block_edits_when_answered()

    def on_update(self):
        before = self.get_doc_before_save()
        if self.status == "Active" and (not before or before.status != "Active"):
            self._close_previous_version()

    @frappe.whitelist()
    def copy_as_new_version(self, effective_from: str) -> str:
        new = frappe.copy_doc(self)
        new.update({"code": f"{self.code.rsplit('-', 1)[0]}-{(self.version or 1) + 1:02d}",
                    "version": (self.version or 1) + 1, "status": "Draft",
                    "effective_from": effective_from, "effective_to": None})
        new.insert()
        return new.name

    # ----------------------------------------------------------------------
    def _response_count(self) -> int:
        return frappe.db.count("FX Feedback Call", {"questionnaire": self.name, "status": "Completed"})

    def _block_edits_when_answered(self):
        if self.is_new() or not self._response_count():
            return
        before = self.get_doc_before_save()
        changed = [f for f in LOCKED_FIELDS if str(before.get(f)) != str(self.get(f))] if before else []
        if changed:
            frappe.throw(_("This version already has responses; use 'Copy as New Version'. Changed: {0}")
                         .format(", ".join(changed)), title=_("Read-only version"))

    def _close_previous_version(self):
        others = frappe.get_all("FX Feedback Questionnaire",
                                filters={"status": "Active", "name": ["!=", self.name]},
                                fields=["name", "effective_from"])
        for o in others:
            prev = feedback.QuestionnaireVersion(o.name, getdate(o.effective_from))
            with business_rules("Cannot activate"):
                feedback.close_previous(prev, getdate(self.effective_from))
            frappe.db.set_value("FX Feedback Questionnaire", o.name,
                                {"effective_to": prev.effective_to, "status": prev.status})


def get_effective(on_date) -> "FXFeedbackQuestionnaire":
    rows = frappe.get_all("FX Feedback Questionnaire", filters={"status": ["in", ["Active", "Superseded"]]},
                          fields=["name", "effective_from", "effective_to", "status"])
    versions = [feedback.QuestionnaireVersion(r.name, getdate(r.effective_from),
                                              getdate(r.effective_to) if r.effective_to else None, r.status)
                for r in rows]
    with business_rules("No questionnaire"):
        v = feedback.effective_version(versions, getdate(on_date))
    return frappe.get_cached_doc("FX Feedback Questionnaire", v.code)
