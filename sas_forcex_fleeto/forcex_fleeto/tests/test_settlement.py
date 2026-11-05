"""Phase 3 — credit-note amounts and supplier/dealer pairing (Screens 5 & 6)."""

import unittest

from sas_forcex_fleeto.forcex_fleeto.services import settlement as st


class TestCreditNoteAmount(unittest.TestCase):
    def test_defaults_to_invoiced_value(self):
        self.assertEqual(st.credit_note_amount(invoiced_value=6500), 6500)

    def test_partial_credit_allowed(self):
        self.assertEqual(st.credit_note_amount(invoiced_value=6500, requested=4000), 4000)

    def test_cannot_exceed_invoiced_value(self):
        with self.assertRaises(st.SettlementError):
            st.credit_note_amount(invoiced_value=6500, requested=7000)

    def test_zero_or_negative_rejected(self):
        with self.assertRaises(st.SettlementError):
            st.credit_note_amount(invoiced_value=0)
        with self.assertRaises(st.SettlementError):
            st.credit_note_amount(invoiced_value=6500, requested=-1)

    def test_amounts_are_rounded_to_paise(self):
        self.assertEqual(st.credit_note_amount(invoiced_value=69999.994), 69999.99)


class TestSupplierPairing(unittest.TestCase):
    def test_pass_through_matches_supplier_credit(self):
        pair = st.pair_supplier_credit(supplier_credit=24000, dealer_invoiced_value=26000)
        self.assertEqual(pair.dealer_credit, 24000)
        self.assertEqual(pair.margin_absorbed, 0)

    def test_dealer_credit_is_capped_at_dealer_invoice(self):
        pair = st.pair_supplier_credit(supplier_credit=30000, dealer_invoiced_value=26000)
        self.assertEqual(pair.dealer_credit, 26000)

    def test_full_refund_policy_absorbs_the_gap(self):
        pair = st.pair_supplier_credit(supplier_credit=20000, dealer_invoiced_value=26000, policy="full_refund")
        self.assertEqual(pair.dealer_credit, 26000)
        self.assertEqual(pair.margin_absorbed, 6000)

    def test_supplier_credit_ref_required(self):
        with self.assertRaises(st.SettlementError):
            st.pair_supplier_credit(supplier_credit=24000, dealer_invoiced_value=26000, supplier_cn_ref="")


if __name__ == "__main__":
    unittest.main()
