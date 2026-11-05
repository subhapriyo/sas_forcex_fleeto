"""
Warranty policy for FLEETO — the "Component-Specific Warranty Logic Matrix".

Everything that a manager might one day ask "why did the system do that?"
about lives here, in plain functions with plain names:

    evaluate()             is this part still under warranty?
    continued_warranty_end non-reset rule for repaired / replaced parts
    missing_evidence()     the mandatory-attachment gate on Screen 1
    route_for()            which lane (lead-acid / supplier / factory)
    default_action()       what the inspector's dropdown should pre-select
    validate_settlement()  hard business rules (MD directives)

No Frappe imports -> unit-testable anywhere.
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass

from .constants import (
    COMPONENT_ROUTE,
    ClaimFor,
    WarrantyRoute,
)
from .constants import (
    ComponentType as C,
)
from .constants import (
    InspectionFinding as F,
)
from .constants import (
    SettlementAction as A,
)


class PolicyViolation(Exception):
    """A business rule was broken. The Frappe layer shows this via frappe.throw."""


# ==========================================================================
# 1. Warranty validity
# ==========================================================================
@dataclass
class WarrantyResult:
    status: str                  # "Active" | "Expired" | "Unknown"
    expires_on: dt.date | None
    reason: str = ""

    @property
    def is_active(self) -> bool:
        return self.status == "Active"


def add_months(d: dt.date, months: int) -> dt.date:
    """Calendar-safe month addition (31-Jan + 1 month -> 28/29-Feb)."""
    m = d.month - 1 + months
    year, month = d.year + m // 12, m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def warranty_end(start: dt.date, months: int) -> dt.date:
    """Last *covered* day. 12 months from 12-Jan-2026 -> 11-Jan-2027."""
    return add_months(start, months) - dt.timedelta(days=1)


def evaluate(start: dt.date | None, months: int, on: dt.date,
             km_limit: int | None = None, odometer_km: int | None = None) -> WarrantyResult:
    """Whichever comes first — time or kilometres — ends the warranty."""
    if not start or not months:
        return WarrantyResult("Unknown", None, "No sale date or warranty period on record")
    return status_for_end(warranty_end(start, months), on, km_limit, odometer_km)


def status_for_end(end: dt.date, on: dt.date,
                   km_limit: int | None = None, odometer_km: int | None = None) -> WarrantyResult:
    """Same check when the end date is already known (stored on the registry
    component, e.g. after a non-reset replacement)."""
    if on > end:
        return WarrantyResult("Expired", end, f"Expired on {end:%d-%b-%Y}")
    if km_limit and odometer_km is not None and odometer_km > km_limit:
        return WarrantyResult("Expired", end, f"Odometer {odometer_km} km exceeds {km_limit} km limit")
    return WarrantyResult("Active", end, f"Active until {end:%d-%b-%Y}")


def continued_warranty_end(original_end: dt.date, replaced_on: dt.date) -> dt.date:
    """Non-Reset Warranty Continuity (SOW Phase 3).

    A repaired or replacement part keeps the ORIGINAL part's end date. It
    never gets a fresh warranty. We also refuse to issue warranty work on a
    part whose warranty is already over (that must go through goodwill).
    """
    if replaced_on > original_end:
        raise PolicyViolation(
            f"Original warranty ended {original_end:%d-%b-%Y}; use Goodwill approval instead"
        )
    return original_end


# ==========================================================================
# 2. Evidence gate (Screen 1 + deck slide 6)
# ==========================================================================
# Which invoice copy is mandatory depends on who is claiming.
EVIDENCE_RULES: dict[str, str] = {
    ClaimFor.CUSTOMER: "customer_invoice",
    ClaimFor.INSTORE_DEALER: "distributor_invoice",
    ClaimFor.INSTORE_DISTRIBUTOR: "tally_invoice",
}
PHOTO_FIELDS = ("component_photo", "odometer_photo")


def missing_evidence(claim_for: str, files: dict[str, str | None]) -> list[str]:
    """Return the attachment fields still missing. Empty list = gate open."""
    missing = []
    invoice_field = EVIDENCE_RULES.get(claim_for)
    if invoice_field and not files.get(invoice_field):
        missing.append(invoice_field)
    if not any(files.get(f) for f in PHOTO_FIELDS):
        missing.append(" or ".join(PHOTO_FIELDS))
    return missing


# ==========================================================================
# 3. Routing + settlement rules
# ==========================================================================
def route_for(component_type: str) -> WarrantyRoute:
    try:
        return COMPONENT_ROUTE[component_type]
    except KeyError:
        raise ValueError(f"No warranty route configured for component '{component_type}'") from None


# What the inspector's "Settlement Action" defaults to, per lane and finding.
_DEFAULTS: dict[WarrantyRoute, dict[str, A]] = {
    WarrantyRoute.LEAD_ACID: {F.FOUND_OK: A.SAME_RETURN, F.REPAIRABLE: A.SAME_RETURN, F.IRREPARABLE: A.CREDIT_NOTE},
    WarrantyRoute.SUPPLIER: {F.FOUND_OK: A.SAME_RETURN, F.REPAIRABLE: A.SUPPLIER_RMA, F.IRREPARABLE: A.SUPPLIER_RMA},
    WarrantyRoute.FACTORY: {F.FOUND_OK: A.SAME_RETURN, F.REPAIRABLE: A.REPAIR_RETURN, F.IRREPARABLE: A.CREDIT_NOTE},
}

# Actions that are *allowed* per lane (REJECT is always allowed).
_ALLOWED: dict[WarrantyRoute, set[A]] = {
    WarrantyRoute.LEAD_ACID: {A.SAME_RETURN, A.CREDIT_NOTE},
    WarrantyRoute.SUPPLIER: {A.SAME_RETURN, A.SUPPLIER_RMA, A.CREDIT_NOTE},
    WarrantyRoute.FACTORY: {A.SAME_RETURN, A.REPAIR_RETURN, A.CREDIT_NOTE, A.REPLACE},
}


def default_action(component_type: str, finding: str) -> A:
    return _DEFAULTS[route_for(component_type)][finding]


def validate_settlement(component_type: str, finding: str, action: str, *,
                        value: float = 0, replace_threshold: float | None = None,
                        md_approved: bool = False) -> None:
    """Raise PolicyViolation if the chosen action breaks a rule."""
    if action == A.REJECT:
        return

    # MD directive: lead-acid units are NEVER replaced — even with approval.
    if component_type == C.LEAD_ACID_BATTERY and action == A.REPLACE:
        raise PolicyViolation(
            "Direct replacement of lead-acid batteries is prohibited (MD directive). Issue a Credit Note."
        )

    route = route_for(component_type)
    if action not in _ALLOWED[route]:
        hint = "no in-house cell repair; send to supplier" if route == WarrantyRoute.SUPPLIER else ""
        raise PolicyViolation(f"'{action}' is not allowed for {component_type}. {hint}".strip())

    if action == A.REPLACE and replace_threshold is not None and value > replace_threshold and not md_approved:
        raise PolicyViolation(
            f"Replacement value {value:,.2f} exceeds threshold {replace_threshold:,.2f}; MD approval required"
        )
