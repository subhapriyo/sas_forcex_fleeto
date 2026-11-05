"""
Frappe glue shared by controllers and APIs.

The services/ package raises plain Python exceptions. This file turns them
into friendly Desk messages and gives one place to read settings.
"""

from __future__ import annotations

import datetime as dt
import json
from contextlib import contextmanager

import frappe
from frappe import _

from .services import feedback, settlement, ticket_flow, warranty_rules

# Every "business rule said no" exception from services/
RULE_ERRORS = (
    warranty_rules.PolicyViolation,
    ticket_flow.InvalidTransition,
    settlement.SettlementError,
    feedback.FeedbackError,
    ValueError,
)


@contextmanager
def business_rules(title: str = "Not allowed"):
    """Wrap service calls: `with business_rules(): validate_settlement(...)`.

    Converts the exception to frappe.throw so the user sees a clean red
    dialog instead of a traceback, and the transaction is rolled back.
    """
    try:
        yield
    except RULE_ERRORS as e:
        frappe.throw(str(e), title=_(title))


def settings():
    """FX Service Settings (Single DocType), cached per request."""
    return frappe.get_cached_doc("FX Service Settings")


def battery_type_map() -> dict:
    raw = settings().battery_type_map or "{}"
    try:
        return json.loads(raw)
    except ValueError:
        frappe.throw(_("FX Service Settings › Battery Type Map is not valid JSON"))


def warranty_policy(component_type: str, model: str | None = None):
    """Most specific policy wins: (component, model) before (component, any model)."""
    rows = [p for p in settings().warranty_policies if p.component_type == component_type]
    exact = [p for p in rows if p.model and model and p.model.lower() == model.lower()]
    generic = [p for p in rows if not p.model]
    return (exact or generic or [None])[0]


def as_time(value) -> dt.time | None:
    """MariaDB returns TIME columns as timedelta; Desk sends 'HH:MM:SS'."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.time):
        return value
    if isinstance(value, dt.timedelta):
        return (dt.datetime.min + value).time()
    return dt.time.fromisoformat(str(value))


def move_ticket(ticket: str, new_status: str, **values) -> None:
    """Change a ticket's status from another document (MIR, Job Card ...).

    Goes through the normal save() so the transition guard still runs.
    """
    doc = frappe.get_doc("FX Service Ticket", ticket)
    doc.update(values)
    doc.status = new_status
    doc.flags.ignore_permissions = True  # caller already passed its own permission check
    doc.save()


def users_with_role(role: str) -> list[str]:
    return frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent", distinct=True)


def notify(users: list[str], subject: str, doctype: str, name: str) -> None:
    """Bell-icon alert in Desk."""
    for user in users:
        frappe.get_doc({
            "doctype": "Notification Log", "for_user": user, "type": "Alert",
            "subject": subject, "document_type": doctype, "document_name": name,
        }).insert(ignore_permissions=True)
