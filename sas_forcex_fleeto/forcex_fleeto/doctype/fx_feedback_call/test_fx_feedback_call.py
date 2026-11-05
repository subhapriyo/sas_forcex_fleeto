"""Integration: queue build -> FIFO open -> outcomes."""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from sas_forcex_fleeto.forcex_fleeto import tasks
from sas_forcex_fleeto.forcex_fleeto.api.feedback_desk import open_next_call

# Frappe auto-builds _Test records for every DocType this one links to and COMMITS
# them before the tests start (frappe/tests/classes/integration_test_case.py). On a
# dev site that clashes with real masters (e.g. Fiscal Year), so we opt out and
# create only the few records each test needs.
IGNORE_TEST_RECORD_DEPENDENCIES = ["FX Feedback Questionnaire", "FX Vehicle Registry", "User"]

def questionnaire():
    if frappe.db.exists("FX Feedback Questionnaire", "FB-Q-TEST-01"):
        return
    frappe.get_doc({
        "doctype": "FX Feedback Questionnaire", "code": "FB-Q-TEST-01", "questionnaire_name": "Test",
        "status": "Active", "effective_from": add_days(nowdate(), -60), "call_after_days": 7, "max_attempts": 2,
        "questions": [
            {"question": "Service?", "answer_type": "Star rating (1-5)", "mandatory": 1, "active": 1},
            {"question": "Recommend?", "answer_type": "Yes / No / Maybe", "mandatory": 1, "active": 1,
             "is_recommend_question": 1},
        ],
    }).insert()


def vehicle(chassis, inv, days_ago):
    if frappe.db.exists("FX Vehicle Registry", chassis):
        return
    frappe.get_doc({"doctype": "FX Vehicle Registry", "chassis_no": chassis, "customer_name": f"Rider {inv}",
                    "mobile": "+919830000001", "konnect_invoice_no": inv,
                    "invoice_date": add_days(nowdate(), -days_ago)}).insert()


class TestFeedbackDesk(IntegrationTestCase):
    def setUp(self):
        # Rollback is per class, so clear calls left by the previous test.
        frappe.db.delete("FX Feedback Call", {"invoice_no": ["like", "INV-FB-%"]})
        questionnaire()
        vehicle("MD9FBTEST00000001", "INV-FB-OLD", 20)
        vehicle("MD9FBTEST00000002", "INV-FB-NEW", 10)
        vehicle("MD9FBTEST00000003", "INV-FB-NOTDUE", 3)

    def test_queue_is_built_once_and_fifo(self):
        tasks.build_feedback_queue()
        self.assertEqual(tasks.build_feedback_queue(), 0)  # idempotent
        self.assertFalse(frappe.db.exists("FX Feedback Call", {"invoice_no": "INV-FB-NOTDUE"}))
        first = frappe.get_doc("FX Feedback Call", open_next_call())
        self.assertEqual(first.invoice_no, "INV-FB-OLD")
        self.assertEqual(len(first.answers), 2)

    def test_connected_requires_mandatory_answers(self):
        tasks.build_feedback_queue()
        call = frappe.get_doc("FX Feedback Call", open_next_call())
        with self.assertRaises(frappe.ValidationError):
            call.submit_outcome("Connected", json.dumps({"1": 5}))
        call.reload()
        call.submit_outcome("Connected", json.dumps({"1": 2, "2": "Yes"}))
        self.assertEqual(call.status, "Completed")
        self.assertEqual(call.is_detractor, 1)

    def test_unreachable_after_max_attempts(self):
        tasks.build_feedback_queue()
        call = frappe.get_doc("FX Feedback Call", open_next_call())
        call.submit_outcome("Not Reachable")
        self.assertEqual(call.status, "Queued")
        call.submit_outcome("Not Reachable")
        self.assertEqual(call.status, "Unreachable")
