"""
Konnect -> ForceX upstream sync (SOW Phase 1).

Two entry points, one pipeline:

    upload_invoice_report(file_url)   Desk user uploads the Excel export
    push_invoices(rows)               Konnect calls our REST API with JSON rows
                    │
                    ▼
    FX Konnect Import Log (Queued) ── frappe.enqueue ──► run_import()
                                                          │ parse_rows()   (pure, tested)
                                                          │ _upsert()      per importable row
                                                          ▼
                                                     log: Done + details JSON

Idempotent: re-sending the same export updates rows, never duplicates
(sync_key = Konnect invoice no | chassis).
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import getdate

from sas_forcex_fleeto.forcex_fleeto.services import konnect_parser, warranty_rules
from sas_forcex_fleeto.forcex_fleeto.utils import (
    battery_type_map,
    settings,
    warranty_policy,
)

IMPORT_ROLES = {"FX Warranty Service Head", "FX Operations Head", "System Manager"}
COMMIT_EVERY = 200


def _require_import_role():
    if not IMPORT_ROLES & set(frappe.get_roles()):
        frappe.throw(_("Not permitted to import Konnect data"), frappe.PermissionError)


@frappe.whitelist()
def upload_invoice_report(file_url: str) -> str:
    _require_import_role()
    log = frappe.get_doc({"doctype": "FX Konnect Import Log", "source": "File Upload",
                          "file": file_url, "status": "Queued"}).insert()
    frappe.enqueue(run_import, queue="long", timeout=1800, log_name=log.name, enqueue_after_commit=True)
    return log.name


@frappe.whitelist(methods=["POST"])
def push_invoices(rows: str | list) -> str:
    """REST: POST /api/method/sas_forcex_fleeto.forcex_fleeto.api.konnect.push_invoices
    body {"rows": [{"Konnect Invoice Number": ..., "Chassis": ..., ...}]}
    Auth with the API key/secret of an integration user that has an import role."""
    _require_import_role()
    rows = json.loads(rows) if isinstance(rows, str) else rows
    log = frappe.get_doc({"doctype": "FX Konnect Import Log", "source": "API", "status": "Queued",
                          "details": json.dumps({"payload": rows})}).insert()
    frappe.enqueue(run_import, queue="long", timeout=1800, log_name=log.name, enqueue_after_commit=True)
    return log.name


# --------------------------------------------------------------------------
# Background job
# --------------------------------------------------------------------------
def run_import(log_name: str) -> None:
    log = frappe.get_doc("FX Konnect Import Log", log_name)
    log.db_set("status", "Running", commit=True)
    try:
        header, rows = _load_rows(log)
        result = konnect_parser.parse_rows(header, rows, battery_type_map=battery_type_map(),
                                           strict_vin=bool(settings().strict_vin))
        created = updated = 0
        for i, row in enumerate(r for r in result.rows if r.is_importable):
            created_now = _upsert(row)
            created += created_now
            updated += not created_now
            if (i + 1) % COMMIT_EVERY == 0:
                frappe.db.commit()  # keep long imports from holding one giant transaction

        s = result.summary()
        log.update({
            "status": "Done", "total": s["total"], "importable": s["importable"], "blocked": s["blocked"],
            "created": created, "updated": updated,
            "details": json.dumps([
                {"row": r.row_no, "invoice": r.konnect_invoice_no, "errors": r.errors, "warnings": r.warnings}
                for r in result.rows if r.errors or r.warnings
            ], indent=1),
        })
        log.save(ignore_permissions=True)
    except Exception:
        frappe.db.rollback()
        log.reload()
        log.db_set({"status": "Failed", "details": frappe.get_traceback()}, commit=True)
        raise


def _load_rows(log) -> tuple[list, list]:
    if log.source == "API":
        payload = json.loads(log.details or "{}").get("payload") or []
        header = list(payload[0].keys()) if payload else list(konnect_parser.REQUIRED_COLUMNS)
        return header, [[r.get(h) for h in header] for r in payload]
    path = frappe.get_doc("File", {"file_url": log.file}).get_full_path()
    return konnect_parser.read_xlsx(path)


def _upsert(row: konnect_parser.ParsedRow) -> bool:
    """Create or update one FX Vehicle Registry. Returns True if created."""
    name = frappe.db.get_value("FX Vehicle Registry", {"sync_key": row.sync_key}) or \
        frappe.db.exists("FX Vehicle Registry", row.chassis_no)
    doc = frappe.get_doc("FX Vehicle Registry", name) if name else frappe.new_doc("FX Vehicle Registry")

    doc.update({
        "chassis_no": row.chassis_no, "model": row.model, "product_name": row.product_name,
        "battery_chemistry": row.battery_chemistry or "", "customer_name": row.customer_name,
        "mobile": row.mobile, "whatsapp": row.whatsapp, "email": row.email,
        "konnect_invoice_no": row.konnect_invoice_no, "konnect_invoice_date": row.konnect_invoice_date,
        "invoice_date": row.invoice_date, "showroom_invoice_no": row.showroom_invoice_no,
        "dealer_code": row.dealer_code, "grand_total": row.grand_total, "sync_key": row.sync_key,
        "dealer": frappe.db.get_value("Customer", {"fx_konnect_party_code": row.dealer_code}),
        "import_warnings": "\n".join(row.warnings),
    })

    # Which date starts the warranty is a FLEETO decision -> setting.
    start = row.konnect_invoice_date if settings().warranty_start_basis == "Konnect Invoice Date" else row.invoice_date

    existing = {c.serial_no: c for c in doc.components}
    for comp in row.components:
        if comp.serial_no in existing:
            continue  # never overwrite: may already carry a non-reset replacement history
        policy = warranty_policy(comp.component_type, row.model)
        end = warranty_rules.warranty_end(getdate(start), policy.months) if (policy and start) else None
        doc.append("components", {
            "component_type": comp.component_type, "serial_no": comp.serial_no,
            "warranty_start": start, "warranty_end": end, "source_column": comp.source_column,
        })

    doc.flags.ignore_permissions = True
    doc.save()
    return not name
