"""
Konnect "Customer Invoice Line Report" -> clean, validated Python objects.

This module has NO Frappe imports on purpose: it can be unit-tested in a
plain virtualenv in milliseconds, and the same code runs inside the bench.
The Frappe side (api/konnect.py) only decides *where* to save the rows.

Pipeline for one export:

    read_xlsx(path) ──► parse_rows(header, rows) ──► ParseResult
                              │
                              ├─ _map_header()      every required column present?
                              ├─ _parse_one()       per-row cleaning + checks
                              └─ duplicate check    a serial may live on ONE vehicle only

Errors vs warnings:
    errors    -> the row is NOT imported (shown in FX Konnect Import Log)
    warnings  -> the row IS imported, but flagged for the data team
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .constants import ComponentType

# --------------------------------------------------------------------------
# Column contract with Konnect. Left = header text in the export,
# right = attribute name on ParsedRow. Change here if Konnect renames a column.
# --------------------------------------------------------------------------
REQUIRED_COLUMNS = {
    "Bill From Party Code": "dealer_code",
    "Bill From Party Name": "dealer_name",
    "Customer Name": "customer_name",
    "Mobile Number": "mobile_raw",
    "Invoice Date": "invoice_date_raw",
    "Konnect Invoice Number": "konnect_invoice_no",
    "Konnect Invoice Date": "konnect_invoice_date_raw",
    "Model": "model",
    "Battery Type": "battery_type",
    "Chassis": "chassis_no",
}

OPTIONAL_COLUMNS = {
    "WhatsApp No": "whatsapp_raw",
    "Email Address": "email",
    "Address": "address",
    "State": "state",
    "District": "district",
    "PIN": "pincode",
    "Showroom Invoice Number": "showroom_invoice_no",
    "Billing Type": "billing_type",
    "Product Name": "product_name",
    "Colour": "colour",
    "Volt": "volt",
    "Ah": "ah",
    "Quantity": "qty",
    "Unit Rate": "unit_rate",
    "Total Item Value Without GST": "net_amount",
    "CGST": "cgst",
    "SGST": "sgst",
    "IGST": "igst",
    "Total Item Value With GST": "grand_total",
}

# Columns that carry a component serial number -> component type.
# Battery1..6 get their chemistry from the "Battery Type" column (see below).
SERIAL_COLUMNS = {
    "Motor": ComponentType.MOTOR,
    "Controller": ComponentType.CONTROLLER,
    "Charger": None,  # lead vs lithium charger follows battery chemistry
    "IOT": ComponentType.IOT,
}
BATTERY_COLUMNS = [f"Battery{i}" for i in range(1, 7)]

# "Battery Type" codes seen in Konnect. ASSUMPTION: "LED" = lead-acid.
# "WTBT" (probably "without battery") is intentionally unmapped -> warning.
# Confirm with FLEETO and extend via FX Konnect Settings > Battery Type Map.
DEFAULT_BATTERY_TYPE_MAP = {
    "LED": ComponentType.LEAD_ACID_BATTERY,
    "LEAD": ComponentType.LEAD_ACID_BATTERY,
    "LI": ComponentType.LITHIUM_BATTERY,
    "LITHIUM": ComponentType.LITHIUM_BATTERY,
}

EMPTY_TOKENS = {"", "NA", "N/A", "-", "NONE", "NULL"}
GST_TOLERANCE = 0.05          # rupees; Konnect rounds CGST/SGST separately
VIN_FORBIDDEN = set("IOQ")    # ISO 3779: VINs never contain I, O or Q


class KonnectFormatError(ValueError):
    """The file itself is wrong (e.g. a required column is missing)."""


@dataclass
class Component:
    component_type: str
    serial_no: str
    source_column: str


@dataclass
class ParsedRow:
    row_no: int                       # 1-based Excel row, for the import log
    dealer_code: str = ""
    dealer_name: str = ""
    customer_name: str = ""
    mobile: str | None = None
    whatsapp: str | None = None
    email: str = ""
    invoice_date: dt.date | None = None
    konnect_invoice_no: str = ""
    konnect_invoice_date: dt.date | None = None
    showroom_invoice_no: str = ""
    model: str = ""
    product_name: str = ""
    chassis_no: str = ""
    battery_chemistry: str | None = None
    grand_total: float = 0.0
    components: list[Component] = field(default_factory=list)
    raw: dict = field(default_factory=dict)       # untouched source values
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_importable(self) -> bool:
        return not self.errors

    @property
    def sync_key(self) -> str:
        """Stable key so re-importing the same export never duplicates data."""
        return f"{self.konnect_invoice_no}|{self.chassis_no}"


@dataclass
class ParseResult:
    rows: list[ParsedRow]

    def summary(self) -> dict:
        return {
            "total": len(self.rows),
            "importable": sum(r.is_importable for r in self.rows),
            "blocked": sum(not r.is_importable for r in self.rows),
            "with_warnings": sum(bool(r.warnings) for r in self.rows),
        }


# ==========================================================================
# Small, individually-tested helpers
# ==========================================================================
def clean(value) -> str:
    """Trim a cell to a string; treat NA-style placeholders as empty."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.upper() in EMPTY_TOKENS else text


def parse_date(value) -> dt.date | None:
    """Konnect sends D/M/YYYY text ("9/10/2026"); Excel may send datetimes."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = clean(value)
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        return dt.date(year, month, day)
    except ValueError:  # 31/02/2026 and friends
        return None


def normalize_mobile(value) -> str | None:
    """Return +91XXXXXXXXXX for a valid Indian mobile, else None."""
    digits = re.sub(r"\D", "", clean(value))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    return None


def to_float(value) -> float:
    try:
        return float(clean(value) or 0)
    except ValueError:
        return 0.0


def chassis_issues(chassis: str) -> list[str]:
    """Soft VIN checks. Returned as warnings — FLEETO data has known
    O-for-0 typos and we must not block a real sale because of them."""
    issues = []
    if len(chassis) != 17:
        issues.append(f"Chassis '{chassis}' is {len(chassis)} chars; a VIN has 17")
    bad = VIN_FORBIDDEN & set(chassis.upper())
    if bad:
        issues.append(
            f"Chassis '{chassis}' contains I/O/Q ({''.join(sorted(bad))}); "
            "probably a typo for 1/0 — fix at source in Konnect"
        )
    return issues


# ==========================================================================
# Main entry points
# ==========================================================================
def read_xlsx(path: str) -> tuple[list[str], list[list]]:
    """Read the first sheet. Kept tiny so the Frappe side can also feed
    rows that arrive from the Konnect REST API instead of a file."""
    import openpyxl  # imported lazily: only needed for file uploads

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        header = [clean(h) for h in next(it)]
        rows = [list(r) for r in it]
    finally:
        wb.close()
    return header, rows


def parse_rows(header: list[str], rows: list[list], battery_type_map: dict | None = None,
               strict_vin: bool = True) -> ParseResult:
    """Validate a whole export. Never raises for bad *rows* — only for a bad *file*.

    strict_vin=False silences the 17-char / I-O-Q chassis warnings. Use it if
    FLEETO confirms their chassis numbering is not ISO-3779 (the real export
    has "O" at position 9 on almost every chassis, which looks systematic).
    """
    col = _map_header(header)
    btmap = {k.upper(): v for k, v in (battery_type_map or DEFAULT_BATTERY_TYPE_MAP).items()}

    parsed: list[ParsedRow] = []
    serial_owner: dict[str, str] = {}  # serial -> chassis that first claimed it

    for idx, values in enumerate(rows, start=2):  # row 1 is the header
        if not any(clean(v) for v in values):
            continue  # export padding
        row = _parse_one(idx, values, col, btmap, strict_vin)

        # A component serial can belong to exactly one vehicle.
        for comp in row.components:
            owner = serial_owner.setdefault(comp.serial_no, row.chassis_no)
            if owner != row.chassis_no:
                row.errors.append(f"{comp.source_column} serial '{comp.serial_no}' already used on chassis {owner}")
        parsed.append(row)

    return ParseResult(parsed)


# ==========================================================================
# Internals
# ==========================================================================
def _map_header(header: list[str]) -> dict[str, int]:
    index = {clean(h): i for i, h in enumerate(header)}
    missing = [c for c in REQUIRED_COLUMNS if c not in index]
    if missing:
        raise KonnectFormatError(f"Konnect export is missing column(s): {', '.join(missing)}")
    return index


def _parse_one(row_no: int, values: list, col: dict[str, int], btmap: dict, strict_vin: bool = True) -> ParsedRow:
    def get(name):
        i = col.get(name)
        return values[i] if i is not None and i < len(values) else None

    row = ParsedRow(row_no=row_no, raw={h: get(h) for h in col})

    # --- identity ---------------------------------------------------------
    row.dealer_code = clean(get("Bill From Party Code"))
    row.dealer_name = clean(get("Bill From Party Name"))
    row.customer_name = clean(get("Customer Name"))
    row.konnect_invoice_no = clean(get("Konnect Invoice Number"))
    row.showroom_invoice_no = clean(get("Showroom Invoice Number"))
    row.chassis_no = clean(get("Chassis")).upper()
    row.model = clean(get("Model"))
    row.product_name = clean(get("Product Name"))
    row.email = clean(get("Email Address"))

    for label, value in (("Konnect Invoice Number", row.konnect_invoice_no),
                         ("Chassis", row.chassis_no),
                         ("Bill From Party Code", row.dealer_code)):
        if not value:
            row.errors.append(f"{label} is blank")

    # --- contact (feedback calls + WhatsApp depend on this) -----------------
    row.mobile = normalize_mobile(get("Mobile Number"))
    if not row.mobile:
        row.errors.append(f"Invalid mobile '{clean(get('Mobile Number'))}'")
    row.whatsapp = normalize_mobile(get("WhatsApp No")) or row.mobile

    # --- dates ---------------------------------------------------------------
    row.invoice_date = parse_date(get("Invoice Date"))
    row.konnect_invoice_date = parse_date(get("Konnect Invoice Date"))
    if not row.invoice_date:
        row.errors.append(f"Unreadable Invoice Date '{clean(get('Invoice Date'))}'")
    if row.invoice_date and row.konnect_invoice_date and row.invoice_date < row.konnect_invoice_date:
        # Retail invoice earlier than the dealer's purchase invoice: legal but suspicious.
        row.warnings.append(
            f"Invoice Date {row.invoice_date:%d-%m-%Y} is earlier than Konnect date "
            f"{row.konnect_invoice_date:%d-%m-%Y}"
        )

    # --- chassis sanity --------------------------------------------------
    if row.chassis_no and strict_vin:
        row.warnings.extend(chassis_issues(row.chassis_no))

    # --- money: GST must add up -----------------------------------------
    net, total = to_float(get("Total Item Value Without GST")), to_float(get("Total Item Value With GST"))
    tax = to_float(get("CGST")) + to_float(get("SGST")) + to_float(get("IGST"))
    row.grand_total = total
    if total and abs(net + tax - total) > GST_TOLERANCE:
        row.warnings.append(f"GST mismatch: {net:.2f} + {tax:.2f} != {total:.2f}")

    # --- components ------------------------------------------------------
    btype = clean(get("Battery Type")).upper()
    row.battery_chemistry = btmap.get(btype)
    if btype and not row.battery_chemistry:
        row.warnings.append(f"Battery Type '{btype}' is not mapped; battery/charger warranty route unknown")

    charger_type = (
        ComponentType.LITHIUM_CHARGER
        if row.battery_chemistry == ComponentType.LITHIUM_BATTERY
        else ComponentType.LEAD_CHARGER
    )
    for column, ctype in SERIAL_COLUMNS.items():
        serial = clean(get(column))
        if serial:
            row.components.append(Component(ctype or charger_type, serial, column))
    for column in BATTERY_COLUMNS:
        serial = clean(get(column))
        if serial:
            row.components.append(Component(row.battery_chemistry or ComponentType.OTHER, serial, column))

    # The chassis carries its own warranty (structural defects), so it gets a
    # component row like any other part; its serial is the chassis number.
    if row.chassis_no:
        row.components.append(Component(ComponentType.CHASSIS, row.chassis_no, "Chassis"))

    return row
