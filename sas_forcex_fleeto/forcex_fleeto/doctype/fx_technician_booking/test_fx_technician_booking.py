"""Integration: calendar conflict prevention on a real database."""

import unittest

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

# Frappe auto-builds _Test records for every DocType this one links to and COMMITS
# them before the tests start (frappe/tests/classes/integration_test_case.py). On a
# dev site that clashes with real masters (e.g. Fiscal Year), so we opt out and
# create only the few records each test needs.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Employee", "FX Service Ticket"]

def site_company() -> str | None:
    """Employees need a Company. A fresh site may not have one yet."""
    return frappe.db.get_single_value("Global Defaults", "default_company") or next(
        iter(frappe.get_all("Company", pluck="name", limit=1)), None)


def technician(name="FX Test Tech"):
    emp = frappe.db.get_value("Employee", {"employee_name": name})
    if emp:
        return emp
    company = site_company()
    return frappe.get_doc({"doctype": "Employee", "first_name": name, "gender": "Male", "date_of_birth": "1990-01-01",
                           "date_of_joining": "2020-01-01", "company": company, "status": "Active"}).insert().name


def book(tech, start, end, status="Assigned"):
    return frappe.get_doc({"doctype": "FX Technician Booking", "technician": tech, "booking_date": nowdate(),
                           "from_time": start, "to_time": end, "status": status, "notify": 0})


class TestBooking(IntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Site set-up gap, not a code bug: say so clearly instead of crashing.
        if not site_company():
            raise unittest.SkipTest("No Company on this site; create one (setup wizard) to run booking tests")

    # Frappe rolls back per test CLASS, not per test -> start each test clean.
    def setUp(self):
        frappe.db.delete("FX Technician Booking", {"technician": technician(), "booking_date": nowdate()})

    def test_double_booking_rejected(self):
        tech = technician()
        book(tech, "09:00:00", "11:00:00").insert()
        with self.assertRaises(frappe.ValidationError):
            book(tech, "10:00:00", "12:00:00").insert()

    def test_adjacent_slot_allowed(self):
        tech = technician()
        book(tech, "09:00:00", "11:00:00").insert()
        book(tech, "11:00:00", "13:00:00").insert()

    def test_cancelled_booking_frees_slot(self):
        tech = technician()
        b = book(tech, "14:30:00", "16:30:00").insert()
        b.status = "Cancelled"
        b.save()
        book(tech, "14:30:00", "16:30:00").insert()
