"""
Downstream accounting (ForceX FLEETO -> ForceX ERP).

⚠ Open decision (see docs §11): the FRD deck marks some steps "Process in
Tally". If FLEETO books credit notes in Tally, replace these two functions
with a Tally push and keep the same signatures — callers won't change.

Both documents are created as DRAFT for Accounts to review and submit.
"""

import frappe
from frappe import _

from sas_forcex_fleeto.forcex_fleeto.utils import settings


def make_dealer_credit_note(ticket: str, amount: float, remarks: str = "") -> str:
    """Sales Invoice with is_return=1 against the dealer.

    The original sale was invoiced in Konnect, so there is usually no ERPNext
    Sales Invoice to set as `return_against`; the Konnect invoice number is
    kept in `remarks` and the custom link field instead. (As far as I know,
    ERPNext v16 accepts a credit note without return_against — verify on your
    site with a test company before go-live.)
    """
    t = frappe.db.get_value("FX Service Ticket", ticket, ["business_partner", "invoice_no"], as_dict=True)
    item = settings().credit_note_item
    if not (t and t.business_partner and item):
        frappe.throw(_("Set Claim From on the ticket and Credit Note Item in FX Service Settings"))
    _check_gst_ready(item)

    si = frappe.new_doc("Sales Invoice")
    si.customer = t.business_partner
    si.is_return = 1
    si.update_stock = 0
    si.fx_service_ticket = ticket
    si.remarks = f"Warranty credit for {ticket} / Konnect invoice {t.invoice_no}. {remarks}".strip()
    si.append("items", {"item_code": item, "qty": -1, "rate": amount})
    # set_missing_values pulls party details; with India Compliance installed this
    # also sets place of supply and the matching GST tax template.
    si.set_missing_values()
    if si.taxes_and_charges and not si.get("taxes"):
        si.set_taxes()  # ⚠ verify on bench in Phase 3: template -> tax rows
    si.insert(ignore_permissions=True)
    return si.name


def _check_gst_ready(item: str) -> None:
    """With India Compliance, a GST invoice needs HSN/SAC on the item.
    Fail early with a clear message instead of a deep validation error."""
    if frappe.get_meta("Item").has_field("gst_hsn_code") and not frappe.db.get_value("Item", item, "gst_hsn_code"):
        frappe.throw(_("Credit Note Item {0} has no HSN/SAC code. Set it on the Item first.").format(item))


def make_foc_challan(ticket: str, item_code: str, serial_no: str | None = None) -> str:
    """Zero-value Delivery Note used as the warranty / FOC challan."""
    customer = frappe.db.get_value("FX Service Ticket", ticket, "business_partner")
    dn = frappe.new_doc("Delivery Note")
    dn.customer = customer
    dn.fx_service_ticket = ticket
    dn.append("items", {"item_code": item_code, "qty": 1, "rate": 0, "serial_no": serial_no})
    dn.set_missing_values()
    dn.insert(ignore_permissions=True)
    return dn.name
