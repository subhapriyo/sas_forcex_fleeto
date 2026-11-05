"""Phase 1 + 3 — warranty status, evidence gate, routing and settlement policy."""

import datetime as dt
import unittest

from sas_forcex_fleeto.forcex_fleeto.services import warranty_rules as wr
from sas_forcex_fleeto.forcex_fleeto.services.constants import (
    ClaimFor,
    WarrantyRoute,
)
from sas_forcex_fleeto.forcex_fleeto.services.constants import (
    ComponentType as C,
)
from sas_forcex_fleeto.forcex_fleeto.services.constants import (
    InspectionFinding as F,
)
from sas_forcex_fleeto.forcex_fleeto.services.constants import (
    SettlementAction as A,
)


class TestWarrantyStatus(unittest.TestCase):
    def test_expiry_is_start_plus_months_minus_one_day(self):
        # SOW Screen 1: sale 12-Jan-2026, 12 months -> expires 11-Jan-2027
        self.assertEqual(wr.warranty_end(dt.date(2026, 1, 12), 12), dt.date(2027, 1, 11))

    def test_month_end_start_dates_do_not_overflow(self):
        self.assertEqual(wr.warranty_end(dt.date(2026, 1, 31), 1), dt.date(2026, 2, 27))

    def test_active_on_last_day_and_expired_the_day_after(self):
        start = dt.date(2026, 1, 12)
        self.assertTrue(wr.evaluate(start, 12, on=dt.date(2027, 1, 11)).is_active)
        self.assertFalse(wr.evaluate(start, 12, on=dt.date(2027, 1, 12)).is_active)

    def test_km_limit_expires_warranty_early(self):
        res = wr.evaluate(dt.date(2026, 1, 12), 12, on=dt.date(2026, 3, 1), km_limit=20000, odometer_km=25000)
        self.assertFalse(res.is_active)
        self.assertIn("km", res.reason)

    def test_status_for_known_end_date(self):
        end = dt.date(2027, 1, 11)
        self.assertTrue(wr.status_for_end(end, on=end).is_active)
        self.assertFalse(wr.status_for_end(end, on=end, km_limit=100, odometer_km=101).is_active)

    def test_missing_start_date_is_unknown_not_active(self):
        res = wr.evaluate(None, 12, on=dt.date(2026, 3, 1))
        self.assertFalse(res.is_active)
        self.assertEqual(res.status, "Unknown")


class TestNonResetContinuity(unittest.TestCase):
    def test_replacement_part_inherits_original_end_date(self):
        original_end = dt.date(2027, 1, 11)
        self.assertEqual(wr.continued_warranty_end(original_end, replaced_on=dt.date(2026, 10, 3)), original_end)

    def test_replacement_after_expiry_is_refused(self):
        with self.assertRaises(wr.PolicyViolation):
            wr.continued_warranty_end(dt.date(2026, 1, 1), replaced_on=dt.date(2026, 10, 3))


class TestEvidenceGate(unittest.TestCase):
    def test_customer_claim_needs_customer_invoice_and_photo(self):
        missing = wr.missing_evidence(ClaimFor.CUSTOMER, {"customer_invoice": None, "component_photo": None})
        self.assertIn("customer_invoice", missing)
        self.assertIn("component_photo or odometer_photo", missing)

    def test_instore_dealer_needs_distributor_invoice(self):
        files = {"distributor_invoice": "/f/inv.pdf", "component_photo": "/f/p.png"}
        self.assertEqual(wr.missing_evidence(ClaimFor.INSTORE_DEALER, files), [])

    def test_instore_distributor_needs_tally_invoice(self):
        files = {"customer_invoice": "/f/x.pdf", "odometer_photo": "/f/o.jpg"}
        self.assertEqual(wr.missing_evidence(ClaimFor.INSTORE_DISTRIBUTOR, files), ["tally_invoice"])

    def test_video_is_optional(self):
        files = {"customer_invoice": "/f/x.pdf", "odometer_photo": "/f/o.jpg"}
        self.assertEqual(wr.missing_evidence(ClaimFor.CUSTOMER, files), [])


class TestRouting(unittest.TestCase):
    def test_component_routes(self):
        self.assertEqual(wr.route_for(C.LEAD_ACID_BATTERY), WarrantyRoute.LEAD_ACID)
        self.assertEqual(wr.route_for(C.LITHIUM_CHARGER), WarrantyRoute.SUPPLIER)
        self.assertEqual(wr.route_for(C.LEAD_CHARGER), WarrantyRoute.FACTORY)

    def test_unknown_component_raises(self):
        with self.assertRaises(ValueError):
            wr.route_for("Flux Capacitor")


class TestSettlementPolicy(unittest.TestCase):
    def test_lead_acid_replacement_is_always_forbidden(self):
        with self.assertRaises(wr.PolicyViolation) as ctx:
            wr.validate_settlement(C.LEAD_ACID_BATTERY, F.IRREPARABLE, A.REPLACE, md_approved=True)
        self.assertIn("MD", str(ctx.exception))

    def test_lead_acid_irreparable_goes_to_credit_note(self):
        self.assertEqual(wr.default_action(C.LEAD_ACID_BATTERY, F.IRREPARABLE), A.CREDIT_NOTE)
        wr.validate_settlement(C.LEAD_ACID_BATTERY, F.IRREPARABLE, A.CREDIT_NOTE)

    def test_lithium_cannot_be_repaired_in_house(self):
        with self.assertRaises(wr.PolicyViolation):
            wr.validate_settlement(C.LITHIUM_BATTERY, F.REPAIRABLE, A.REPAIR_RETURN)
        self.assertEqual(wr.default_action(C.LITHIUM_BATTERY, F.REPAIRABLE), A.SUPPLIER_RMA)

    def test_found_ok_is_same_return_for_everyone(self):
        for comp in (C.LEAD_ACID_BATTERY, C.LITHIUM_BATTERY, C.MOTOR):
            self.assertEqual(wr.default_action(comp, F.FOUND_OK), A.SAME_RETURN)

    def test_factory_replacement_needs_approval_above_threshold(self):
        with self.assertRaises(wr.PolicyViolation):
            wr.validate_settlement(C.MOTOR, F.IRREPARABLE, A.REPLACE, value=9000, replace_threshold=5000)
        wr.validate_settlement(C.MOTOR, F.IRREPARABLE, A.REPLACE, value=9000, replace_threshold=5000, md_approved=True)
        wr.validate_settlement(C.MOTOR, F.IRREPARABLE, A.REPLACE, value=3000, replace_threshold=5000)

    def test_reject_is_always_allowed(self):
        wr.validate_settlement(C.LITHIUM_BATTERY, F.FOUND_OK, A.REJECT)


if __name__ == "__main__":
    unittest.main()
