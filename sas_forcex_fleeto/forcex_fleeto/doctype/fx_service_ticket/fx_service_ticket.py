"""
FX Service Ticket — Screens 1 & 2.

Life of a save():
    validate()
      ├─ _match_component()   is the dealer's serial on this vehicle in Konnect?
      ├─ _compute_warranty()  Active / Expired from the registry + policy
      ├─ _guard_status()      only moves allowed by ticket_flow.TRANSITIONS
      └─ _evidence_gate()     attachments required before Draft -> Open

Status is read-only on the form; users change it with the buttons rendered
from `next_statuses` (see fx_service_ticket.js), which call set_status().
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

from sas_forcex_fleeto.forcex_fleeto.services import ticket_flow, warranty_rules
from sas_forcex_fleeto.forcex_fleeto.services.constants import (
    ClaimFor,
    Status,
    TicketType,
)
from sas_forcex_fleeto.forcex_fleeto.utils import business_rules, warranty_policy

# Who may approve goodwill for out-of-warranty claims. ASSUMPTION: the MD's
# approval is recorded by the Operations Head — confirm with FLEETO.
GOODWILL_APPROVER_ROLE = "FX Operations Head"

EVIDENCE_FIELDS = ("customer_invoice", "distributor_invoice", "tally_invoice", "component_photo", "odometer_photo")


class FXServiceTicket(Document):
    # ------------------------------------------------------------------ hooks
    def onload(self):
        # Drives the action buttons on the form.
        self.set_onload("next_statuses", ticket_flow.next_statuses(self.ticket_type, self.status))

    def validate(self):
        self._fetch_distributor()
        self._match_component()
        self._compute_warranty()
        self._guard_status()
        self._evidence_gate()

    # ------------------------------------------------------------ API (form)
    @frappe.whitelist()
    def set_status(self, new_status: str):
        """Called by the status buttons. Permission = write access on the ticket."""
        self.check_permission("write")
        if self.status == Status.GOODWILL_PENDING and new_status == Status.UNDER_INSPECTION:
            if GOODWILL_APPROVER_ROLE not in frappe.get_roles():
                frappe.throw(_("Only {0} can approve goodwill warranty").format(GOODWILL_APPROVER_ROLE))
            self.goodwill_approved_by = frappe.session.user
        self.status = new_status
        self.save()
        return self.status

    @frappe.whitelist()
    def receive_material(self):
        """Warranty lane, first diamond: material in hand -> inspect, goodwill or reject."""
        self.check_permission("write")
        next_status = ticket_flow.after_material_receipt(
            is_in_warranty=self.warranty_status == "Active",
            wants_goodwill=bool(self.goodwill_requested),
        )
        # Two moves in one click: Open -> Material Received -> next
        self.status = Status.MATERIAL_RECEIVED
        self.save()
        self.status = next_status
        self.save()
        return self.status

    # -------------------------------------------------------------- helpers
    def _fetch_distributor(self):
        """Deck slide 5: 'Auto fetch Distributor Name' from the chosen dealer."""
        if self.business_partner and not self.distributor:
            self.distributor = frappe.db.get_value("Customer", self.business_partner, "fx_distributor")

    def _registry_row(self):
        if not (self.vehicle and self.component_serial):
            return None
        return frappe.db.get_value(
            "FX Vehicle Component",
            {"parent": self.vehicle, "parenttype": "FX Vehicle Registry", "serial_no": self.component_serial},
            ["component_type", "warranty_start", "warranty_end", "status"],
            as_dict=True,
        )

    def _match_component(self):
        """'Part Discrepancy & Override' (SOW §1): mismatch is allowed only with a reason."""
        row = self._registry_row()
        self.system_match = int(bool(row))
        if row and not self.component_type:
            self.component_type = row.component_type
        past_draft = self.status != Status.DRAFT
        if self.component_serial and not row and past_draft and not self.override_reason:
            frappe.throw(_("Serial {0} is not on this vehicle in Konnect. Enter a Part Override Reason.")
                         .format(self.component_serial))

    def _compute_warranty(self):
        if not self.component_type:
            return
        row = self._registry_row()
        model = frappe.db.get_value("FX Vehicle Registry", self.vehicle, "model") if self.vehicle else None
        policy = warranty_policy(self.component_type, model)
        # Evaluate on the day the ticket was raised, not today — a ticket
        # opened inside warranty must not "expire" while it is being worked on.
        on = getdate(self.creation) if self.creation else getdate(nowdate())

        km = {"km_limit": policy.km_limit if policy else None, "odometer_km": self.odometer_km}

        if row and row.warranty_end:
            # End date stored at import / after replacement -> respects non-reset rule.
            result = warranty_rules.status_for_end(getdate(row.warranty_end), on, **km)
        else:
            # Unknown part (override case): fall back to the vehicle's sale date.
            start = (row and row.warranty_start) or self.sale_date
            result = warranty_rules.evaluate(
                getdate(start) if start else None, policy.months if policy else 0, on=on, **km)

        self.warranty_status = result.status
        self.warranty_expires_on = result.expires_on

    def _guard_status(self):
        before = self.get_doc_before_save()
        old = before.status if before else None
        with business_rules("Invalid status change"):
            ticket_flow.assert_transition(self.ticket_type, old, self.status)

    def _evidence_gate(self):
        """Screen 1: submission locked until invoice + photo evidence attached."""
        before = self.get_doc_before_save()
        leaving_draft = (before is None or before.status == Status.DRAFT) and self.status != Status.DRAFT
        if not leaving_draft or self.ticket_type != TicketType.WARRANTY:
            return
        missing = warranty_rules.missing_evidence(
            self.claim_for or ClaimFor.CUSTOMER, {f: self.get(f) for f in EVIDENCE_FIELDS})
        if missing:
            frappe.throw(_("Attach before submitting: {0}").format(", ".join(missing)), title=_("Evidence missing"))
