"""
WhatsApp / SMS adapter — provider-agnostic on purpose.

FX Service Settings › WhatsApp Sender holds the dotted path of ANY function
with the signature   send(mobile: str, message: str) -> str | None
e.g. a wrapper around the frappe_whatsapp app, Gupshup, Interakt or Twilio.

If it is blank we do NOT fail: the message is logged as a Comment on the
document, so UAT can run before the provider account is approved.
"""

import frappe

from sas_forcex_fleeto.forcex_fleeto.utils import settings


def enqueue_send(mobile: str, message: str, ref_doctype: str, ref_name: str):
    frappe.enqueue(send, mobile=mobile, message=message, ref_doctype=ref_doctype, ref_name=ref_name,
                   enqueue_after_commit=True)


def send(mobile: str, message: str, ref_doctype: str, ref_name: str):
    # The record can vanish before the job runs (deleted, or a rolled-back test).
    # Nothing to report against, so skip instead of failing the job.
    if not frappe.db.exists(ref_doctype, ref_name):
        return
    path = settings().whatsapp_sender
    status = "logged only (no provider configured)"
    if path and mobile:
        try:
            frappe.get_attr(path)(mobile, message)
            status = "sent"
        except Exception:
            frappe.log_error(title="FX WhatsApp send failed", reference_doctype=ref_doctype, reference_name=ref_name)
            status = "FAILED (see Error Log)"
    ref = frappe.get_doc(ref_doctype, ref_name)
    ref.add_comment("Info", f"WhatsApp to {mobile}: {status}<br>{frappe.utils.escape_html(message)}")
    if status == "sent" and ref.meta.has_field("whatsapp_sent"):
        ref.db_set("whatsapp_sent", 1)  # only a real send flips the flag


def send_booking_alert(booking: str):
    """Screen 3 dispatch alert to technician and dealer."""
    b = frappe.get_doc("FX Technician Booking", booking)
    t = frappe.db.get_value("FX Service Ticket", b.ticket,
                            ["customer_name", "mobile", "damage_details", "business_partner"], as_dict=True) or {}
    tech_mobile = frappe.db.get_value("Employee", b.technician, "cell_number")
    msg = (f"Job {b.ticket} on {b.booking_date} {b.from_time}-{b.to_time}. "
           f"Customer {t.get('customer_name')} ({t.get('mobile')}). Issue: {t.get('damage_details') or '-'}")
    send(tech_mobile, msg, b.doctype, b.name)
