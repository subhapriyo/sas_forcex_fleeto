"""
Bootstrap generator for the ForceX FLEETO DocTypes.

    python -m sas_forcex_fleeto.forcex_fleeto.tools.doctype_specs     # writes doctype/*/*.json
    bench --site forcex.localhost migrate                        # syncs them

Why generate instead of clicking in Desk?
    * Select options come straight from services/constants.py — one source of truth.
    * Reviewable in a single file during code review.
After the first migrate you MAY switch to editing in Desk (developer_mode=1)
— Desk re-exports the JSON. If you do, stop running this generator, or it
will overwrite your Desk edits. Pick one workflow per DocType and note it here.
"""

from __future__ import annotations

import json
import os
import re

from ..services.constants import (
    ROLES,
    AnswerType,
    CallOutcome,
    CallStatus,
    ComponentType,
    InspectionFinding,
    SettlementAction,
)

MODULE = "ForceX FLEETO"
MODIFIED = "2026-11-05 17:00:00.000000"   # bump when you change a spec, or migrate skips it
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def opts(values) -> str:
    return "\n".join(values)


def f(fieldname, fieldtype, label=None, options=None, **kw) -> dict:
    """One field. Extra kwargs pass straight to the JSON (reqd=1, in_list_view=1 ...)."""
    # label=None -> derive from fieldname; label="" -> deliberately blank (column breaks)
    d = {"fieldname": fieldname, "fieldtype": fieldtype,
         "label": fieldname.replace("_", " ").title() if label is None else label}
    if options is not None:
        d["options"] = options
    d.update(kw)
    return d


def sec(label, name=None, **kw):
    return f(name or "sec_" + re.sub(r"\W+", "_", label.lower()).strip("_"), "Section Break", label, **kw)


def col(n):
    return f(f"col_{n}", "Column Break", "")


# Role sets reused below
SVC_DESK = ["FX CRM", "FX Coordinator", "FX Technical Coordinator"]
HEADS = ["FX Warranty Service Head", "FX Operations Head"]


def perms(full=(), write=(), read=(), submittable=False):
    rows = [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1,
             "submit": int(submittable), "cancel": int(submittable), "report": 1, "export": 1}]
    for r in full:
        rows.append({"role": r, "read": 1, "write": 1, "create": 1, "report": 1,
                     "submit": int(submittable), "cancel": int(submittable)})
    for r in write:
        rows.append({"role": r, "read": 1, "write": 1, "create": 1, "report": 1})
    for r in read:
        rows.append({"role": r, "read": 1, "report": 1})
    return rows


# ==========================================================================
# Specs
# ==========================================================================
SPECS: dict[str, dict] = {}

# ---------------------------------------------------------------- settings
SPECS["FX Warranty Policy"] = dict(istable=1, fields=[
    f("component_type", "Select", options=opts(ComponentType.values()), reqd=1, in_list_view=1),
    f("model", "Data", description="Blank = all models", in_list_view=1),
    f("months", "Int", reqd=1, in_list_view=1),
    f("km_limit", "Int", in_list_view=1),
])

SPECS["FX Service Settings"] = dict(issingle=1, fields=[
    sec("Konnect"),
    f("konnect_base_url", "Data", "Konnect API Base URL"),
    f("konnect_api_key", "Password", "Konnect API Key"),
    f("strict_vin", "Check", "Warn on non-VIN chassis numbers", default="1"),
    f("battery_type_map", "Code", options="JSON",
      default='{"LED": "Lead-Acid Battery", "LI": "Lithium-Ion Battery"}'),
    sec("Warranty"),
    f("warranty_start_basis", "Select", options="Invoice Date\nKonnect Invoice Date", default="Invoice Date"),
    f("warranty_policies", "Table", options="FX Warranty Policy"),
    f("replace_threshold", "Currency", "Replacement needs MD approval above"),
    f("dealer_credit_policy", "Select", options="pass_through\nfull_refund", default="pass_through"),
    f("credit_note_item", "Link", options="Item", description="Non-stock service item used on credit notes"),
    sec("Notifications"),
    f("whatsapp_sender", "Data", description="Dotted path of a send(mobile, message) function; blank = log only"),
    f("detractor_alert_role", "Link", options="Role", default="FX Warranty Service Head"),
], permissions=perms(write=HEADS))

# ---------------------------------------------------------------- registry
SPECS["FX Vehicle Component"] = dict(istable=1, fields=[
    f("component_type", "Select", options=opts(ComponentType.values()), reqd=1, in_list_view=1),
    f("serial_no", "Data", reqd=1, in_list_view=1, search_index=1),
    f("warranty_start", "Date", in_list_view=1),
    f("warranty_end", "Date", in_list_view=1),
    f("status", "Select", options="Active\nReplaced\nScrapped", default="Active"),
    f("replaced_by_serial", "Data"),
    f("source_column", "Data", read_only=1),
])

SPECS["FX Vehicle Registry"] = dict(
    autoname="field:chassis_no", title_field="customer_name",
    search_fields="customer_name,mobile,konnect_invoice_no",
    fields=[
        f("chassis_no", "Data", reqd=1, unique=1, in_list_view=1),
        f("model", "Data", in_list_view=1),
        f("product_name", "Data"),
        f("battery_chemistry", "Select", options=opts(["", ComponentType.LEAD_ACID_BATTERY, ComponentType.LITHIUM_BATTERY])),
        col(1),
        f("customer_name", "Data", in_list_view=1),
        f("mobile", "Data", options="Phone", search_index=1),
        f("whatsapp", "Data", options="Phone"),
        f("email", "Data", options="Email"),
        sec("Invoice"),
        f("konnect_invoice_no", "Data", search_index=1),
        f("konnect_invoice_date", "Date"),
        f("invoice_date", "Date", "Retail Invoice Date"),
        f("showroom_invoice_no", "Data"),
        col(2),
        f("dealer", "Link", options="Customer"),
        f("dealer_code", "Data", search_index=1),
        f("grand_total", "Currency"),
        f("sync_key", "Data", unique=1, read_only=1, hidden=1),
        sec("Components"),
        f("components", "Table", options="FX Vehicle Component"),
        f("import_warnings", "Small Text", read_only=1),
    ],
    permissions=perms(write=HEADS, read=SVC_DESK + ["FX Business Partner", "FX Spare Store"]),
)

SPECS["FX Konnect Import Log"] = dict(autoname="hash", fields=[
    f("source", "Select", options="File Upload\nAPI", in_list_view=1),
    f("file", "Attach"),
    f("status", "Select", options="Queued\nRunning\nDone\nFailed", in_list_view=1),
    f("total", "Int"), f("importable", "Int"), f("blocked", "Int", in_list_view=1),
    f("created", "Int"), f("updated", "Int"),
    f("details", "Code", options="JSON", read_only=1),
], permissions=perms(write=HEADS, read=SVC_DESK))

# ---------------------------------------------------------------- ticket
SPECS["FX Triage Check"] = dict(istable=1, fields=[
    f("check_item", "Data", reqd=1, in_list_view=1),
    f("done", "Check", in_list_view=1),
    f("reading", "Data", in_list_view=1),
])

# FX Service Ticket retired 05-Nov-2026: FLEETO tickets are HD Tickets (see integrations/helpdesk.py)

# ---------------------------------------------------------------- field service
SPECS["FX Technician Booking"] = dict(autoname="hash", fields=[
    f("ticket", "Link", options="HD Ticket", in_list_view=1),
    f("technician", "Link", options="Employee", reqd=1, in_list_view=1),
    f("booking_date", "Date", reqd=1, in_list_view=1),
    f("from_time", "Time", reqd=1),
    f("to_time", "Time", reqd=1),
    f("status", "Select", options="Assigned\nIn Progress\nDone\nCancelled\nBlocked", default="Assigned", in_list_view=1),
    col(1),
    f("zone", "Data"), f("skillset", "Data"), f("vehicle_tag", "Data", "Dispatch Vehicle Tag"),
    f("notify", "Check", "Send WhatsApp/SMS to tech & dealer", default="1"),
], permissions=perms(write=["FX Technical Coordinator", "FX Coordinator"] + HEADS, read=["FX CRM"]))

SPECS["FX Job Card Part"] = dict(istable=1, fields=[
    f("item_code", "Link", options="Item", reqd=1, in_list_view=1),
    f("qty", "Float", default="1", in_list_view=1),
    f("serial_no", "Data", in_list_view=1),
])

SPECS["FX Job Card"] = dict(autoname="hash", is_submittable=1, fields=[
    f("booking", "Link", options="FX Technician Booking", reqd=1),
    f("ticket", "Link", options="HD Ticket", fetch_from="booking.ticket", read_only=1, in_list_view=1),
    f("technician", "Link", options="Employee", fetch_from="booking.technician", read_only=1),
    f("arrival_time", "Datetime"), f("arrival_lat", "Float", precision="6"), f("arrival_lng", "Float", precision="6"),
    f("departure_time", "Datetime"),
    col(1),
    f("odometer_km", "Int"), f("odometer_photo", "Attach Image"),
    f("vehicle_status", "Select", options="READY\nFAIL", reqd=1, in_list_view=1),
    sec("Work"),
    f("root_cause", "Small Text"), f("work_done", "Small Text"),
    f("parts", "Table", options="FX Job Card Part"),
    sec("Signatures"),
    f("customer_signature", "Signature", "Dealer / Customer Signature"),
    f("technician_signature", "Signature"),
], permissions=perms(full=["FX Technical Coordinator"] + HEADS, submittable=True))

# ---------------------------------------------------------------- factory
SPECS["FX Material Receipt"] = dict(autoname="hash", fields=[
    f("receipt_date", "Date", reqd=1, default="Today", in_list_view=1),
    f("ticket", "Link", options="HD Ticket", description="May be tagged later (FRD note 2/3)", in_list_view=1),
    f("received_from", "Link", options="Customer"),
    f("component_type", "Select", options=opts(ComponentType.values()), reqd=1),
    f("serial_no", "Data", reqd=1, in_list_view=1),
    f("notes", "Small Text"),
], permissions=perms(write=["FX Spare Store", "FX Coordinator"] + HEADS, read=SVC_DESK))

SPECS["FX Material Inspection"] = dict(
    autoname="naming_series:", is_submittable=1, track_changes=1,
    fields=[
        f("naming_series", "Select", options="MIR-.YYYY.-.####", default="MIR-.YYYY.-.####"),
        f("ticket", "Link", options="HD Ticket", reqd=1, in_list_view=1),
        f("material_receipt", "Link", options="FX Material Receipt"),
        f("component_type", "Select", options=opts(ComponentType.values()), fetch_from="ticket.fx_component_type", reqd=1),
        f("serial_no", "Data", fetch_from="ticket.fx_component_serial"),
        f("original_invoice", "Data", description="Konnect invoice of the vehicle (set automatically)"),
        f("inspector", "Link", options="User", default="__user"),
        col(1),
        f("finding", "Select", options=opts(InspectionFinding.values()), reqd=1, in_list_view=1),
        f("settlement_action", "Select", options=opts([""] + SettlementAction.values()), in_list_view=1,
          description="Blank = system default for this component & finding"),
        f("replacement_serial", "Data", depends_on="eval:doc.settlement_action=='Replace Unit'"),
        f("md_approved", "Check", "Goodwill / MD approval"),
        sec("Values"),
        f("invoiced_value", "Currency"), f("credit_note_amount", "Currency"),
        f("replacement_value", "Currency"),
        col(2),
        f("scrap_tag", "Data", "Hazardous Scrap Tag"), f("recycler_batch", "Data", "Authorised Recycler Batch"),
    ],
    permissions=perms(full=HEADS, write=["FX Spare Store"], submittable=True),
)

SPECS["FX Supplier RMA"] = dict(autoname="naming_series:", track_changes=1, fields=[
    f("naming_series", "Select", options="RMA-SUP-.YYYY.-.###", default="RMA-SUP-.YYYY.-.###"),
    f("ticket", "Link", options="HD Ticket", reqd=1, in_list_view=1),
    f("supplier", "Link", options="Supplier", reqd=1, in_list_view=1),
    f("component_serial", "Data", fetch_from="ticket.fx_component_serial"),
    f("status", "Select", options="Draft\nSent to Supplier\nSupplier Acknowledged\nRepaired Pack Returned\nSupplier Credited\nClosed",
      default="Draft", in_list_view=1),
    f("courier", "Data"), f("awb_no", "Data", "AWB No"),
    col(1),
    f("supplier_assessment", "Select", options="\nRepaired Pack Returned\nPack Irreparable - Supplier Credit Note"),
    f("supplier_cn_ref", "Data", "Supplier Credit Note Ref"),
    f("supplier_credit", "Currency", "Credit Value Received"),
    f("dealer_invoiced_value", "Currency"),
    f("auto_dealer_cn", "Check", "Auto-generate Dealer Credit Note", default="1"),
    f("dealer_credit", "Currency", read_only=1),
    f("margin_absorbed", "Currency", read_only=1),
], permissions=perms(write=HEADS + ["FX Spare Store"], read=SVC_DESK))

# ---------------------------------------------------------------- feedback
SPECS["FX Feedback Question"] = dict(istable=1, fields=[
    f("question", "Data", reqd=1, in_list_view=1),
    f("answer_type", "Select", options=opts(AnswerType.values()), reqd=1, in_list_view=1),
    f("mandatory", "Check", in_list_view=1),
    f("active", "Check", default="1", in_list_view=1),
    f("is_recommend_question", "Check", "Counts for detractor alert"),
])

SPECS["FX Feedback Questionnaire"] = dict(autoname="field:code", fields=[
    f("code", "Data", reqd=1, unique=1, in_list_view=1),
    f("questionnaire_name", "Data", reqd=1),
    f("status", "Select", options="Draft\nActive\nSuperseded", default="Draft", in_list_view=1),
    f("version", "Int", default="1"),
    col(1),
    f("effective_from", "Date", reqd=1, in_list_view=1),
    f("effective_to", "Date", read_only=1),
    f("call_after_days", "Int", default="7", reqd=1),
    f("max_attempts", "Int", default="3", reqd=1),
    sec("WhatsApp"),
    f("whatsapp_template", "Small Text",
      default="Dear {customer_name}, thank you for sharing your feedback with FLEETO Customer Care today on invoice {invoice_no}. We value your opinion. — Team FLEETO"),
    sec("Questions"),
    f("questions", "Table", options="FX Feedback Question"),
], permissions=perms(write=["FX Warranty Service Head", "FX CRM"], read=["FX Coordinator"]))

SPECS["FX Feedback Answer"] = dict(istable=1, fields=[
    f("question_idx", "Int", read_only=1, in_list_view=1),
    f("question", "Data", read_only=1, in_list_view=1),
    f("answer_type", "Data", read_only=1),
    f("mandatory", "Check", read_only=1),
    f("answer", "Data", in_list_view=1),
])

SPECS["FX Feedback Call"] = dict(autoname="hash", track_changes=1, sort_field="invoice_date", sort_order="ASC", fields=[
    f("invoice_no", "Data", reqd=1, unique=1, in_list_view=1),
    f("invoice_date", "Date", reqd=1, in_list_view=1, search_index=1),
    f("vehicle", "Link", options="FX Vehicle Registry"),
    f("customer_name", "Data", fetch_from="vehicle.customer_name", in_list_view=1),
    f("mobile", "Data", fetch_from="vehicle.mobile"),
    f("whatsapp", "Data", fetch_from="vehicle.whatsapp"),
    col(1),
    f("status", "Select", options=opts(CallStatus.values()), default=CallStatus.QUEUED, in_list_view=1, search_index=1),
    f("attempts", "Int", read_only=1),
    f("hold_until", "Datetime"),
    f("claimed_by", "Link", options="User", read_only=1),
    f("questionnaire", "Link", options="FX Feedback Questionnaire", read_only=1),
    sec("Call"),
    f("call_outcome", "Select", options=opts([""] + CallOutcome.values())),
    f("answers", "Table", options="FX Feedback Answer"),
    f("is_detractor", "Check", read_only=1),
    f("whatsapp_sent", "Check", read_only=1),
    f("completed_on", "Datetime", read_only=1),
], permissions=perms(write=["FX CRM"], read=HEADS))


# ==========================================================================
# Writer
# ==========================================================================
def slug(name: str) -> str:
    return name.lower().replace(" ", "_")


def build(name: str, spec: dict) -> dict:
    spec = dict(spec)
    doc = {
        "doctype": "DocType", "name": name, "module": MODULE, "custom": 0,
        "engine": "InnoDB", "modified": MODIFIED, "owner": "Administrator",
        "fields": spec.pop("fields"),
        "permissions": [] if spec.get("istable") else spec.pop("permissions", perms()),
    }
    doc.update(spec)
    for i, fd in enumerate(doc["fields"], start=1):
        fd.setdefault("idx", i)
    return doc


def write_all(base: str = os.path.join(HERE, "doctype")) -> list[str]:
    written = []
    for name, spec in SPECS.items():
        folder = os.path.join(base, slug(name))
        os.makedirs(folder, exist_ok=True)
        open(os.path.join(folder, "__init__.py"), "a").close()
        path = os.path.join(folder, f"{slug(name)}.json")
        with open(path, "w") as fh:
            json.dump(build(name, spec), fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        written.append(path)
    return written


# Fixtures for hooks.py: the 11 FRD roles
ROLE_FIXTURES = [{"doctype": "Role", "role_name": r, "desk_access": 1} for r in ROLES]

if __name__ == "__main__":
    for p in write_all():
        print("wrote", os.path.relpath(p, HERE))
