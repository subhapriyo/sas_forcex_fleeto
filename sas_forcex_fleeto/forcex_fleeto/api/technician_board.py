"""Screen 3: Technician Board (Desk page /desk/fx-technician-board).

One day per screen, one row per technician, one column per roster slot.
The board only READS; booking goes through FX Technician Booking.insert(),
so the row lock and overlap check in the controller still guard every booking.
"""

import frappe
from frappe import _
from frappe.utils import getdate

from sas_forcex_fleeto.forcex_fleeto.services import scheduler
from sas_forcex_fleeto.forcex_fleeto.services.constants import Status, TicketType
from sas_forcex_fleeto.forcex_fleeto.utils import as_time, settings

# Service tickets waiting for a technician (the stages that lead to "Technician Assigned")
BOOKABLE_STAGES = (Status.TELE_TRIAGE, Status.VISIT_DONE_UNRESOLVED)


def technicians() -> list[dict]:
    """Active employees whose Designation is listed in FX Service Settings."""
    designations = [d.strip() for d in (settings().get("technician_designations") or "").splitlines() if d.strip()]
    filters = {"status": "Active"}
    if designations:
        filters["designation"] = ["in", designations]
    return frappe.get_all("Employee", filters=filters, fields=["name", "employee_name", "designation", "cell_number"],
                          order_by="employee_name asc")


@frappe.whitelist()
def get_board(date: str | None = None) -> dict:
    """One day of the board: roster slots, and per technician one cell per slot with the bookings touching it."""
    frappe.has_permission("FX Technician Booking", "read", throw=True)
    day = getdate(date)
    techs = technicians()
    rows = frappe.get_all(
        "FX Technician Booking",
        filters={"booking_date": day, "technician": ["in", [t.name for t in techs] or [""]]},
        fields=["name", "technician", "ticket", "from_time", "to_time", "status"],
        order_by="from_time asc",
    )
    subjects = dict(frappe.get_all("HD Ticket", filters={"name": ["in", [r.ticket for r in rows if r.ticket] or [""]]},
                                   fields=["name", "subject"], as_list=True))
    bookings = [scheduler.Booking(r.technician, day, as_time(r.from_time), as_time(r.to_time),
                                  r.ticket or "", r.status, name=r.name) for r in rows]
    board = scheduler.day_board([t.name for t in techs], day, bookings)

    def booking_json(b):
        return {"name": b.name, "ticket": b.ticket, "subject": subjects.get(b.ticket, ""), "status": b.status,
                "from_time": f"{b.start:%H:%M}", "to_time": f"{b.end:%H:%M}"}

    return {
        "date": str(day),
        "slots": [{"start": f"{s.start:%H:%M:%S}", "end": f"{s.end:%H:%M:%S}", "label": s.label}
                  for s in scheduler.DEFAULT_SLOTS],
        "rows": [{"technician": t.name, "employee_name": t.employee_name, "designation": t.designation,
                  "cells": [{"free": c.free, "bookings": [booking_json(b) for b in c.bookings]}
                            for c in board[t.name]]} for t in techs],
        "can_book": bool(frappe.has_permission("FX Technician Booking", "create")),
    }


@frappe.whitelist()
def bookable_tickets(txt: str = "") -> list[dict]:
    """Service tickets waiting for a technician, for the booking dialog."""
    filters = {"ticket_type": TicketType.SERVICE, "fx_stage": ["in", BOOKABLE_STAGES]}
    or_filters = {"name": ["like", f"%{txt}%"], "subject": ["like", f"%{txt}%"]} if txt else None
    return frappe.get_list("HD Ticket", filters=filters, or_filters=or_filters,
                           fields=["name", "subject", "fx_stage", "fx_vehicle"], order_by="creation asc", limit=50)


@frappe.whitelist()
def book_slot(technician: str, date: str, from_time: str, to_time: str, ticket: str | None = None,
              status: str = "Assigned", notify: int = 1) -> str:
    """Book from the board. Insert goes through the booking controller, so the overlap check and row lock still apply."""
    if status not in ("Assigned", "Blocked"):
        frappe.throw(_("A new booking is either Assigned (a job) or Blocked (leave / transit)."))
    if status == "Assigned" and not ticket:
        frappe.throw(_("Pick the service ticket this visit is for."))
    doc = frappe.get_doc({
        "doctype": "FX Technician Booking", "technician": technician, "booking_date": date,
        "from_time": from_time, "to_time": to_time, "ticket": ticket if status == "Assigned" else None,
        "status": status, "notify": int(notify) if status == "Assigned" else 0,
    }).insert()   # permission, overlap check and row lock run here
    return doc.name
