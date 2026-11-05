"""
Shared vocabulary for the ForceX FLEETO module.

Why a constants file?
    Every status, component type and settlement action is spelled exactly
    once here. DocType Select options, Python rules and tests all import
    from this file, so a typo like "Lead Acid" vs "Lead-Acid" can never
    silently break routing.

Rule of thumb for future edits:
    If you add a value here, also add it to the matching DocType Select
    field (see the docs, section "DocType field reference") and run the
    test-suite — tests/test_constants_sync.py will tell you if you forgot.
"""

from enum import Enum


class StrEnum(str, Enum):
    """Enum whose members compare equal to their string value.

    Frappe stores Select fields as plain strings, so `doc.status == Status.OPEN`
    must work without `.value` everywhere.
    """

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


# --------------------------------------------------------------------------
# Ticket classification
# --------------------------------------------------------------------------
class TicketType(StrEnum):
    SERVICE = "Service"      # blue track in the FLEETO process-flow slide
    WARRANTY = "Warranty"    # yellow track


class ClaimFor(StrEnum):
    """Who is raising a warranty claim (deck slide 5/6).

    Each value decides which invoice must be attached (see EVIDENCE_RULES).
    """

    CUSTOMER = "Customer Claim"
    INSTORE_DEALER = "Instore - Dealer"
    INSTORE_DISTRIBUTOR = "Instore - Distributor"


class ComponentType(StrEnum):
    LEAD_ACID_BATTERY = "Lead-Acid Battery"
    LITHIUM_BATTERY = "Lithium-Ion Battery"
    LITHIUM_CHARGER = "Lithium Charger"
    LEAD_CHARGER = "Lead Charger"
    MOTOR = "Motor"
    CONTROLLER = "Controller"
    CHASSIS = "Chassis"
    IOT = "IOT Device"
    OTHER = "Other"


class WarrantyRoute(StrEnum):
    """The three swim-lanes of the warranty matrix (SOW section 2)."""

    LEAD_ACID = "Lead-Acid Bench Check"
    SUPPLIER = "Supplier RMA (Lithium)"
    FACTORY = "Factory Workbench"


# Component -> route. Lithium *chargers* follow the supplier lane too
# (deck: "Lithium Battery and Charger"); lead chargers stay in the factory.
COMPONENT_ROUTE: dict[str, WarrantyRoute] = {
    ComponentType.LEAD_ACID_BATTERY: WarrantyRoute.LEAD_ACID,
    ComponentType.LITHIUM_BATTERY: WarrantyRoute.SUPPLIER,
    ComponentType.LITHIUM_CHARGER: WarrantyRoute.SUPPLIER,
    ComponentType.LEAD_CHARGER: WarrantyRoute.FACTORY,
    ComponentType.MOTOR: WarrantyRoute.FACTORY,
    ComponentType.CONTROLLER: WarrantyRoute.FACTORY,
    ComponentType.CHASSIS: WarrantyRoute.FACTORY,
    ComponentType.IOT: WarrantyRoute.FACTORY,
    ComponentType.OTHER: WarrantyRoute.FACTORY,
}


class InspectionFinding(StrEnum):
    FOUND_OK = "Found OK"
    REPAIRABLE = "Repairable"
    IRREPARABLE = "Irreparable"


class SettlementAction(StrEnum):
    SAME_RETURN = "Same Return"              # no fault / cleaned & recharged
    REPAIR_RETURN = "Repair & Same Return"   # fixed on factory workbench
    SUPPLIER_RMA = "Send to Supplier"        # lithium lane
    CREDIT_NOTE = "Issue Credit Note"
    REPLACE = "Replace Unit"                 # NEVER for lead-acid (MD directive)
    REJECT = "Reject Claim"


# --------------------------------------------------------------------------
# Ticket lifecycle statuses (one Select field, two tracks)
# --------------------------------------------------------------------------
class Status(StrEnum):
    DRAFT = "Draft"
    OPEN = "Open"                              # ticket confirmed / raised
    # --- service track ---
    INVOICE_VERIFIED = "Invoice Verified"
    TELE_TRIAGE = "Tele-Calling Triage"
    TECH_ASSIGNED = "Technician Assigned"
    VISIT_DONE_UNRESOLVED = "Visit Done - Unresolved"
    # --- warranty track ---
    MATERIAL_RECEIVED = "Material Received"
    GOODWILL_PENDING = "Goodwill Approval Pending"
    UNDER_INSPECTION = "Under Inspection"
    AT_SUPPLIER = "At Supplier"
    RECEIVED_FROM_SUPPLIER = "Received from Supplier"
    CREDIT_NOTE_PENDING = "Credit Note Pending"
    READY_TO_DISPATCH = "Ready to Dispatch"
    DISPATCHED = "Dispatched"
    DELIVERED = "Delivered"
    # --- shared tail ---
    FEEDBACK_PENDING = "Feedback Pending"
    REJECTED = "Claim Rejected"
    CLOSED = "Closed"


class CallStatus(StrEnum):
    """Status of one row in the Customer Feedback queue (Screens 7/8)."""

    QUEUED = "Queued"
    ON_HOLD = "Call Back Later"
    COMPLETED = "Completed"
    UNREACHABLE = "Unreachable"
    DECLINED = "Customer Declined"


class CallOutcome(StrEnum):
    """What the executive selects on the call form (Screen 8)."""

    CONNECTED = "Connected"
    NOT_REACHABLE = "Not Reachable"
    CALL_BACK_LATER = "Call Back Later"
    DECLINED = "Customer Declined"


class AnswerType(StrEnum):
    STAR = "Star rating (1-5)"
    YES_NO_MAYBE = "Yes / No / Maybe"
    YES_NO = "Yes / No"
    TEXT = "Free text"


# The 11 roles listed in the FRD deck (slide 4). Created as fixtures.
ROLES = [
    "FX CRM",
    "FX Coordinator",
    "FX Technical Coordinator",
    "FX Warranty Service Head",
    "FX Operations Head",
    "FX Business Partner",
    "FX Sales Team",
    "FX ASM",
    "FX RSM",
    "FX Sales Head",
    "FX Spare Store",
]
