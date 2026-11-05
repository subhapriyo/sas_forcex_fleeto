"""
FX Technician Booking — Screen 3 (Centralised Field Resource Calendar).

Double-booking protection, two layers:
  1. scheduler.find_conflicts()  — the rule ("what counts as busy").
  2. Row lock on the Employee    — the guarantee. Two coordinators clicking
     "Confirm" on the same slot at the same second are serialised: the
     second request waits, then sees the first booking and fails cleanly.
     (A plain SELECT check alone has a race window.)
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from sas_forcex_fleeto.forcex_fleeto.services import scheduler
from sas_forcex_fleeto.forcex_fleeto.services.constants import Status
from sas_forcex_fleeto.forcex_fleeto.utils import as_time, business_rules, move_ticket


class FXTechnicianBooking(Document):
    def validate(self):
        with business_rules("Booking not possible"):
            scheduler.validate_booking(self._as_booking())
        if self.status in scheduler.BUSY_STATUSES:
            self._prevent_double_booking()

    def on_update(self):
        before = self.get_doc_before_save()
        newly_assigned = self.status == "Assigned" and (not before or before.status != "Assigned")
        if newly_assigned and self.ticket:
            ticket_status = frappe.db.get_value("FX Service Ticket", self.ticket, "status")
            if ticket_status in (Status.TELE_TRIAGE, Status.VISIT_DONE_UNRESOLVED):
                move_ticket(self.ticket, Status.TECH_ASSIGNED)
            if self.notify:
                # Do not slow the save down with an HTTP call to the WhatsApp provider.
                frappe.enqueue("sas_forcex_fleeto.forcex_fleeto.adapters.whatsapp.send_booking_alert",
                               booking=self.name, enqueue_after_commit=True)

    # ----------------------------------------------------------------------
    def _as_booking(self) -> scheduler.Booking:
        return scheduler.Booking(
            technician=self.technician, day=getdate(self.booking_date),
            start=as_time(self.from_time), end=as_time(self.to_time),
            ticket=self.ticket or "", status=self.status,
        )

    def _prevent_double_booking(self):
        # Layer 2: serialise all bookings for this technician.
        frappe.db.get_value("Employee", self.technician, "name", for_update=True)

        rows = frappe.get_all(
            "FX Technician Booking",
            filters={"technician": self.technician, "booking_date": self.booking_date, "name": ["!=", self.name or ""]},
            fields=["ticket", "from_time", "to_time", "status"],
        )
        existing = [
            scheduler.Booking(self.technician, getdate(self.booking_date), as_time(r.from_time), as_time(r.to_time),
                              r.ticket or "", r.status)
            for r in rows
        ]
        clashes = scheduler.find_conflicts(self._as_booking(), existing)
        if clashes:
            c = clashes[0]
            who = frappe.db.get_value("Employee", self.technician, "employee_name") or self.technician
            frappe.throw(
                _("{0} is already booked {1}–{2} ({3}).").format(
                    who, c.start.strftime("%I:%M %p"), c.end.strftime("%I:%M %p"), c.ticket or c.status),
                title=_("Calendar conflict"),
            )


@frappe.whitelist()
def roster(booking_date: str, zone: str | None = None) -> dict:
    """Data for the calendar grid: {technician: [{slot, ticket|None}]}."""
    day = getdate(booking_date)
    emp_filters = {"status": "Active", "designation": ["in", ["Field Technician", "Factory Engineer"]]}
    techs = frappe.get_list("Employee", filters=emp_filters, fields=["name", "employee_name"])
    rows = frappe.get_list("FX Technician Booking", filters={"booking_date": day, **({"zone": zone} if zone else {})},
                           fields=["technician", "ticket", "from_time", "to_time", "status"])
    bookings = [scheduler.Booking(r.technician, day, as_time(r.from_time), as_time(r.to_time), r.ticket or "", r.status)
                for r in rows]

    grid = {}
    for t in techs:
        cells = []
        for slot in scheduler.DEFAULT_SLOTS:
            probe = scheduler.Booking(t.name, day, slot.start, slot.end)
            hit = next(iter(scheduler.find_conflicts(probe, bookings)), None)
            cells.append({"slot": slot.label, "ticket": hit.ticket if hit else None,
                          "status": hit.status if hit else "Available"})
        grid[t.name] = {"name": t.employee_name, "cells": cells}
    return grid
