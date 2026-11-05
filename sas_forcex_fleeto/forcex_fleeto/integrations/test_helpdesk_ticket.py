"""
Integration tests: FLEETO tickets as ForceX Helpdesk HD Tickets.

    bench --site fleeto.localhost run-tests --module sas_forcex_fleeto.forcex_fleeto.integrations.test_helpdesk_ticket

This module is not inside a DocType folder, so Frappe builds no _Test records
for it (only EXTRA_TEST_RECORD_DEPENDENCIES would be built, and there are none).
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from sas_forcex_fleeto.forcex_fleeto.integrations import helpdesk
from sas_forcex_fleeto.forcex_fleeto.services.constants import ComponentType, Status

CHASSIS, SERIAL = "MD9TESTHD00000001", "BAT-HD-0001"


def vehicle():
    s = frappe.get_single("FX Service Settings")
    if not any(p.component_type == ComponentType.LEAD_ACID_BATTERY and not p.model for p in s.warranty_policies):
        s.append("warranty_policies", {"component_type": ComponentType.LEAD_ACID_BATTERY, "months": 12})
        s.save()
    if not frappe.db.exists("FX Vehicle Registry", CHASSIS):
        start = add_days(nowdate(), -30)
        frappe.get_doc({"doctype": "FX Vehicle Registry", "chassis_no": CHASSIS, "customer_name": "HD Test Rider",
                        "mobile": "+919830000099", "konnect_invoice_no": "TINV-HD-1", "invoice_date": start,
                        "components": [{"component_type": ComponentType.LEAD_ACID_BATTERY, "serial_no": SERIAL,
                                        "warranty_start": start, "warranty_end": add_days(start, 364)}]}).insert()


def ticket(**kw):
    vehicle()
    return frappe.get_doc({"doctype": "HD Ticket", "subject": "HD test claim", "raised_by": "hd.test@example.com",
                           "description": "test", "ticket_type": "Warranty", "fx_claim_for": "Customer Claim",
                           "fx_vehicle": CHASSIS, "fx_component_serial": SERIAL, **kw}).insert(ignore_permissions=True)


EV = {"fx_customer_invoice": "/files/inv.pdf", "fx_component_photo": "/files/p.png"}


class TestHelpdeskTicket(IntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        helpdesk.setup()  # fields / ticket types exist on any site with helpdesk installed

    def test_konnect_match_and_warranty(self):
        t = ticket()
        self.assertEqual((t.fx_stage, t.fx_component_type, t.fx_warranty_status),
                         (Status.DRAFT, ComponentType.LEAD_ACID_BATTERY, "Active"))

    def test_evidence_gate(self):
        t = ticket()
        with self.assertRaises(frappe.ValidationError):
            helpdesk.set_stage(t.name, Status.OPEN)
        t2 = ticket(**EV)
        self.assertEqual(helpdesk.set_stage(t2.name, Status.OPEN), Status.OPEN)

    def test_skipping_stages_blocked(self):
        t = ticket(**EV)
        helpdesk.set_stage(t.name, Status.OPEN)
        with self.assertRaises(frappe.ValidationError):
            helpdesk.set_stage(t.name, Status.DISPATCHED)

    def test_helpdesk_status_changes_do_not_touch_stage(self):
        t = ticket(**EV)
        helpdesk.set_stage(t.name, Status.OPEN)
        for st in ("Replied", "Paused", "Open"):
            if frappe.db.exists("HD Ticket Status", st):
                t.reload()
                t.status = st  # what Helpdesk does on its own (agent reply, waiting, customer reply)
                t.save(ignore_permissions=True)
        self.assertEqual(frappe.db.get_value("HD Ticket", t.name, "fx_stage"), Status.OPEN)

    def test_override_reason_required(self):
        t = ticket(fx_component_serial="NOT-ON-VEHICLE", **EV)
        with self.assertRaises(frappe.ValidationError):
            helpdesk.set_stage(t.name, Status.OPEN)
        t.reload()
        t.fx_override_reason = "Physical tag differs"
        t.save(ignore_permissions=True)
        self.assertEqual(helpdesk.set_stage(t.name, Status.OPEN), Status.OPEN)

    def test_receive_material_routes_in_warranty_to_inspection(self):
        t = ticket(**EV)
        helpdesk.set_stage(t.name, Status.OPEN)
        self.assertEqual(helpdesk.receive_material(t.name), Status.UNDER_INSPECTION)

    def test_non_fleeto_ticket_is_stock_helpdesk(self):
        t = frappe.get_doc({"doctype": "HD Ticket", "subject": "General question", "raised_by": "hd.test@example.com",
                            "description": "x"}).insert(ignore_permissions=True)
        self.assertFalse(helpdesk.next_stages(t.name))

    def test_mir_cannot_replace_lead_acid(self):
        t = ticket(**EV)
        mir = frappe.get_doc({"doctype": "FX Material Inspection", "ticket": t.name,
                              "component_type": ComponentType.LEAD_ACID_BATTERY, "finding": "Irreparable",
                              "settlement_action": "Replace Unit", "replacement_serial": "X", "md_approved": 1,
                              "scrap_tag": "PCB-HAZ-1"})
        with self.assertRaises(frappe.ValidationError):
            mir.insert()

    def test_irreparable_lead_acid_needs_scrap_tag_and_defaults_to_credit(self):
        t = ticket(**EV)
        mir = frappe.get_doc({"doctype": "FX Material Inspection", "ticket": t.name,
                              "component_type": ComponentType.LEAD_ACID_BATTERY, "finding": "Irreparable",
                              "invoiced_value": 6500})
        with self.assertRaises(frappe.ValidationError):
            mir.insert()
        mir.scrap_tag = "PCB-HAZ-2026-8819"
        mir.insert()
        self.assertEqual((mir.settlement_action, mir.credit_note_amount, mir.original_invoice),
                         ("Issue Credit Note", 6500, "TINV-HD-1"))
