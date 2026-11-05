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


def after_install():
    create_custom_fields(CUSTOM_FIELDS, update=True)
    from .integrations import helpdesk

    helpdesk.setup()  # FLEETO tickets live in ForceX Helpdesk (HD Ticket)


after_migrate = after_install
