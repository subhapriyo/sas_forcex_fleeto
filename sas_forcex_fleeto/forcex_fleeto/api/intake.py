"""Screen 1 lookup: find a vehicle by serial, invoice, chassis or mobile."""

import frappe

from sas_forcex_fleeto.forcex_fleeto.services.konnect_parser import normalize_mobile

MAX_HITS = 10
FIELDS = ["name", "customer_name", "mobile", "model", "konnect_invoice_no", "invoice_date", "dealer"]


@frappe.whitelist()
def lookup_vehicle(search_by: str, query: str) -> list[dict]:
    """Return up to 10 matching FX Vehicle Registry rows.

    Uses frappe.get_list (not get_all) so a Business Partner only sees
    vehicles their User Permissions allow.
    """
    query = (query or "").strip()
    if len(query) < 3:
        return []

    if search_by == "Serial Number":
        comps = frappe.get_all(
            "FX Vehicle Component",
            filters={"serial_no": query, "parenttype": "FX Vehicle Registry"},
            fields=["parent", "serial_no", "component_type"], limit=MAX_HITS,
        )
        by_parent = {c.parent: c for c in comps}
        hits = frappe.get_list("FX Vehicle Registry", filters={"name": ["in", list(by_parent) or [""]]}, fields=FIELDS)
        for h in hits:
            h["matched_serial"] = by_parent[h.name].serial_no
            h["matched_component_type"] = by_parent[h.name].component_type
        return hits

    if search_by == "Invoice Number":
        return frappe.get_list("FX Vehicle Registry", fields=FIELDS, limit=MAX_HITS,
                               or_filters={"konnect_invoice_no": query, "showroom_invoice_no": query})
    if search_by == "Chassis No":
        return frappe.get_list("FX Vehicle Registry", filters={"name": query.upper()}, fields=FIELDS)
    if search_by == "Customer Mobile":
        mobile = normalize_mobile(query)
        return frappe.get_list("FX Vehicle Registry", filters={"mobile": mobile}, fields=FIELDS, limit=MAX_HITS) if mobile else []

    frappe.throw(frappe._("Unknown search type {0}").format(search_by))
