"""
Ticket lifecycle = a small, explicit state machine.

Why not Frappe's Workflow DocType?
    The stage changes from code as well as from people (e.g. submitting an
    inspection moves the ticket), and the branches depend on component type
    and warranty status. Keeping the allowed moves in one Python dict makes
    them testable and greppable.

Three rules live here:
    assert_transition()    is old -> new an allowed move on this lane?
    check_warranty_gate()  inspection only for in-warranty claims, or with goodwill approved
    after_material_receipt() which way the claim goes once the part arrives

To change the flow: edit TRANSITIONS, then run tests/test_ticket_flow.py.
Helpdesk and the Desk form read `next_statuses()` to show only valid buttons.
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
START = {S.DRAFT, S.OPEN}   # a new ticket enters the flow here, never part-way through


class InvalidTransition(Exception):
    pass


def next_statuses(ticket_type: str, current: str) -> list[str]:
    """Statuses reachable from `current` — used to render action buttons."""
    return sorted(TRANSITIONS.get(ticket_type, {}).get(current, set()))


def assert_transition(ticket_type: str, old: str | None, new: str) -> None:
    """Raise InvalidTransition unless old -> new is allowed for this track."""
    if old is None:  # brand-new ticket
        if new not in START:
            raise InvalidTransition(f"A new {ticket_type} ticket starts as Draft or Open, not '{new}'")
        return
    if old == new:
        return
    lane = TRANSITIONS.get(ticket_type)
    if lane is None:
        raise InvalidTransition(f"Unknown ticket type '{ticket_type}'")
    if new not in lane.get(old, set()):
        allowed = ", ".join(next_statuses(ticket_type, old)) or "none (terminal)"
        raise InvalidTransition(f"{ticket_type} ticket cannot move from '{old}' to '{new}'. Allowed: {allowed}")


def check_warranty_gate(old: str | None, new: str, *, in_warranty: bool, may_approve_goodwill: bool) -> None:
    """Who may send a claim to inspection.

    The move table allows Material Received -> Under Inspection, but only an
    in-warranty claim may take it; an expired one must go through goodwill,
    and only a goodwill approver may release it from there.
    """
    if new != S.UNDER_INSPECTION:
        return
    if old == S.MATERIAL_RECEIVED and not in_warranty:
        raise InvalidTransition("This claim is out of warranty: request goodwill approval instead")
    if old == S.GOODWILL_PENDING and not may_approve_goodwill:
        raise InvalidTransition("Only a goodwill approver can send this claim to inspection")


def after_material_receipt(is_in_warranty: bool, wants_goodwill: bool) -> str:
    """The first diamond on the warranty lane."""
    if is_in_warranty:
        return S.UNDER_INSPECTION
    return S.GOODWILL_PENDING if wants_goodwill else S.REJECTED
