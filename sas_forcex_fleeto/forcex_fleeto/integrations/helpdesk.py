"""
ForceX Helpdesk (HD Ticket) is the FLEETO service & warranty ticket.

Design (decided by the Helpdesk trial, 05-Nov-2026, helpdesk v1.30.2):
  * Helpdesk changes HD Ticket.status by itself (customer reply re-opens,
    auto-close closes). That status is the CONVERSATION. Our PROCESS stage
    lives in its own field, `fx_stage`, guarded by services/ticket_flow.
    We never touch `status`, Helpdesk never touches `fx_stage`.
  * Only tickets whose HD Ticket Type is "Service" or "Warranty" are FLEETO
    tickets; every other Helpdesk ticket behaves exactly as stock Helpdesk.
  * Agents move stages from the Helpdesk header ("→ <next stage>" buttons,
    an HD Form Script) or the Desk form (public/js/hd_ticket_fx.js).
    Both call set_stage(), which runs the same validate hook.

Wiring (hooks.py):
    doc_events["HD Ticket"]["validate"] -> validate_hd_ticket
    after_migrate                        -> setup  (fields, types, template, form script)
    doctype_js["HD Ticket"]              -> public/js/hd_ticket_fx.js
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from sas_forcex_fleeto.forcex_fleeto.services import ticket_flow, warranty_rules
from sas_forcex_fleeto.forcex_fleeto.services.constants import (
    ClaimFor,
    Status,
    TicketType,
)
from sas_forcex_fleeto.forcex_fleeto.utils import business_rules, warranty_policy

LANES = {TicketType.SERVICE.value, TicketType.WARRANTY.value}
# ASSUMPTION (decision D3): the MD's goodwill approval is recorded by the Operations Head.
GOODWILL_APPROVER_ROLE = "FX Operations Head"

# HD Ticket attach field -> evidence key understood by services/warranty_rules
EVIDENCE = {"fx_customer_invoice": "customer_invoice", "fx_distributor_invoice": "distributor_invoice",
            "fx_tally_invoice": "tally_invoice", "fx_component_photo": "component_photo",
            "fx_odometer_photo": "odometer_photo"}


def _f(fieldname, fieldtype, label, after, **kw):
    return {"fieldname": fieldname, "fieldtype": fieldtype, "label": label, "insert_after": after, **kw}


CUSTOM_FIELDS = {"HD Ticket": [
    _f("fx_section", "Section Break", "FLEETO Service & Warranty", "description"),
    _f("fx_stage", "Select", "Stage", "fx_section", options="\n".join(Status.values()), default=Status.DRAFT,
       in_standard_filter=1, in_list_view=1, read_only=1),
    _f("fx_claim_for", "Select", "Claim For", "fx_stage", options="\n".join([""] + ClaimFor.values())),
    _f("fx_business_partner", "Link", "Dealer / Distributor", "fx_claim_for", options="Customer"),
    _f("fx_vehicle", "Link", "Vehicle", "fx_business_partner", options="FX Vehicle Registry"),
    _f("fx_odometer_km", "Int", "Odometer (km)", "fx_vehicle"),
    _f("fx_col1", "Column Break", "", "fx_odometer_km"),
    _f("fx_component_type", "Data", "Component", "fx_col1", read_only=1),
    _f("fx_component_serial", "Data", "Component Serial", "fx_component_type", search_index=1),
    _f("fx_warranty_status", "Data", "Warranty Status", "fx_component_serial", read_only=1),
    _f("fx_warranty_expires_on", "Date", "Warranty Expires On", "fx_warranty_status", read_only=1),
    _f("fx_override_reason", "Small Text", "Part override reason", "fx_warranty_expires_on"),
    _f("fx_goodwill_requested", "Check", "Goodwill requested", "fx_override_reason"),
    _f("fx_goodwill_approved_by", "Link", "Goodwill approved by", "fx_goodwill_requested", options="User", read_only=1),
    # evidence
    _f("fx_ev_section", "Section Break", "Evidence", "fx_goodwill_approved_by", collapsible=1),
    _f("fx_customer_invoice", "Attach", "Customer Invoice", "fx_ev_section"),
    _f("fx_distributor_invoice", "Attach", "Distributor Invoice", "fx_customer_invoice"),
    _f("fx_tally_invoice", "Attach", "Tally Invoice", "fx_distributor_invoice"),
    _f("fx_ev_col", "Column Break", "", "fx_tally_invoice"),
    _f("fx_component_photo", "Attach Image", "Component Photo", "fx_ev_col"),
    _f("fx_odometer_photo", "Attach Image", "Odometer Photo", "fx_component_photo"),
    # tele-triage (Screen 2)
    _f("fx_triage_section", "Section Break", "Tele-Calling Triage", "fx_odometer_photo", collapsible=1,
       depends_on="eval:doc.ticket_type=='Service'"),
    _f("fx_call_channel", "Select", "Call Channel", "fx_triage_section",
       options="\nPhone Call\nWhatsApp Video Call\nDealer Conference"),
    _f("fx_triage_outcome", "Select", "Triage Outcome", "fx_call_channel",
       options="\nResolved Remotely\nEscalate to Field Technician\nSend Component to Factory"),
    _f("fx_triage_checks", "Table", "Checklist", "fx_triage_outcome", options="FX Triage Check"),
    # settlement links (filled by MIR / RMA / accounting)
    _f("fx_settle_section", "Section Break", "Settlement", "fx_triage_checks", collapsible=1),
    _f("fx_inspection", "Link", "Material Inspection", "fx_settle_section", options="FX Material Inspection", read_only=1),
    _f("fx_supplier_rma", "Link", "Supplier RMA", "fx_inspection", options="FX Supplier RMA", read_only=1),
    _f("fx_settle_col", "Column Break", "", "fx_supplier_rma"),
    _f("fx_credit_note", "Link", "Credit Note", "fx_settle_col", options="Sales Invoice", read_only=1),
    _f("fx_delivery_note", "Link", "FOC / Warranty Challan", "fx_credit_note", options="Delivery Note", read_only=1),
    _f("fx_advance_warranty_claim_invoice", "Data", "Advance Warranty Claim Invoice", "fx_delivery_note"),
    _f("fx_demo_key", "Data", "Demo key", "fx_advance_warranty_claim_invoice", hidden=1, read_only=1),
]}

# Shown in the Helpdesk agent / portal ticket panel (HD Ticket Template)
TEMPLATE_FIELDS = ["fx_stage", "fx_claim_for", "fx_business_partner", "fx_vehicle", "fx_component_serial",
                   "fx_warranty_status", "fx_override_reason", "fx_goodwill_requested", "fx_odometer_km",
                   "fx_customer_invoice", "fx_component_photo"]
HIDE_FROM_CUSTOMER = {"fx_stage", "fx_warranty_status", "fx_override_reason"}

FORM_SCRIPT_NAME = "FLEETO stage actions"
# Helpdesk form-script contract (helpdesk/desk/src/composables/formCustomisation.ts):
#   the script defines setupForm(ctx) -> {actions}; ctx = {doc, call, toast, ...}; it may be async.
#   Actions WITHOUT `group` render as plain header buttons wired with @click="action.onClick()".
#   We use those on purpose: on Helpdesk 1.30 (frappe-ui 1.0.0-beta.24) a grouped dropdown
#   item ("Stage: X" menu) rendered fine but its onClick never fired when tested on the
#   bench, so no request reached the server. Re-test before switching back to a dropdown.
FORM_SCRIPT = """
async function setupForm({ doc, call, toast }) {
  if (!doc || !["Service", "Warranty"].includes(doc.ticket_type)) return { actions: [] };
  const api = "sas_forcex_fleeto.forcex_fleeto.integrations.helpdesk.";
  const next = await call(api + "next_stages", { ticket: doc.name });
  const run = (method, args, ok) =>
    call(api + method, args)
      .then(() => { toast.success(ok); window.location.reload(); })
      .catch((e) => toast.error((e && (e.messages && e.messages[0])) || (e && e.message) || "Not allowed"));
  const actions = (next || []).map((stage) => ({
    label: "→ " + stage,
    onClick: () => stage === "Material Received"
      ? run("receive_material", { ticket: doc.name }, "Material received")
      : run("set_stage", { ticket: doc.name, stage }, "Moved to " + stage),
  }));
  return { actions };
}
"""


def lane(doc) -> str | None:
    return doc.ticket_type if doc.get("ticket_type") in LANES else None


# ==========================================================================
# doc_events
# ==========================================================================
def validate_hd_ticket(doc, method=None):
    """One hook = every rule. Runs for Helpdesk UI, Desk, API, and our own code."""
    t = lane(doc)
    if not t:
        return  # not a FLEETO ticket: stock Helpdesk
    doc.fx_stage = doc.get("fx_stage") or Status.DRAFT
    before = doc.get_doc_before_save()
    old = before.get("fx_stage") if before else None

    _match_and_warranty(doc)
    with business_rules("Invalid stage change"):
        ticket_flow.assert_transition(t, old, doc.fx_stage)
    _evidence_gate(doc, t, old)


def _registry_row(doc):
    if not (doc.get("fx_vehicle") and doc.get("fx_component_serial")):
        return None
    return frappe.db.get_value(
        "FX Vehicle Component",
        {"parent": doc.fx_vehicle, "parenttype": "FX Vehicle Registry", "serial_no": doc.fx_component_serial},
        ["component_type", "warranty_start", "warranty_end"], as_dict=True)


def _match_and_warranty(doc):
    """Part discrepancy & override (SOW §1) + warranty status, evaluated on the ticket's creation day."""
    if not doc.get("fx_component_serial"):
        return
    row = _registry_row(doc)
    if not row and doc.fx_stage != Status.DRAFT and not doc.get("fx_override_reason"):
        frappe.throw(_("Serial {0} is not on this vehicle in Konnect. Enter a Part Override Reason.")
                     .format(doc.fx_component_serial))
    if row:
        doc.fx_component_type = row.component_type
    if not doc.get("fx_component_type"):
        return
    on = getdate(doc.creation) if doc.get("creation") else getdate(nowdate())
    model = frappe.db.get_value("FX Vehicle Registry", doc.fx_vehicle, "model") if doc.get("fx_vehicle") else None
    policy = warranty_policy(doc.fx_component_type, model)
    km = {"km_limit": policy.km_limit if policy else None, "odometer_km": doc.get("fx_odometer_km")}
    if row and row.warranty_end:
        result = warranty_rules.status_for_end(getdate(row.warranty_end), on, **km)
    else:  # override case: fall back to the vehicle's sale date
        sale = frappe.db.get_value("FX Vehicle Registry", doc.fx_vehicle, "invoice_date") if doc.get("fx_vehicle") else None
        result = warranty_rules.evaluate(getdate(sale) if sale else None, policy.months if policy else 0, on=on, **km)
    doc.fx_warranty_status = result.status
    doc.fx_warranty_expires_on = result.expires_on


def _evidence_gate(doc, t, old):
    """Screen 1: a warranty claim cannot leave Draft without the invoice + a photo."""
    if t != TicketType.WARRANTY or old not in (None, Status.DRAFT) or doc.fx_stage == Status.DRAFT:
        return
    missing = warranty_rules.missing_evidence(doc.get("fx_claim_for") or ClaimFor.CUSTOMER,
                                              {key: doc.get(f) for f, key in EVIDENCE.items()})
    if missing:
        labels = {key: doc.meta.get_label(f) for f, key in EVIDENCE.items()}
        readable = [" or ".join(labels.get(x, x) for x in m.split(" or ")) for m in missing]
        frappe.throw(_("Attach before submitting: {0}").format(", ".join(readable)), title=_("Evidence missing"))


# ==========================================================================
# Agent actions (Helpdesk header dropdown + Desk buttons)
# ==========================================================================
@frappe.whitelist()
def next_stages(ticket: str) -> list[str]:
    doc = frappe.get_doc("HD Ticket", ticket)
    doc.check_permission("read")
    t = lane(doc)
    if not t:
        return []
    stages = ticket_flow.next_statuses(t, doc.get("fx_stage") or Status.DRAFT)
    # "Material Received" is reached via receive_material(), which also takes the warranty decision
    return stages


@frappe.whitelist()
def set_stage(ticket: str, stage: str) -> str:
    doc = frappe.get_doc("HD Ticket", ticket)
    doc.check_permission("write")
    if doc.get("fx_stage") == Status.GOODWILL_PENDING and stage == Status.UNDER_INSPECTION:
        if GOODWILL_APPROVER_ROLE not in frappe.get_roles():
            frappe.throw(_("Only {0} can approve goodwill warranty").format(GOODWILL_APPROVER_ROLE))
        doc.fx_goodwill_approved_by = frappe.session.user
    doc.fx_stage = stage
    doc.save()
    return doc.fx_stage


@frappe.whitelist()
def receive_material(ticket: str) -> str:
    """Warranty lane, first diamond: material in hand -> inspection, goodwill or rejection."""
    doc = frappe.get_doc("HD Ticket", ticket)
    doc.check_permission("write")
    doc.fx_stage = Status.MATERIAL_RECEIVED
    doc.save()
    doc.fx_stage = ticket_flow.after_material_receipt(
        is_in_warranty=doc.get("fx_warranty_status") == "Active", wants_goodwill=bool(doc.get("fx_goodwill_requested")))
    doc.save()
    return doc.fx_stage


# ==========================================================================
# install / migrate
# ==========================================================================
def setup():
    """Idempotent: custom fields, ticket types, template fields, form script. Runs on every migrate."""
    if "helpdesk" not in frappe.get_installed_apps():
        return
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields(CUSTOM_FIELDS, update=True)
    for t in sorted(LANES):
        if not frappe.db.exists("HD Ticket Type", t):
            frappe.get_doc({"doctype": "HD Ticket Type", "name": t, "description": f"FLEETO {t.lower()} ticket"}).insert(
                ignore_permissions=True)
    try:  # Helpdesk reads ticket.template or helpdesk.consts.DEFAULT_TICKET_TEMPLATE
        from helpdesk.consts import DEFAULT_TICKET_TEMPLATE as tpl_name
    except ImportError:
        tpl_name = "Default"
    if frappe.db.exists("HD Ticket Template", tpl_name):
        tpl = frappe.get_doc("HD Ticket Template", tpl_name)
        have = {f.fieldname for f in tpl.fields}
        for fn in TEMPLATE_FIELDS:
            if fn not in have:
                tpl.append("fields", {"fieldname": fn, "required": 0, "hide_from_customer": int(fn in HIDE_FROM_CUSTOMER)})
        tpl.save(ignore_permissions=True)
    fs = frappe.db.exists("HD Form Script", FORM_SCRIPT_NAME)
    values = {"dt": "HD Ticket", "apply_to": "Form", "enabled": 1, "script": FORM_SCRIPT.strip()}
    if fs:
        frappe.get_doc("HD Form Script", fs).update(values).save(ignore_permissions=True)
    else:
        frappe.get_doc({"doctype": "HD Form Script", "name": FORM_SCRIPT_NAME, "__newname": FORM_SCRIPT_NAME, **values}).insert(
            ignore_permissions=True)
