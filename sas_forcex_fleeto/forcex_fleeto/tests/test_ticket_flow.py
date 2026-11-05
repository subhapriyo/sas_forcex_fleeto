"""Phase 2 — ticket state machine mirrors the FLEETO process-flow slide."""

import unittest
from itertools import pairwise

from sas_forcex_fleeto.forcex_fleeto.services import ticket_flow as tf
from sas_forcex_fleeto.forcex_fleeto.services.constants import Status as S
from sas_forcex_fleeto.forcex_fleeto.services.constants import TicketType as T


class TestServiceTrack(unittest.TestCase):
    def test_happy_path_remote_resolution(self):
        path = [S.DRAFT, S.OPEN, S.INVOICE_VERIFIED, S.TELE_TRIAGE, S.FEEDBACK_PENDING, S.CLOSED]
        for old, new in pairwise(path):
            tf.assert_transition(T.SERVICE, old, new)

    def test_field_visit_loop_until_resolved(self):
        tf.assert_transition(T.SERVICE, S.TELE_TRIAGE, S.TECH_ASSIGNED)
        tf.assert_transition(T.SERVICE, S.TECH_ASSIGNED, S.VISIT_DONE_UNRESOLVED)
        tf.assert_transition(T.SERVICE, S.VISIT_DONE_UNRESOLVED, S.TECH_ASSIGNED)  # re-assign
        tf.assert_transition(T.SERVICE, S.TECH_ASSIGNED, S.FEEDBACK_PENDING)

    def test_negative_feedback_reopens_triage(self):
        tf.assert_transition(T.SERVICE, S.FEEDBACK_PENDING, S.TELE_TRIAGE)

    def test_cannot_skip_invoice_verification(self):
        with self.assertRaises(tf.InvalidTransition):
            tf.assert_transition(T.SERVICE, S.OPEN, S.TELE_TRIAGE)

    def test_service_track_cannot_use_warranty_statuses(self):
        with self.assertRaises(tf.InvalidTransition):
            tf.assert_transition(T.SERVICE, S.OPEN, S.MATERIAL_RECEIVED)


class TestWarrantyTrack(unittest.TestCase):
    def test_lithium_supplier_repair_path(self):
        path = [S.DRAFT, S.OPEN, S.MATERIAL_RECEIVED, S.UNDER_INSPECTION, S.AT_SUPPLIER,
                S.RECEIVED_FROM_SUPPLIER, S.READY_TO_DISPATCH, S.DISPATCHED, S.DELIVERED,
                S.FEEDBACK_PENDING, S.CLOSED]
        for old, new in pairwise(path):
            tf.assert_transition(T.WARRANTY, old, new)

    def test_supplier_credit_path(self):
        tf.assert_transition(T.WARRANTY, S.AT_SUPPLIER, S.CREDIT_NOTE_PENDING)
        tf.assert_transition(T.WARRANTY, S.CREDIT_NOTE_PENDING, S.CLOSED)

    def test_out_of_warranty_goes_to_goodwill_or_rejection(self):
        tf.assert_transition(T.WARRANTY, S.MATERIAL_RECEIVED, S.GOODWILL_PENDING)
        tf.assert_transition(T.WARRANTY, S.GOODWILL_PENDING, S.UNDER_INSPECTION)
        tf.assert_transition(T.WARRANTY, S.GOODWILL_PENDING, S.REJECTED)

    def test_closed_is_terminal(self):
        with self.assertRaises(tf.InvalidTransition):
            tf.assert_transition(T.WARRANTY, S.CLOSED, S.OPEN)

    def test_same_status_is_a_noop(self):
        tf.assert_transition(T.WARRANTY, S.UNDER_INSPECTION, S.UNDER_INSPECTION)

    def test_next_statuses_drive_ui_buttons(self):
        self.assertEqual(set(tf.next_statuses(T.WARRANTY, S.DISPATCHED)), {S.DELIVERED})


class TestStatusForWarrantyCheck(unittest.TestCase):
    def test_material_receipt_decision(self):
        self.assertEqual(tf.after_material_receipt(is_in_warranty=True, wants_goodwill=False), S.UNDER_INSPECTION)
        self.assertEqual(tf.after_material_receipt(is_in_warranty=False, wants_goodwill=True), S.GOODWILL_PENDING)
        self.assertEqual(tf.after_material_receipt(is_in_warranty=False, wants_goodwill=False), S.REJECTED)


if __name__ == "__main__":
    unittest.main()
