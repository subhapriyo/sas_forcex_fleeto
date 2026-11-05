"""FLEETO tickets moved to ForceX Helpdesk (HD Ticket). Remove the retired DocType.

Runs post model sync, so every link (bookings, job cards, MIR, RMA, credit notes)
already points at HD Ticket. Existing FX Service Ticket rows are dev/demo data only
(no production site ever had this DocType), so they are deleted with it.
"""

import frappe


def execute():
    for dt in ("FX Service Ticket",):
        if frappe.db.exists("DocType", dt):
            frappe.delete_doc("DocType", dt, force=True, ignore_permissions=True)
        # Frappe's orphan cleanup removes the DocType record but leaves its table behind.
        frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{dt}`")
