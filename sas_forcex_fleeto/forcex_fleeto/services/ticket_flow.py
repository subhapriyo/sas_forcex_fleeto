"""
Ticket lifecycle = a small, explicit state machine.

Why not Frappe's Workflow DocType?
    Workflow is great for approval chains with roles, and we DO use it for
    the Goodwill approval step (see docs). But the operational status here
    changes from code (e.g. "MIR submitted" moves the ticket), and branching
    depends on component type. Keeping the allowed moves in one Python dict
    makes them testable and greppable.

To change the flow: edit TRANSITIONS, then run tests/test_ticket_flow.py.
The Desk form reads `next_statuses()` to show only valid action buttons.
"""

from __future__ import annotations

from .constants import Status as S
from .constants import TicketType as T

TRANSITIONS: dict[str, dict[str, set[str]]] = {
    # ---------------- blue lane in the process-flow slide ----------------
    T.SERVICE: {
        S.DRAFT: {S.OPEN},
        S.OPEN: {S.INVOICE_VERIFIED, S.REJECTED},
        S.INVOICE_VERIFIED: {S.TELE_TRIAGE},
        S.TELE_TRIAGE: {S.FEEDBACK_PENDING, S.TECH_ASSIGNED},
        S.TECH_ASSIGNED: {S.FEEDBACK_PENDING, S.VISIT_DONE_UNRESOLVED},
        S.VISIT_DONE_UNRESOLVED: {S.TECH_ASSIGNED},
        # negative feedback goes back to triage
        S.FEEDBACK_PENDING: {S.CLOSED, S.TELE_TRIAGE},
        S.REJECTED: set(),
        S.CLOSED: set(),
    },
    # ---------------- yellow lane ----------------
    T.WARRANTY: {
        S.DRAFT: {S.OPEN},
        S.OPEN: {S.MATERIAL_RECEIVED, S.REJECTED},
        S.MATERIAL_RECEIVED: {S.UNDER_INSPECTION, S.GOODWILL_PENDING, S.REJECTED},
        S.GOODWILL_PENDING: {S.UNDER_INSPECTION, S.REJECTED},
        # inspection outcome decides the branch (see warranty_rules)
        S.UNDER_INSPECTION: {S.READY_TO_DISPATCH, S.AT_SUPPLIER, S.CREDIT_NOTE_PENDING, S.REJECTED},
        S.AT_SUPPLIER: {S.RECEIVED_FROM_SUPPLIER, S.CREDIT_NOTE_PENDING},
        S.RECEIVED_FROM_SUPPLIER: {S.READY_TO_DISPATCH},
        S.READY_TO_DISPATCH: {S.DISPATCHED},
        S.DISPATCHED: {S.DELIVERED},
        S.DELIVERED: {S.FEEDBACK_PENDING},
        S.CREDIT_NOTE_PENDING: {S.CLOSED, S.FEEDBACK_PENDING},
        S.FEEDBACK_PENDING: {S.CLOSED},
        S.REJECTED: set(),
        S.CLOSED: set(),
    },
}

TERMINAL = {S.CLOSED, S.REJECTED}


class InvalidTransition(Exception):
    pass


def next_statuses(ticket_type: str, current: str) -> list[str]:
    """Statuses reachable from `current` — used to render action buttons."""
    return sorted(TRANSITIONS.get(ticket_type, {}).get(current, set()))


def assert_transition(ticket_type: str, old: str | None, new: str) -> None:
    """Raise InvalidTransition unless old -> new is allowed for this track."""
    if old == new or old is None:  # unchanged, or brand-new document
        return
    lane = TRANSITIONS.get(ticket_type)
    if lane is None:
        raise InvalidTransition(f"Unknown ticket type '{ticket_type}'")
    if new not in lane.get(old, set()):
        allowed = ", ".join(next_statuses(ticket_type, old)) or "none (terminal)"
        raise InvalidTransition(f"{ticket_type} ticket cannot move from '{old}' to '{new}'. Allowed: {allowed}")


def after_material_receipt(is_in_warranty: bool, wants_goodwill: bool) -> str:
    """The first diamond on the warranty lane."""
    if is_in_warranty:
        return S.UNDER_INSPECTION
    return S.GOODWILL_PENDING if wants_goodwill else S.REJECTED
