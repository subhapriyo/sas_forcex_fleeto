"""Phase 1 — Konnect invoice-report parsing (written before the parser)."""

import datetime as dt
import os
import tempfile
import unittest

from sas_forcex_fleeto.forcex_fleeto.services import konnect_parser as kp
from sas_forcex_fleeto.forcex_fleeto.services.constants import ComponentType
from sas_forcex_fleeto.forcex_fleeto.tests.fixtures.sample_konnect import HEADER, ROWS


class TestFieldHelpers(unittest.TestCase):
    def test_parse_date_accepts_d_m_yyyy_without_padding(self):
        self.assertEqual(kp.parse_date("9/10/2026"), dt.date(2026, 10, 9))
        self.assertEqual(kp.parse_date("24/10/2026"), dt.date(2026, 10, 24))

    def test_parse_date_accepts_excel_datetime_cells(self):
        self.assertEqual(kp.parse_date(dt.datetime(2026, 1, 12, 0, 0)), dt.date(2026, 1, 12))

    def test_parse_date_returns_none_for_garbage(self):
        self.assertIsNone(kp.parse_date("31/02/2026"))
        self.assertIsNone(kp.parse_date(""))
        self.assertIsNone(kp.parse_date(None))

    def test_normalize_mobile_to_e164(self):
        self.assertEqual(kp.normalize_mobile("8910000001"), "+918910000001")
        self.assertEqual(kp.normalize_mobile("+91 74300 00007"), "+917430000007")
        self.assertEqual(kp.normalize_mobile("09733000003"), "+919733000003")

    def test_normalize_mobile_rejects_non_indian_mobile(self):
        # Indian mobiles start with 6-9; 1234567890 is a classic test value.
        self.assertIsNone(kp.normalize_mobile("1234567890"))
        self.assertIsNone(kp.normalize_mobile("12345"))

    def test_chassis_check_flags_letter_o_and_bad_length(self):
        self.assertEqual(kp.chassis_issues("MD9ZX2WL025669435"), [])
        self.assertIn("contains I/O/Q", " ".join(kp.chassis_issues("MD9ZX2WLO25669553")))
        self.assertIn("17", " ".join(kp.chassis_issues("MD9EV2WL012345")))


class TestRowParsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = kp.parse_rows(HEADER, ROWS)
        cls.by_inv = {r.konnect_invoice_no: r for r in cls.result.rows}

    def test_blank_padding_rows_are_skipped(self):
        self.assertEqual(len(self.result.rows), 7)

    def test_clean_row_has_no_errors_and_all_components(self):
        row = self.by_inv["TINV0018"]
        self.assertEqual(row.errors, [])
        self.assertEqual(row.mobile, "+918910000001")
        self.assertEqual(row.invoice_date, dt.date(2026, 10, 24))
        batteries = [c for c in row.components if c.component_type == ComponentType.LEAD_ACID_BATTERY]
        self.assertEqual(len(batteries), 6)
        self.assertIn(("Motor", "FLEETO26MTR1234"), [(c.component_type, c.serial_no) for c in row.components])

    def test_led_battery_type_is_mapped_to_lead_acid(self):
        self.assertEqual(self.by_inv["TINV0018"].battery_chemistry, ComponentType.LEAD_ACID_BATTERY)

    def test_unknown_battery_type_is_a_warning_not_an_error(self):
        row = self.by_inv["TINV0006"]
        self.assertIsNone(row.battery_chemistry)
        self.assertTrue(any("Battery Type" in w for w in row.warnings))

    def test_whatsapp_falls_back_to_mobile(self):
        row = self.by_inv["TINV0009"]
        self.assertEqual(row.whatsapp, row.mobile)

    def test_junk_row_is_blocked(self):
        row = self.by_inv["TINV0006"]
        self.assertFalse(row.is_importable)
        self.assertTrue(any("mobile" in e.lower() for e in row.errors))

    def test_letter_o_in_chassis_is_only_a_warning(self):
        row = self.by_inv["TINV0017"]
        self.assertTrue(row.is_importable)
        self.assertTrue(any("I/O/Q" in w for w in row.warnings))

    def test_strict_vin_can_be_switched_off(self):
        res = kp.parse_rows(HEADER, ROWS, strict_vin=False)
        row = next(r for r in res.rows if r.konnect_invoice_no == "TINV0017")
        self.assertFalse(any("I/O/Q" in w for w in row.warnings))

    def test_gst_mismatch_is_flagged(self):
        self.assertTrue(any("GST" in w for w in self.by_inv["TINV0007"].warnings))
        self.assertFalse(any("GST" in w for w in self.by_inv["TINV0018"].warnings))

    def test_invoice_before_konnect_date_is_flagged(self):
        self.assertTrue(any("earlier than Konnect" in w for w in self.by_inv["TINV0016"].warnings))

    def test_idempotency_key_is_invoice_plus_chassis(self):
        self.assertEqual(self.by_inv["TINV0018"].sync_key, "TINV0018|MD9EV2WL012345")

    def test_summary_counts(self):
        self.assertEqual(self.result.summary()["blocked"], 1)
        self.assertEqual(self.result.summary()["importable"], 6)


class TestDuplicateDetection(unittest.TestCase):
    def test_same_serial_on_two_vehicles_blocks_the_second(self):
        rows = [ROWS[0], list(ROWS[0])]
        rows[1][HEADER.index("Konnect Invoice Number")] = "TINV9999"
        rows[1][HEADER.index("Chassis")] = "MD9EV2WL099999"
        res = kp.parse_rows(HEADER, rows)
        self.assertTrue(res.rows[0].is_importable)
        self.assertFalse(res.rows[1].is_importable)
        self.assertTrue(any("already used" in e for e in res.rows[1].errors))


class TestMissingColumns(unittest.TestCase):
    def test_missing_required_column_raises_early(self):
        bad_header = [h for h in HEADER if h != "Chassis"]
        with self.assertRaises(kp.KonnectFormatError):
            kp.parse_rows(bad_header, [])


class TestXlsxReader(unittest.TestCase):
    def test_reads_first_sheet(self):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(HEADER)
        for r in ROWS:
            ws.append(r)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "report.xlsx")
            wb.save(path)
            header, rows = kp.read_xlsx(path)
        self.assertEqual(header, HEADER)
        self.assertEqual(len(kp.parse_rows(header, rows).rows), 7)


if __name__ == "__main__":
    unittest.main()
