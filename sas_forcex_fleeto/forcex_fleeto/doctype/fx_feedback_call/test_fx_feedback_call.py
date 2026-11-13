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


def build_queue_isolated():
    """Build the queue, then set aside every open call that is not this test's.

    The FIFO desk always serves the oldest open call on the SITE; on a dev site
    with demo or real Konnect data that is never a test row. Parking the others
    happens inside the test transaction, so Frappe's class rollback restores them.
    """
    n = tasks.build_feedback_queue()
    frappe.db.sql("""update `tabFX Feedback Call` set status='Customer Declined'
                     where invoice_no not like 'INV-FB-%%' and status in ('Queued', 'Call Back Later')""")
    return n


class TestFeedbackDesk(IntegrationTestCase):
    def setUp(self):
        # Rollback is per class, so clear calls left by the previous test.
        frappe.db.delete("FX Feedback Call", {"invoice_no": ["like", "INV-FB-%"]})
        questionnaire()
        vehicle("MD9FBTEST00000001", "INV-FB-OLD", 20)
        vehicle("MD9FBTEST00000002", "INV-FB-NEW", 10)
        vehicle("MD9FBTEST00000003", "INV-FB-NOTDUE", 3)

    def test_queue_is_built_once_and_fifo(self):
        build_queue_isolated()
        self.assertEqual(build_queue_isolated(), 0)  # idempotent
        self.assertFalse(frappe.db.exists("FX Feedback Call", {"invoice_no": "INV-FB-NOTDUE"}))
        first = frappe.get_doc("FX Feedback Call", open_next_call())
        self.assertEqual(first.invoice_no, "INV-FB-OLD")
        self.assertEqual(len(first.answers), 2)

    def test_connected_requires_mandatory_answers(self):
        build_queue_isolated()
        call = frappe.get_doc("FX Feedback Call", open_next_call())
        with self.assertRaises(frappe.ValidationError):
            call.submit_outcome("Connected", json.dumps({"1": 5}))
        call.reload()
        call.submit_outcome("Connected", json.dumps({"1": 2, "2": "Yes"}))
        self.assertEqual(call.status, "Completed")
        self.assertEqual(call.is_detractor, 1)

    def test_unreachable_after_max_attempts(self):
        build_queue_isolated()
        call = frappe.get_doc("FX Feedback Call", open_next_call())
        call.submit_outcome("Not Reachable")
        self.assertEqual(call.status, "Queued")
        call.submit_outcome("Not Reachable")
        self.assertEqual(call.status, "Unreachable")


class TestFeedbackDeskPage(IntegrationTestCase):
    """api/feedback_desk get_call / submit_call, as used by the Feedback Desk page."""

    def setUp(self):
        frappe.db.delete("FX Feedback Call", {"invoice_no": ["like", "INV-FB-%"]})
        questionnaire()
        vehicle("MD9FBTEST00000001", "INV-FB-OLD", 20)

    def test_get_and_submit_call(self):
        from sas_forcex_fleeto.forcex_fleeto.api.feedback_desk import get_call, submit_call
        build_queue_isolated()
        name = open_next_call()
        c = get_call(name)
        self.assertEqual(c["invoice_no"], "INV-FB-OLD")
        self.assertEqual([a["answer_type"] for a in c["answers"]], ["Star rating (1-5)", "Yes / No / Maybe"])
        r = submit_call(name, "Connected", json.dumps({"1": 5, "2": "Yes"}))
        self.assertEqual(r["status"], "Completed")
        self.assertEqual(r["is_detractor"], 0)


class TestQuestionnaireLock(IntegrationTestCase):
    """B5: once a version has answers, its questions cannot be reworded."""

    def setUp(self):
        frappe.db.delete("FX Feedback Call", {"invoice_no": ["like", "INV-FB-%"]})
        questionnaire()
        vehicle("MD9FBTEST00000001", "INV-FB-OLD", 20)

    def test_rewording_an_answered_question_is_blocked(self):
        build_queue_isolated()
        call = frappe.get_doc("FX Feedback Call", open_next_call())
        call.submit_outcome("Connected", json.dumps({"1": 4, "2": "Yes"}))
        q = frappe.get_doc("FX Feedback Questionnaire", call.questionnaire)
        q.questions[0].question = "Something else entirely?"
        with self.assertRaises(frappe.ValidationError):
            q.save()


class TestQueueBeyondFirstRows(IntegrationTestCase):
    """B4: calls on hold must not hide a due call further down the queue."""

    def setUp(self):
        frappe.db.delete("FX Feedback Call", {"invoice_no": ["like", "INV-FB-%"]})
        questionnaire()

    def test_due_call_found_behind_many_held_calls(self):
        from frappe.utils import add_to_date, now_datetime

        build_queue_isolated()  # parks every non-test open call
        later = add_to_date(now_datetime(), hours=4)
        for i in range(60):  # older than the due call, but all on hold for hours
            frappe.get_doc({"doctype": "FX Feedback Call", "invoice_no": f"INV-FB-HOLD-{i:02d}",
                            "invoice_date": add_days(nowdate(), -90), "status": "Call Back Later",
                            "hold_until": later}).insert(ignore_permissions=True)
        frappe.get_doc({"doctype": "FX Feedback Call", "invoice_no": "INV-FB-DUE",
                        "invoice_date": add_days(nowdate(), -10), "status": "Queued"}).insert(ignore_permissions=True)
        name = open_next_call()
        self.assertIsNotNone(name, "queue looked empty although a call was due")
        self.assertEqual(frappe.db.get_value("FX Feedback Call", name, "invoice_no"), "INV-FB-DUE")
