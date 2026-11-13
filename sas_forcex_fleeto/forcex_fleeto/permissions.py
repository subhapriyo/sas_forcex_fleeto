"""Who sees ForceX FLEETO on the Apps screen (hooks.py > add_to_apps_screen)."""

import frappe

from sas_forcex_fleeto.forcex_fleeto.services.constants import ROLES


def has_app_permission() -> bool:
    if frappe.session.user == "Administrator":
        return True
    return bool(set(frappe.get_roles()) & (set(ROLES) | {"System Manager"}))
