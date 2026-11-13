"""
WhatsApp adapter: the only place FLEETO talks to a WhatsApp provider.

Configured in FX WhatsApp Settings (Desk: /desk/fx-whatsapp-settings):
  * Meta WhatsApp Cloud API: built in. Each event (booking alert, feedback
    thank-you) can name an approved template; without one, plain text is sent.
  * Custom Function: any send(mobile, message) function, e.g. a Gupshup,
    Interakt or Twilio wrapper.
  * Log Only, or WhatsApp switched off: nothing leaves the system; the message
    is logged as a Comment on the record, so UAT runs before the provider
    account is approved.

Older sites: if FX WhatsApp Settings is off but FX Service Settings >
WhatsApp Sender is filled, that function is still used.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from sas_forcex_fleeto.forcex_fleeto.services import whatsapp_rules as rules
from sas_forcex_fleeto.forcex_fleeto.utils import settings

SETTINGS = "FX WhatsApp Settings"
ADMIN_ROLES = ("System Manager", "FX Operations Head", "FX Warranty Service Head")
# Template name/language fields in FX WhatsApp Settings for each event
EVENTS = {"booking": ("booking_template", "booking_template_language"),
          "feedback": ("feedback_template", "feedback_template_language")}


class SendError(Exception):
    pass


def wa_settings():
    return frappe.get_cached_doc(SETTINGS)


def enqueue_send(mobile: str, message: str, ref_doctype: str, ref_name: str,
                 event: str | None = None, params: list | None = None):
    frappe.enqueue(send, mobile=mobile, message=message, ref_doctype=ref_doctype, ref_name=ref_name,
                   event=event, params=params, enqueue_after_commit=True)


def send(mobile: str, message: str, ref_doctype: str, ref_name: str,
         event: str | None = None, params: list | None = None):
    """Send one message and record the outcome as a Comment on the record."""
    # The record can vanish before the job runs (deleted, or a rolled-back test).
    if not frappe.db.exists(ref_doctype, ref_name):
        return
    if not mobile:
        status = "skipped (no mobile number)"
    else:
        try:
            status = _deliver(mobile, message, event, params)
        except (SendError, rules.InvalidNumber) as e:
            status = f"FAILED: {e}"
            frappe.log_error(title="FX WhatsApp send failed", message=str(e),
                             reference_doctype=ref_doctype, reference_name=ref_name)
        except Exception:
            status = "FAILED (see Error Log)"
            frappe.log_error(title="FX WhatsApp send failed", reference_doctype=ref_doctype, reference_name=ref_name)
    ref = frappe.get_doc(ref_doctype, ref_name)
    ref.add_comment("Info", f"WhatsApp to {frappe.utils.escape_html(mobile or '-')}: {frappe.utils.escape_html(status)}"
                            f"<br>{frappe.utils.escape_html(message)}")
    if status.startswith("sent") and ref.meta.has_field("whatsapp_sent"):
        ref.db_set("whatsapp_sent", 1)  # only a real send flips the flag


def _deliver(mobile, message, event=None, params=None) -> str:
    """Returns a short status; raises SendError when the provider refuses."""
    s = wa_settings()
    if not s.enabled:
        legacy = settings().get("whatsapp_sender")
        if legacy:
            frappe.get_attr(legacy)(mobile, message)
            return "sent (FX Service Settings > WhatsApp Sender)"
        return "logged only (WhatsApp is switched off in FX WhatsApp Settings)"
    if s.provider == "Log Only":
        return "logged only (provider: Log Only)"
    if s.provider == "Custom Function":
        frappe.get_attr(s.custom_sender)(mobile, message)
        return "sent"

    to = rules.to_whatsapp_number(mobile, s.default_country_code)
    name_field, lang_field = EVENTS.get(event, (None, None))
    if name_field and s.get(name_field):
        payload = rules.template_payload(to, s.get(name_field), s.get(lang_field) or "en", params)
    else:
        payload = rules.text_payload(to, message)
    msg_id = _post_cloud_api(s, payload)
    return f"sent (Meta message id {msg_id})"


def _post_cloud_api(s, payload) -> str:
    import requests

    token = s.get_password("access_token", raise_exception=False)
    if not (s.phone_number_id and token):
        raise SendError(_("Phone Number ID and Access Token are required in FX WhatsApp Settings"))
    try:
        r = requests.post(rules.cloud_api_url(s.graph_api_version or "v21.0", s.phone_number_id),
                          json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    except requests.RequestException as e:
        raise SendError(f"Could not reach Meta: {e}") from e
    try:
        body = r.json()
    except ValueError:
        body = r.text
    if r.status_code >= 400:
        raise SendError(rules.cloud_error_text(body))
    return ((body.get("messages") or [{}])[0].get("id", "?")) if isinstance(body, dict) else "?"


@frappe.whitelist()
def send_test(mobile: str) -> dict:
    """'Send Test Message' button. Meta: the sample hello_world template."""
    frappe.only_for(ADMIN_ROLES)
    s = wa_settings()
    try:
        if not s.enabled:
            raise SendError(_("Tick 'Enable WhatsApp' first"))
        if s.provider == "Meta WhatsApp Cloud API":
            to = rules.to_whatsapp_number(mobile, s.default_country_code)
            detail = f"OK: Meta accepted the message (id {_post_cloud_api(s, rules.template_payload(to, 'hello_world', 'en_US'))})"
        else:
            detail = "OK: " + _deliver(mobile, "Test message from ForceX FLEETO")
        ok = True
    except (SendError, rules.InvalidNumber) as e:
        ok, detail = False, f"Failed: {e}"
    except Exception as e:
        frappe.log_error(title="FX WhatsApp test failed")
        ok, detail = False, f"Failed: {e}"
    frappe.db.set_single_value(SETTINGS, {"last_test_status": detail[:500], "last_test_on": now_datetime()})
    frappe.clear_document_cache(SETTINGS, SETTINGS)
    return {"ok": ok, "detail": detail}


def send_booking_alert(booking: str):
    """Screen 3 dispatch alert to the technician."""
    b = frappe.get_doc("FX Technician Booking", booking)
    t = frappe.db.get_value("HD Ticket", b.ticket, ["subject", "fx_vehicle"], as_dict=True) or frappe._dict()
    v = frappe.db.get_value("FX Vehicle Registry", t.get("fx_vehicle"), ["customer_name", "mobile"], as_dict=True) or {}
    t.update(v)
    tech_mobile = frappe.db.get_value("Employee", b.technician, "cell_number")
    slot = f"{b.from_time}-{b.to_time}"
    msg = (f"Job {b.ticket} on {b.booking_date} {slot}. "
           f"Customer {t.get('customer_name')} ({t.get('mobile')}). Issue: {t.get('subject') or '-'}")
    # Template body order: ticket, date, slot, customer, customer mobile, issue
    send(tech_mobile, msg, b.doctype, b.name, event="booking",
         params=[b.ticket, b.booking_date, slot, t.get("customer_name"), t.get("mobile"), t.get("subject")])
