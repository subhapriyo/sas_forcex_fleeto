"""Install / migrate hooks.

before_*: create the FX roles. DocType permissions reference them, and
migrate syncs DocTypes BEFORE fixtures, so roles must exist first.

after_*: custom fields on STANDARD DocTypes.

We never edit Customer / Sales Invoice JSON. Custom Fields survive ERPNext
upgrades and are recreated idempotently on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from .services.constants import ROLES

CUSTOM_FIELDS = {
    "Customer": [
        {"fieldname": "fx_konnect_party_code", "label": "Konnect Party Code", "fieldtype": "Data",
         "insert_after": "customer_name", "unique": 1, "search_index": 1},
        {"fieldname": "fx_distributor", "label": "Distributor", "fieldtype": "Link", "options": "Customer",
         "insert_after": "fx_konnect_party_code"},
    ],
    "Sales Invoice": [
        {"fieldname": "fx_service_ticket", "label": "Service Ticket", "fieldtype": "Link",
         "options": "HD Ticket", "insert_after": "customer", "read_only": 1},
    ],
    "Delivery Note": [
        {"fieldname": "fx_service_ticket", "label": "Service Ticket", "fieldtype": "Link",
         "options": "HD Ticket", "insert_after": "customer", "read_only": 1},
    ],
}


def ensure_roles():
    """Idempotent: creates any missing FX role, leaves existing ones alone."""
    for role in ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


before_install = ensure_roles
before_migrate = ensure_roles


# Bulk upload (Data Import) on STANDARD DocTypes for the two head roles.
# FLEETO DocTypes carry their import rights in their own JSON (tools/doctype_specs.py).
BULK_IMPORTERS = ["FX Warranty Service Head", "FX Operations Head"]
BULK_IMPORT_RIGHTS = {
    "Customer": ("read", "write", "create", "report", "import"),
    "HD Ticket": ("read", "write", "create", "report", "import"),
    "Data Import": ("read", "write", "create"),  # the import tool itself
}


def grant_bulk_import():
    """Idempotent. Adds Custom DocPerm rows; Frappe copies the standard rules first,
    so existing access on these DocTypes is kept."""
    from frappe.permissions import add_permission, update_permission_property

    for doctype, rights in BULK_IMPORT_RIGHTS.items():
        for role in BULK_IMPORTERS:
            if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}):
                add_permission(doctype, role, 0)
            for ptype in rights:
                update_permission_property(doctype, role, 0, ptype, 1, validate=False)


def after_install():
    create_custom_fields(CUSTOM_FIELDS, update=True)
    from .integrations import helpdesk

    helpdesk.setup()  # FLEETO tickets live in ForceX Helpdesk (HD Ticket)
    grant_bulk_import()

    # Read-only field on a Single: defaults are not written for existing records
    from .tools.doctype_specs import SPECS

    endpoint = next(x["default"] for x in SPECS["FX Service Settings"]["fields"]
                    if x["fieldname"] == "konnect_inbound_endpoint")
    if frappe.db.get_single_value("FX Service Settings", "konnect_inbound_endpoint") != endpoint:
        frappe.db.set_single_value("FX Service Settings", "konnect_inbound_endpoint", endpoint)


after_migrate = after_install
