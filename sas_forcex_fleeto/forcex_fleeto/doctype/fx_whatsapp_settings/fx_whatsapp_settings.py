"""FX WhatsApp Settings — how FLEETO sends WhatsApp messages (Single DocType).

Sending itself lives in adapters/whatsapp.py; payload rules in services/whatsapp_rules.py.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document


class FXWhatsAppSettings(Document):
    def validate(self):
        self.default_country_code = re.sub(r"\D", "", self.default_country_code or "") or "91"
        if self.provider == "Custom Function" and self.custom_sender:
            try:
                frappe.get_attr(self.custom_sender)
            except Exception:
                frappe.throw(_("Sender Function {0} was not found. Check the dotted path.").format(self.custom_sender))

    def on_update(self):
        frappe.clear_document_cache(self.doctype, self.name)  # the adapter reads the cached doc
