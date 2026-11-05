"""
FX Job Card — Screen 4 (mobile digital job card).

Submitting the job card is the technician's "I'm done" signal:
    READY -> ticket goes to Feedback Pending (Customer Care calls)
    FAIL  -> ticket goes back to the scheduler for another visit
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime

from sas_forcex_fleeto.forcex_fleeto.services.constants import Status
from sas_forcex_fleeto.forcex_fleeto.utils import move_ticket


class FXJobCard(Document):
    def validate(self):
        if self.arrival_time and self.departure_time and get_datetime(self.departure_time) <= get_datetime(self.arrival_time):
            frappe.throw(_("Departure must be after arrival"))

    def before_submit(self):
        # Signatures + GPS are the proof-of-visit; refuse to submit without them.
        missing = [label for field, label in (
            ("customer_signature", _("Dealer / Customer Signature")),
            ("technician_signature", _("Technician Signature")),
            ("arrival_lat", _("GPS arrival location")),
            ("odometer_photo", _("Odometer Photo")),
        ) if not self.get(field)]
        if missing:
            frappe.throw(_("Required to submit: {0}").format(", ".join(missing)))

    def on_submit(self):
        frappe.db.set_value("FX Technician Booking", self.booking, "status", "Done")
        if self.ticket:
            move_ticket(self.ticket, Status.FEEDBACK_PENDING if self.vehicle_status == "READY"
                        else Status.VISIT_DONE_UNRESOLVED)
