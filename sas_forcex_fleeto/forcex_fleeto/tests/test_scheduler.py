"""Phase 2 — technician calendar conflict prevention (Screen 3)."""

import datetime as dt
import unittest

from sas_forcex_fleeto.forcex_fleeto.services import scheduler as sch

D = dt.date(2026, 10, 3)


def booking(tech, start, end, ticket="T-1", status="Assigned", day=D):
    return sch.Booking(technician=tech, day=day, start=dt.time(*start), end=dt.time(*end), ticket=ticket, status=status)


class TestOverlap(unittest.TestCase):
    def test_touching_slots_do_not_overlap(self):
        a = booking("AMIT", (9, 0), (11, 0))
        b = booking("AMIT", (11, 0), (13, 0))
        self.assertFalse(sch.overlaps(a, b))

    def test_partial_overlap_detected(self):
        self.assertTrue(sch.overlaps(booking("AMIT", (9, 0), (11, 0)), booking("AMIT", (10, 30), (12, 0))))

    def test_different_technicians_never_conflict(self):
        self.assertFalse(sch.overlaps(booking("AMIT", (9, 0), (11, 0)), booking("BIPIN", (9, 0), (11, 0))))

    def test_different_days_never_conflict(self):
        other = booking("AMIT", (9, 0), (11, 0), day=D + dt.timedelta(days=1))
        self.assertFalse(sch.overlaps(booking("AMIT", (9, 0), (11, 0)), other))


class TestConflicts(unittest.TestCase):
    def setUp(self):
        self.existing = [
            booking("AMIT", (9, 0), (11, 0), "FLT-SRV-1079"),
            booking("AMIT", (11, 30), (13, 30), "FLT-SRV-1080"),
            booking("BIPIN", (9, 0), (11, 0), "TRANSIT", status="Blocked"),
            booking("AMIT", (14, 30), (16, 30), "OLD", status="Cancelled"),
        ]

    def test_booking_into_busy_slot_returns_conflict(self):
        new = booking("AMIT", (9, 0), (11, 0), "FLT-SRV-1082")
        self.assertEqual([c.ticket for c in sch.find_conflicts(new, self.existing)], ["FLT-SRV-1079"])

    def test_cancelled_bookings_free_the_slot(self):
        new = booking("AMIT", (14, 30), (16, 30), "FLT-SRV-1082")
        self.assertEqual(sch.find_conflicts(new, self.existing), [])

    def test_transit_block_counts_as_busy(self):
        new = booking("BIPIN", (10, 0), (10, 30), "FLT-SRV-1082")
        self.assertEqual(len(sch.find_conflicts(new, self.existing)), 1)

    def test_rebooking_the_same_ticket_ignores_itself(self):
        same = booking("AMIT", (9, 0), (11, 0), "FLT-SRV-1079")
        self.assertEqual(sch.find_conflicts(same, self.existing), [])

    def test_end_before_start_is_rejected(self):
        with self.assertRaises(ValueError):
            sch.validate_booking(booking("AMIT", (11, 0), (9, 0)))


class TestRoster(unittest.TestCase):
    def test_free_slots_for_roster_grid(self):
        existing = [booking("AMIT", (9, 0), (11, 0)), booking("AMIT", (11, 30), (13, 30))]
        free = sch.free_slots("AMIT", D, existing)
        self.assertEqual([s.label for s in free], ["02:30 PM - 04:30 PM", "05:00 PM - 07:00 PM"])


if __name__ == "__main__":
    unittest.main()
