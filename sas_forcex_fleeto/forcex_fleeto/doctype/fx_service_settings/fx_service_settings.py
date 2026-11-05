"""FX Service Settings — single place for every tunable rule."""

import json

import frappe
from frappe import _
from frappe.model.document import Document

from sas_forcex_fleeto.forcex_fleeto.services.constants import ComponentType


class FXServiceSettings(Document):
    def validate(self):
        # Battery type map must be JSON {code: ComponentType}
        try:
            mapping = json.loads(self.battery_type_map or "{}")
        except ValueError:
            frappe.throw(_("Battery Type Map must be valid JSON"))
        bad = {v for v in mapping.values() if v not in ComponentType.values()}
        if bad:
            frappe.throw(_("Unknown component type(s) in Battery Type Map: {0}").format(", ".join(bad)))

        # One generic policy per component; duplicates make results ambiguous.
        seen = set()
        for p in self.warranty_policies:
            key = (p.component_type, (p.model or "").lower())
            if key in seen:
                frappe.throw(_("Duplicate warranty policy for {0} / {1}").format(p.component_type, p.model or "all models"))
            seen.add(key)
            if p.months <= 0:
                frappe.throw(_("Warranty months must be positive ({0})").format(p.component_type))

    def on_update(self):
        frappe.clear_document_cache(self.doctype, self.name)  # utils.settings() uses the cache
