"""
FX Supplier RMA — Screen 6 (lithium lane).

    Draft -> Sent to Supplier -> Supplier Acknowledged
          -> Repaired Pack Returned   => ticket Received from Supplier
          -> Supplier Credited        => dealer credit note (paired), ticket Credit Note Pending
"""

from frappe.model.document import Document

from sas_forcex_fleeto.forcex_fleeto.accounting import make_dealer_credit_note
from sas_forcex_fleeto.forcex_fleeto.services import settlement
from sas_forcex_fleeto.forcex_fleeto.services.constants import Status
from sas_forcex_fleeto.forcex_fleeto.utils import business_rules, move_ticket, settings


class FXSupplierRMA(Document):
    def validate(self):
        if self.status == "Supplier Credited":
            with business_rules("Credit pairing failed"):
                pair = settlement.pair_supplier_credit(
                    self.supplier_credit, self.dealer_invoiced_value,
                    policy=settings().dealer_credit_policy or "pass_through",
                    supplier_cn_ref=self.supplier_cn_ref,
                )
            self.dealer_credit, self.margin_absorbed = pair.dealer_credit, pair.margin_absorbed

    def on_update(self):
        before = self.get_doc_before_save()
        if not before or before.status == self.status:
            return  # only react to status *changes*

        if self.status == "Sent to Supplier":
            move_ticket(self.ticket, Status.AT_SUPPLIER, fx_supplier_rma=self.name)
        elif self.status == "Repaired Pack Returned":
            move_ticket(self.ticket, Status.RECEIVED_FROM_SUPPLIER)
        elif self.status == "Supplier Credited":
            values = {}
            if self.auto_dealer_cn:
                values["fx_credit_note"] = make_dealer_credit_note(
                    self.ticket, self.dealer_credit, remarks=f"Paired with supplier CN {self.supplier_cn_ref}")
            move_ticket(self.ticket, Status.CREDIT_NOTE_PENDING, **values)
