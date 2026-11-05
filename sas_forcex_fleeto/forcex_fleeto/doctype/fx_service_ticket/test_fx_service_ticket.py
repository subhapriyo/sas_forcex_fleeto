"""
Integration tests — need a bench site.

    bench --site forcex.localhost set-config allow_tests true
    bench --site forcex.localhost run-tests --module sas_forcex_fleeto.forcex_fleeto.doctype.fx_service_ticket.test_fx_service_ticket

Each test runs inside a transaction that is rolled back, so no cleanup needed.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from sas_forcex_fleeto.forcex_fleeto.services.constants import ComponentType, Status

# Frappe auto-builds _Test records for every DocType this one links to and COMMITS
# them before the tests start (frappe/tests/classes/integration_test_case.py). On a
# dev site that clashes with real masters (e.g. Fiscal Year), so we opt out and
# create only the few records each test needs.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Customer", "Delivery Note", "FX Material Inspection", "FX Supplier RMA", "FX Vehicle Registry", "Sales Invoice", "User"]

def make_vehicle(chassis="MD9TEST0000000001", serial="BAT-T-0001", months=12):
    settings = frappe.get_single("FX Service Settings")
    if not any(p.component_type == ComponentType.LEAD_ACID_BATTERY for p in settings.warranty_policies):
        settings.append("warranty_policies", {"component_type": ComponentType.LEAD_ACID_BATTERY, "months": months})
        settings.save()
    start = add_days(nowdate(), -30)
    return frappe.get_doc({
        "doctype": "FX Vehicle Registry", "chassis_no": chassis, "customer_name": "Test Rider",
        "mobile": "+919830000000", "konnect_invoice_no": "TINV-T-1", "invoice_date": start,
        "components": [{"component_type": ComponentType.LEAD_ACID_BATTERY, "serial_no": serial,
                        "warranty_start": start, "warranty_end": add_days(start, 364)}],
    }).insert(ignore_if_duplicate=True)


def make_ticket(**kw):
    v = make_vehicle()
    doc = frappe.get_doc({"doctype": "FX Service Ticket", "ticket_type": "Warranty", "claim_for": "Customer Claim",
                          "vehicle": v.name, "component_serial": "BAT-T-0001", **kw})
    return doc.insert()


class TestFXServiceTicket(IntegrationTestCase):
    def test_registry_match_and_warranty_status(self):
        t = make_ticket()
        self.assertEqual(t.system_match, 1)
        self.assertEqual(t.component_type, ComponentType.LEAD_ACID_BATTERY)
        self.assertEqual(t.warranty_status, "Active")

    def test_evidence_gate_blocks_submission(self):
        t = make_ticket()
        with self.assertRaises(frappe.ValidationError):
            t.set_status(Status.OPEN)

    def test_evidence_gate_opens_with_attachments(self):
        t = make_ticket(customer_invoice="/files/inv.pdf", component_photo="/files/p.png")
        t.set_status(Status.OPEN)
        self.assertEqual(t.status, Status.OPEN)

    def test_illegal_transition_rejected(self):
        t = make_ticket(customer_invoice="/files/inv.pdf", component_photo="/files/p.png")
        t.set_status(Status.OPEN)
        with self.assertRaises(frappe.ValidationError):
            t.set_status(Status.DISPATCHED)

    def test_serial_mismatch_needs_override_reason(self):
        t = make_ticket(component_serial="NOT-ON-VEHICLE", customer_invoice="/f/i.pdf", component_photo="/f/p.png")
        self.assertEqual(t.system_match, 0)
        with self.assertRaises(frappe.ValidationError):
            t.set_status(Status.OPEN)
        t.reload()
        t.override_reason = "Physical PDI tag differs from Konnect"
        t.set_status(Status.OPEN)


class TestLeadAcidPolicy(IntegrationTestCase):
    def test_mir_cannot_replace_lead_acid(self):
        t = make_ticket(customer_invoice="/f/i.pdf", component_photo="/f/p.png")
        mir = frappe.get_doc({"doctype": "FX Material Inspection", "ticket": t.name,
                              "component_type": ComponentType.LEAD_ACID_BATTERY, "finding": "Irreparable",
                              "settlement_action": "Replace Unit", "replacement_serial": "X", "md_approved": 1,
                              "scrap_tag": "PCB-HAZ-1"})
        with self.assertRaises(frappe.ValidationError):
            mir.insert()

    def test_irreparable_lead_acid_needs_scrap_tag(self):
        t = make_ticket(customer_invoice="/f/i.pdf", component_photo="/f/p.png")
        mir = frappe.get_doc({"doctype": "FX Material Inspection", "ticket": t.name,
                              "component_type": ComponentType.LEAD_ACID_BATTERY, "finding": "Irreparable",
                              "invoiced_value": 6500})
        with self.assertRaises(frappe.ValidationError):
            mir.insert()
        mir.scrap_tag = "PCB-HAZ-2026-8819"
        mir.insert()
        self.assertEqual(mir.settlement_action, "Issue Credit Note")
        self.assertEqual(mir.credit_note_amount, 6500)
