"""
Demo data for the ForceX FLEETO module: every screen gets realistic records.

    bench --site <site> execute sas_forcex_fleeto.forcex_fleeto.demo.seed
    bench --site <site> execute sas_forcex_fleeto.forcex_fleeto.demo.clear

Safety
    * Runs only when the site has developer_mode = 1, or site config
      "fx_allow_demo_data": 1  (bench --site <site> set-config fx_allow_demo_data 1).
    * Needs a Company (finish the setup wizard first).
    * Idempotent: seed() twice changes nothing the second time.
    * Every demo record is recognisable, so clear() never touches real data:
        vehicles   chassis starts with "MD9DEM"
        tickets    HD Tickets with fx_demo_key set
        employees  "Demo Tech ..."
        supplier   "Demo Cell Energy Ltd"
        dealers    created only if missing; real Konnect dealers are reused and never deleted

What you get (dates are relative to today, so warranty / queue states stay valid)
    8 vehicles (6 lead-acid, 2 lithium; one sold 14 months ago -> battery expired)
    3 technicians, 3 calendar entries (assigned, done, transit block), 1 draft job card
    9 tickets across both lanes:
        service : Open · Tele-Calling Triage -> Technician Assigned · Feedback Pending · Closed
        warranty: Draft (evidence missing) · Open with part override · Under Inspection + draft MIR
                  · Under Inspection + draft Supplier RMA (lithium) · Goodwill Approval Pending
    1 questionnaire (5 questions, as SOW Screen 9) unless an active one already exists
    7 feedback calls: completed promoter, completed detractor, not-reachable retry,
      call-back-later hold, 3 queued
"""

from __future__ import annotations

import base64
import json

import frappe
from frappe.utils import add_days, add_to_date, getdate, now_datetime, nowdate

from sas_forcex_fleeto.forcex_fleeto.api import konnect
from sas_forcex_fleeto.forcex_fleeto.services import konnect_parser
from sas_forcex_fleeto.forcex_fleeto.services.constants import CallOutcome, Status

CHASSIS_PREFIX = "MD9DEM"
TECH_PREFIX = "Demo Tech"
SUPPLIER = "Demo Cell Energy Ltd"
QUESTIONNAIRE = "FB-Q-DEMO-01"

# Real Konnect dealer codes (from the 31-Oct export). Reused if they already exist.
DEALERS = [("DL-00363", "Showroom-Damodar Green Wheel"), ("DL-00381", "Suhana Motors"), ("DL-00377", "ANF Services")]

# ASSUMPTION (decision D7): placeholder warranty months until FLEETO confirms.
POLICIES = [("Lead-Acid Battery", 12), ("Lithium-Ion Battery", 36), ("Lithium Charger", 12), ("Lead Charger", 12),
            ("Motor", 24), ("Controller", 24), ("Chassis", 36), ("IOT Device", 12), ("Other", 12)]


# ==========================================================================
# Entry points
# ==========================================================================
def seed() -> dict:
    _guard()
    frappe.set_user("Administrator")
    out = {}
    out["settings"] = _settings()
    out["dealers"] = _dealers()
    out["vehicles"] = _vehicles()
    files = _evidence_files()
    techs = _technicians()
    out["technicians"] = len(techs)
    tickets = _tickets(files)
    out["tickets"] = {k: frappe.db.get_value("HD Ticket", v, "fx_stage") for k, v in tickets.items()}
    out["calendar"] = _calendar(techs, tickets)
    out["inspection"] = _inspection(tickets)
    out["supplier_rma"] = _supplier_rma(tickets)
    out["feedback_calls"] = _feedback()
    frappe.db.commit()
    print(json.dumps(out, indent=1, default=str))
    return out


def clear() -> dict:
    """Remove ONLY demo records (identified as described in the module docstring)."""
    _guard()
    frappe.set_user("Administrator")
    vehicles = frappe.get_all("FX Vehicle Registry", filters={"name": ["like", f"{CHASSIS_PREFIX}%"]}, pluck="name")
    tickets = frappe.get_all("HD Ticket", filters={"fx_demo_key": ["is", "set"]}, pluck="name")
    techs = frappe.get_all("Employee", filters={"employee_name": ["like", f"{TECH_PREFIX}%"]}, pluck="name")
    counts = {}

    def drop(doctype, names):
        for n in names:
            doc = frappe.get_doc(doctype, n)
            if doc.docstatus == 1:
                doc.cancel()
            frappe.delete_doc(doctype, n, force=True, ignore_permissions=True)
        counts[doctype] = len(names)

    drop("FX Job Card", frappe.get_all("FX Job Card", filters={"ticket": ["in", tickets or [""]]}, pluck="name"))
    drop("FX Technician Booking", frappe.get_all("FX Technician Booking",
                                                 filters={"technician": ["in", techs or [""]]}, pluck="name"))
    drop("FX Material Inspection", frappe.get_all("FX Material Inspection", filters={"ticket": ["in", tickets or [""]]}, pluck="name"))
    drop("FX Supplier RMA", frappe.get_all("FX Supplier RMA", filters={"ticket": ["in", tickets or [""]]}, pluck="name"))
    drop("FX Feedback Call", frappe.get_all("FX Feedback Call", filters={"vehicle": ["in", vehicles or [""]]}, pluck="name"))
    drop("HD Ticket", tickets)
    drop("FX Vehicle Registry", vehicles)
    drop("Employee", techs)
    drop("Supplier", frappe.get_all("Supplier", filters={"name": SUPPLIER}, pluck="name"))
    if not frappe.db.count("FX Feedback Call", {"questionnaire": QUESTIONNAIRE}):
        drop("FX Feedback Questionnaire", frappe.get_all("FX Feedback Questionnaire", filters={"name": QUESTIONNAIRE}, pluck="name"))
    drop("File", frappe.get_all("File", filters={"file_name": ["like", "fx_demo_%"]}, pluck="name"))
    frappe.db.commit()
    print(json.dumps(counts, indent=1))
    return counts


# ==========================================================================
# Steps
# ==========================================================================
def _guard():
    if not (frappe.conf.developer_mode or frappe.conf.get("fx_allow_demo_data")):
        frappe.throw("Demo data is disabled on this site. Enable with: "
                     "bench --site <site> set-config fx_allow_demo_data 1")
    if not frappe.get_all("Company", limit=1):
        frappe.throw("No Company on this site. Complete the setup wizard first.")


def _company() -> str:
    return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company", pluck="name")[0]


def _leaf(doctype: str, prefer: str | None = None) -> str:
    if prefer and frappe.db.exists(doctype, prefer):
        return prefer
    return frappe.get_all(doctype, filters={"is_group": 0}, pluck="name", limit=1)[0]


def _settings() -> int:
    s = frappe.get_single("FX Service Settings")
    have = {(p.component_type, p.model or "") for p in s.warranty_policies}
    for comp, months in POLICIES:
        if (comp, "") not in have:
            s.append("warranty_policies", {"component_type": comp, "months": months})
    s.save()
    return len(s.warranty_policies)


def _dealers() -> list[str]:
    names = []
    for code, name in DEALERS:
        existing = frappe.db.get_value("Customer", {"fx_konnect_party_code": code})
        if not existing:
            c = frappe.get_doc({"doctype": "Customer", "customer_name": name, "customer_type": "Company",
                                "customer_group": _leaf("Customer Group", "Commercial"),
                                "territory": _leaf("Territory", "India"), "fx_konnect_party_code": code})
            if frappe.get_meta("Customer").has_field("gst_category"):
                c.gst_category = "Unregistered"
            existing = c.insert().name
        names.append(existing)
    return names


def _d(days_ago: int) -> str:
    """Konnect sends D/M/YYYY text, so the demo does too (exercises the parser)."""
    d = getdate(add_days(nowdate(), -days_ago))
    return f"{d.day}/{d.month}/{d.year}"


# (n, dealer code, customer, battery type, days since sale, model)
VEHICLES = [
    (1, "DL-00363", "Arindam Ghosh", "LED", 40, "Wolf Warrior"),
    (2, "DL-00363", "Bithika Pal", "LED", 25, "Magnum"),
    (3, "DL-00381", "Chandan Saha", "LI", 60, "Magnum"),
    (4, "DL-00381", "Dolon Sen", "LI", 15, "Aayan"),
    (5, "DL-00363", "Esha Mukherjee", "LED", 425, "Wolf Warrior"),   # 14 months: battery expired
    (6, "DL-00377", "Faisal Ahmed", "LED", 10, "Magnum"),
    (7, "DL-00377", "Gargi Roy", "LED", 9, "Wolf"),
    (8, "DL-00363", "Hiran Das", "LED", 3, "Wolf Warrior"),           # not yet due for a feedback call
]


def _gst(total: float) -> dict:
    """Intra-state 5% GST (2.5% CGST + 2.5% SGST) that adds up exactly, as Konnect sends it.
    The parser checks net + tax == total, so demo figures must be consistent."""
    net = round(total / 1.05, 2)
    cgst = round((total - net) / 2, 2)
    return {"Total Item Value Without GST": net, "CGST": cgst, "SGST": round(total - net - cgst, 2), "IGST": 0,
            "Total Item Value With GST": total}


def chassis(n: int) -> str:
    return f"{CHASSIS_PREFIX}XX26{n:07d}"   # 17 chars, no I/O/Q -> no VIN warnings


def battery(n: int, i: int = 1) -> str:
    return f"DEMO-BAT-{n:02d}{i:02d}"


def _vehicles() -> dict:
    header = list(konnect_parser.REQUIRED_COLUMNS) + ["WhatsApp No", "Product Name", "Total Item Value Without GST",
                                                       "CGST", "SGST", "IGST", "Total Item Value With GST",
                                                       "Motor", "Controller", "Charger", "Battery1", "Battery2"]
    dealer_names = dict(DEALERS)
    rows = []
    for n, code, cust, btype, days, model in VEHICLES:
        r = {
            "Bill From Party Code": code, "Bill From Party Name": dealer_names[code], "Customer Name": cust,
            "Mobile Number": f"98300001{n:02d}", "WhatsApp No": f"98300001{n:02d}",
            "Invoice Date": _d(days), "Konnect Invoice Number": f"DEMO-INV-{n:03d}", "Konnect Invoice Date": _d(days),
            "Model": model, "Product Name": f"{model} {'LI' if btype == 'LI' else 'LED'} 60V", "Battery Type": btype,
            "Chassis": chassis(n), **_gst(54500 if btype == "LED" else 89000),
            "Motor": f"DEMO-MTR-{n:02d}", "Controller": f"DEMO-CNT-{n:02d}", "Charger": f"DEMO-CHG-{n:02d}",
            "Battery1": battery(n, 1), "Battery2": battery(n, 2) if btype == "LED" else "",
        }
        rows.append([r.get(h, "") for h in header])
    result = konnect_parser.parse_rows(header, rows, battery_type_map={"LED": "Lead-Acid Battery", "LI": "Lithium-Ion Battery"})
    created = sum(konnect._upsert(row) for row in result.rows if row.is_importable)
    return {"parsed": len(result.rows), "created": created, "blocked": result.summary()["blocked"]}


def _evidence_files() -> dict:
    """Two tiny private files so evidence links open in Desk."""
    pdf = _tiny_pdf("FLEETO demo invoice - not a real document")
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
    out = {}
    for key, fname, content in (("invoice", "fx_demo_invoice.pdf", pdf), ("photo", "fx_demo_photo.png", png)):
        url = frappe.db.get_value("File", {"file_name": fname}, "file_url")
        if not url:
            url = frappe.get_doc({"doctype": "File", "file_name": fname, "is_private": 1, "content": content}).insert().file_url
        out[key] = url
    return out


def _tiny_pdf(text: str) -> bytes:
    """A valid one-page PDF (correct xref offsets). Frappe scans uploaded PDFs with
    pypdf for embedded JavaScript, so a malformed PDF is rejected on upload."""
    stream = f"BT /F1 14 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def _technicians() -> dict:
    for d in ("Factory Engineer", "Field Technician"):
        if not frappe.db.exists("Designation", d):
            frappe.get_doc({"doctype": "Designation", "designation_name": d}).insert()
    techs = {}
    for first, desig, mobile in (("Amit", "Factory Engineer", "9830000201"), ("Bipin", "Field Technician", "9830000202"),
                                 ("Niladri", "Factory Engineer", "9830000203")):
        full = f"{TECH_PREFIX} {first}"
        name = frappe.db.get_value("Employee", {"employee_name": full})
        if not name:
            name = frappe.get_doc({
                "doctype": "Employee", "first_name": TECH_PREFIX, "last_name": first, "employee_name": full,
                "gender": "Male", "date_of_birth": "1990-01-01", "date_of_joining": "2024-04-01",
                "company": _company(), "status": "Active", "designation": desig, "cell_number": mobile,
            }).insert().name
        techs[first] = name
    return techs


# demo-script keys -> HD Ticket fields (keeps the scenario table below readable)
_FIELD = {"vehicle": "fx_vehicle", "business_partner": "fx_business_partner", "component_serial": "fx_component_serial",
          "component_type": "fx_component_type", "override_reason": "fx_override_reason", "claim_for": "fx_claim_for",
          "goodwill_requested": "fx_goodwill_requested", "customer_invoice": "fx_customer_invoice",
          "component_photo": "fx_component_photo", "call_channel": "fx_call_channel",
          "triage_outcome": "fx_triage_outcome", "triage_checks": "fx_triage_checks"}


def _ticket(key: str, values: dict, moves: list[str] | None = None, receive=False) -> str:
    """Create a FLEETO HD Ticket once (keyed by fx_demo_key) and walk it through the
    REAL stage rules, so every demo state is one the system allows."""
    from sas_forcex_fleeto.forcex_fleeto.integrations import helpdesk

    name = frappe.db.get_value("HD Ticket", {"fx_demo_key": key})
    if name:
        return name
    v = dict(values)
    subject = v.pop("damage_details", "FLEETO ticket")
    code = frappe.db.get_value("Customer", v.get("business_partner"), "fx_konnect_party_code") or "dealer"
    doc = frappe.get_doc({
        "doctype": "HD Ticket", "subject": subject, "description": f"<p>{subject}</p>",
        "raised_by": f"{code.lower()}@dealers.demo.fleeto", "fx_demo_key": key,
        **{_FIELD.get(k, k): val for k, val in v.items()},
    }).insert(ignore_permissions=True)
    for stage in moves or []:
        helpdesk.set_stage(doc.name, stage)
    if receive:
        helpdesk.receive_material(doc.name)
    return doc.name


def _tickets(files: dict) -> dict:
    dealer = {code: frappe.db.get_value("Customer", {"fx_konnect_party_code": code}) for code, _ in DEALERS}
    ev = {"customer_invoice": files["invoice"], "component_photo": files["photo"]}
    svc = {"ticket_type": "Service"}
    S = Status
    t = {}
    # ---------------- service lane
    t["S1"] = _ticket("S1", {**svc, "vehicle": chassis(1), "business_partner": dealer["DL-00363"],
                             "damage_details": "Vehicle not starting after rain"}, [S.OPEN])
    t["S2"] = _ticket("S2", {**svc, "vehicle": chassis(2), "business_partner": dealer["DL-00363"],
                             "damage_details": "Range dropped to 40 km", "call_channel": "Phone Call",
                             "triage_outcome": "Escalate to Field Technician",
                             "triage_checks": [{"check_item": "Battery terminal voltage", "done": 1, "reading": "49.2 V"},
                                               {"check_item": "Controller wiring harness", "done": 1},
                                               {"check_item": "BMS fault log code", "done": 0}]},
                      [S.OPEN, S.INVOICE_VERIFIED, S.TELE_TRIAGE])          # booking moves it to Technician Assigned
    t["S3"] = _ticket("S3", {**svc, "vehicle": chassis(6), "business_partner": dealer["DL-00377"],
                             "damage_details": "Horn not working", "call_channel": "WhatsApp Video Call",
                             "triage_outcome": "Resolved Remotely"},
                      [S.OPEN, S.INVOICE_VERIFIED, S.TELE_TRIAGE, S.FEEDBACK_PENDING])
    t["S4"] = _ticket("S4", {**svc, "vehicle": chassis(7), "business_partner": dealer["DL-00377"],
                             "damage_details": "Brake squeal", "triage_outcome": "Resolved Remotely"},
                      [S.OPEN, S.INVOICE_VERIFIED, S.TELE_TRIAGE, S.FEEDBACK_PENDING, S.CLOSED])
    # ---------------- warranty lane
    w = {"ticket_type": "Warranty", "claim_for": "Customer Claim"}
    t["W1"] = _ticket("W1", {**w, "vehicle": chassis(1), "component_serial": battery(1), "business_partner": dealer["DL-00363"],
                             "damage_details": "Battery swelling, evidence not yet uploaded"})           # stays Draft
    t["W2"] = _ticket("W2", {**w, **ev, "vehicle": chassis(4), "business_partner": dealer["DL-00381"],
                             "component_type": "Motor", "component_serial": "MTR-PHYSICAL-7781",
                             "override_reason": "Motor replaced at dealer before Konnect sync; physical tag differs",
                             "damage_details": "Motor noise at high load"}, [S.OPEN])
    t["W3"] = _ticket("W3", {**w, **ev, "vehicle": chassis(2), "component_serial": battery(2),
                             "business_partner": dealer["DL-00363"], "damage_details": "Battery not holding charge"},
                      [S.OPEN], receive=True)                                  # -> Under Inspection
    t["W4"] = _ticket("W4", {**w, **ev, "vehicle": chassis(3), "component_serial": battery(3),
                             "business_partner": dealer["DL-00381"], "damage_details": "Lithium pack BMS fault E12"},
                      [S.OPEN], receive=True)                                  # -> Under Inspection (lithium)
    t["W5"] = _ticket("W5", {**w, **ev, "vehicle": chassis(5), "component_serial": battery(5),
                             "business_partner": dealer["DL-00363"], "goodwill_requested": 1,
                             "damage_details": "Battery dead, 14 months old (out of warranty)"},
                      [S.OPEN], receive=True)                                  # -> Goodwill Approval Pending
    return t


def _calendar(techs: dict, tickets: dict) -> int:
    today, yesterday = nowdate(), add_days(nowdate(), -1)
    entries = [
        {"technician": techs["Amit"], "ticket": tickets["S2"], "booking_date": today, "from_time": "14:30:00",
         "to_time": "16:30:00", "status": "Assigned", "zone": "Kolkata North / Hooghly", "skillset": "High-Voltage / BMS",
         "vehicle_tag": "WB-02-AL-4102"},
        {"technician": techs["Amit"], "ticket": tickets["S4"], "booking_date": yesterday, "from_time": "09:00:00",
         "to_time": "11:00:00", "status": "Done", "zone": "Kolkata North / Hooghly"},
        {"technician": techs["Bipin"], "booking_date": today, "from_time": "09:00:00", "to_time": "11:00:00",
         "status": "Blocked", "zone": "Barasat"},                                  # on transit
    ]
    made = 0
    for e in entries:
        if frappe.db.exists("FX Technician Booking", {k: e[k] for k in ("technician", "booking_date", "from_time")}):
            continue
        frappe.get_doc({"doctype": "FX Technician Booking", "notify": 0, **e}).insert()
        made += 1
    booking = frappe.db.get_value("FX Technician Booking", {"ticket": tickets["S2"], "status": "Assigned"})
    if booking and not frappe.db.exists("FX Job Card", {"booking": booking}):
        frappe.get_doc({"doctype": "FX Job Card", "booking": booking, "vehicle_status": "READY",
                        "arrival_time": add_to_date(now_datetime(), hours=-1), "arrival_lat": 22.8890, "arrival_lng": 88.3990,
                        "odometer_km": 184, "root_cause": "Loose connector on BMS harness",
                        "work_done": "Re-crimped connector, bench tested"}).insert()   # draft: signatures pending
    return made


def _inspection(tickets: dict) -> str | None:
    """Draft MIR on the lead-acid claim: irreparable -> credit note (submit it to see the router)."""
    t = tickets["W3"]
    name = frappe.db.get_value("FX Material Inspection", {"ticket": t})
    if not name:
        # component_type passed explicitly: it is mandatory and I'm not certain fetch_from
        # fills it before Frappe's mandatory check on insert.
        name = frappe.get_doc({"doctype": "FX Material Inspection", "ticket": t, "finding": "Irreparable",
                               "component_type": frappe.db.get_value("HD Ticket", t, "fx_component_type"),
                               "invoiced_value": 6500, "scrap_tag": "PCB-HAZ-DEMO-0001",
                               "recycler_batch": "Demo Smelters"}).insert().name
    return name


def _supplier_rma(tickets: dict) -> str | None:
    if not frappe.db.exists("Supplier", SUPPLIER):
        frappe.get_doc({"doctype": "Supplier", "supplier_name": SUPPLIER,
                        "supplier_group": _leaf("Supplier Group")}).insert()
    t = tickets["W4"]
    name = frappe.db.get_value("FX Supplier RMA", {"ticket": t})
    if not name:
        name = frappe.get_doc({"doctype": "FX Supplier RMA", "ticket": t, "supplier": SUPPLIER, "status": "Draft",
                               "courier": "SafeXpress", "awb_no": "DEMO-AWB-0001",
                               "dealer_invoiced_value": 24000}).insert().name
    return name


def _questionnaire() -> str:
    active = frappe.get_all("FX Feedback Questionnaire", filters={"status": "Active"}, pluck="name", limit=1)
    if active:
        return active[0]   # never replace a real questionnaire
    frappe.get_doc({
        "doctype": "FX Feedback Questionnaire", "code": QUESTIONNAIRE, "questionnaire_name": "Post-Sale Customer Feedback (demo)",
        "status": "Active", "version": 1, "effective_from": add_days(nowdate(), -500), "call_after_days": 7, "max_attempts": 3,
        "questions": [
            {"question": "How would you rate our service?", "answer_type": "Star rating (1-5)", "mandatory": 1, "active": 1},
            {"question": "How would you rate our product?", "answer_type": "Star rating (1-5)", "mandatory": 1, "active": 1},
            {"question": "Would you recommend our product to others?", "answer_type": "Yes / No / Maybe", "mandatory": 1,
             "active": 1, "is_recommend_question": 1},
            {"question": "Was the vehicle handover and feature explanation satisfactory?", "answer_type": "Yes / No", "active": 1},
            {"question": "Any suggestions for us?", "answer_type": "Free text", "active": 1},
        ],
    }).insert()
    return QUESTIONNAIRE


def _feedback() -> dict:
    q = _questionnaire()
    # vehicle n -> outcome script ("" = leave queued)
    plan = {5: ("Connected", {"1": 5, "2": 4, "3": "Yes", "4": "Yes", "5": "Longer charging cable please"}),
            3: ("Connected", {"1": 2, "2": 3, "3": "No", "4": "Yes", "5": "Service centre too far"}),   # detractor
            1: ("Not Reachable", None), 2: ("Call Back Later", None), 4: ("", None), 6: ("", None), 7: ("", None)}
    out = {}
    for n, (outcome, answers) in plan.items():
        inv = f"DEMO-INV-{n:03d}"
        name = frappe.db.get_value("FX Feedback Call", {"invoice_no": inv})
        if not name:
            call = frappe.get_doc({"doctype": "FX Feedback Call", "invoice_no": inv, "vehicle": chassis(n),
                                   "invoice_date": frappe.db.get_value("FX Vehicle Registry", chassis(n), "invoice_date"),
                                   "questionnaire": q, "status": "Queued"})
            call.load_questions()
            call.insert()
            if outcome:
                cb = str(add_to_date(now_datetime(), days=1)) if outcome == CallOutcome.CALL_BACK_LATER else None
                call.submit_outcome(outcome, json.dumps(answers) if answers else None, cb)
            name = call.name
        out[inv] = frappe.db.get_value("FX Feedback Call", name, "status")
    return out
