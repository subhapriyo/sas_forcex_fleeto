"""
FX Material Inspection (MIR) — Screen 5: the RMA router.

The inspector records a finding; submit() executes the settlement:

    Same Return / Repair & Same Return  -> ticket Ready to Dispatch
    Send to Supplier                    -> draft FX Supplier RMA, ticket At Supplier
    Issue Credit Note                   -> draft credit note,      ticket Credit Note Pending
    Replace Unit                        -> registry updated (non-reset), ticket Ready to Dispatch
    Reject Claim                        -> ticket Claim Rejected

Financial documents are created as DRAFTS. Accounts reviews and submits
them — the service team never posts to the ledger directly.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

from sas_forcex_fleeto.forcex_fleeto.accounting import make_dealer_credit_note
from sas_forcex_fleeto.forcex_fleeto.services import settlement, warranty_rules
from sas_forcex_fleeto.forcex_fleeto.services.constants import (
    ComponentType,
    InspectionFinding,
    Status,
)
from sas_forcex_fleeto.forcex_fleeto.services.constants import (
    SettlementAction as A,
)
from sas_forcex_fleeto.forcex_fleeto.utils import business_rules, move_ticket, settings


class FXMaterialInspection(Document):
    def validate(self):
        # Konnect invoice of the vehicle on the ticket (HD Ticket -> FX Vehicle Registry)
        if not self.original_invoice and self.ticket:
            vehicle = frappe.db.get_value("HD Ticket", self.ticket, "fx_vehicle")
            self.original_invoice = frappe.db.get_value("FX Vehicle Registry", vehicle, "konnect_invoice_no") if vehicle else None
        if not self.settlement_action:
            self.settlement_action = warranty_rules.default_action(self.component_type, self.finding)

        with business_rules("Settlement not allowed"):
            warranty_rules.validate_settlement(
                self.component_type, self.finding, self.settlement_action,
                value=self.replacement_value or 0,
                replace_threshold=settings().replace_threshold or None,
                md_approved=bool(self.md_approved),
            )
            if self.settlement_action == A.CREDIT_NOTE:
                self.credit_note_amount = settlement.credit_note_amount(
                    self.invoiced_value, self.credit_note_amount or None)

        # Pollution Control Board: irreparable lead-acid must carry a scrap manifest.
        if (self.component_type == ComponentType.LEAD_ACID_BATTERY
                and self.finding == InspectionFinding.IRREPARABLE and not self.scrap_tag):
            frappe.throw(_("Hazardous Scrap Tag is mandatory for irreparable lead-acid batteries"))

        if self.settlement_action == A.REPLACE and not self.replacement_serial:
            frappe.throw(_("Enter the Replacement Serial No"))

    def on_submit(self):
        action = self.settlement_action
        ticket = self.ticket

        if action in (A.SAME_RETURN, A.REPAIR_RETURN):
            move_ticket(ticket, Status.READY_TO_DISPATCH, fx_inspection=self.name)

        elif action == A.SUPPLIER_RMA:
            rma = frappe.get_doc({"doctype": "FX Supplier RMA", "ticket": ticket, "status": "Draft",
                                  "supplier": self._component_supplier(),
                                  "dealer_invoiced_value": self.invoiced_value}).insert(ignore_mandatory=True)
            # Ticket stays "Under Inspection" until the RMA is actually sent
            # (FX Supplier RMA -> "Sent to Supplier" moves it to At Supplier).
            move_ticket(ticket, Status.UNDER_INSPECTION, fx_inspection=self.name, fx_supplier_rma=rma.name)

        elif action == A.CREDIT_NOTE:
            cn = make_dealer_credit_note(ticket, self.credit_note_amount, remarks=f"MIR {self.name}: {self.finding}")
            move_ticket(ticket, Status.CREDIT_NOTE_PENDING, fx_inspection=self.name, fx_credit_note=cn)

        elif action == A.REPLACE:
            self._register_replacement()
            move_ticket(ticket, Status.READY_TO_DISPATCH, fx_inspection=self.name)

        elif action == A.REJECT:
            move_ticket(ticket, Status.REJECTED, fx_inspection=self.name)

    # ----------------------------------------------------------------------
    def _component_supplier(self):
        """Supplier is picked on the RMA by the warranty team (no item master link yet)."""
        return None

    def _register_replacement(self):
        """Non-reset rule: the new serial inherits the OLD serial's end date."""
        vehicle = frappe.db.get_value("HD Ticket", self.ticket, "fx_vehicle")
        reg = frappe.get_doc("FX Vehicle Registry", vehicle)
        old = next((c for c in reg.components if c.serial_no == self.serial_no), None)
        if not old or not old.warranty_end:
            frappe.throw(_("Original serial {0} not found on vehicle {1}").format(self.serial_no, vehicle))

        with business_rules("Replacement not allowed"):
            end = warranty_rules.continued_warranty_end(getdate(old.warranty_end), getdate(nowdate()))
        old.status, old.replaced_by_serial = "Replaced", self.replacement_serial
        reg.append("components", {
            "component_type": old.component_type, "serial_no": self.replacement_serial,
            "warranty_start": old.warranty_start, "warranty_end": end, "source_column": f"Replacement ({self.name})",
        })
        reg.flags.ignore_permissions = True
        reg.save()
