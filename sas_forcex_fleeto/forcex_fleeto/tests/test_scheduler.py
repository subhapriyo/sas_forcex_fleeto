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

    def test_editing_a_booking_does_not_clash_with_itself(self):
        saved = sch.Booking("AMIT", D, dt.time(9), dt.time(11), "FLT-SRV-1079", name="BK-1")
        moved = sch.Booking("AMIT", D, dt.time(9, 30), dt.time(11, 30), "FLT-SRV-1079", name="BK-1")
        self.assertEqual(sch.find_conflicts(moved, [saved]), [])

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


class TestSameTicketTwice(unittest.TestCase):
    """B3: a technician cannot be in two places at once, even for the same ticket."""

    def test_second_overlapping_booking_for_same_ticket_conflicts(self):
        first = booking("AMIT", (9, 0), (11, 0), ticket="0004")
        again = booking("AMIT", (10, 0), (12, 0), ticket="0004")
        self.assertEqual(sch.find_conflicts(again, [first]), [first])


scheduler, Booking = sch, sch.Booking


def t(hour, minute=0):
    return dt.time(hour, minute)


class TestDayBoard(unittest.TestCase):
    """Technician Board: one row per technician, one cell per roster slot."""

    def setUp(self):
        self.bookings = [
            Booking("T1", D, t(9), t(11), "0004"),                       # fills slot 1
            Booking("T1", D, t(12), t(15), "0005", "In Progress"),       # spans slots 2 and 3
            Booking("T2", D, t(9), t(11), "0006", "Cancelled"),          # frees the slot
            Booking("T2", D, t(17), t(18), "", "Blocked"),               # leave / transit
        ]

    def test_every_technician_gets_one_cell_per_slot(self):
        board = scheduler.day_board(["T1", "T2", "T3"], D, self.bookings)
        self.assertEqual(list(board), ["T1", "T2", "T3"])
        self.assertTrue(all(len(cells) == len(scheduler.DEFAULT_SLOTS) for cells in board.values()))

    def test_booking_shows_in_every_slot_it_overlaps(self):
        cells = scheduler.day_board(["T1"], D, self.bookings)["T1"]
        self.assertEqual([[b.ticket for b in c.bookings] for c in cells], [["0004"], ["0005"], ["0005"], []])
        self.assertEqual([c.free for c in cells], [False, False, False, True])

    def test_cancelled_booking_is_listed_but_slot_stays_free(self):
        first = scheduler.day_board(["T2"], D, self.bookings)["T2"][0]
        self.assertTrue(first.free)
        self.assertEqual([b.status for b in first.bookings], ["Cancelled"])

    def test_blocked_time_makes_slot_busy(self):
        last = scheduler.day_board(["T2"], D, self.bookings)["T2"][3]
        self.assertFalse(last.free)

    def test_other_days_are_ignored(self):
        other = [Booking("T1", D + dt.timedelta(days=1), t(9), t(11), "0099")]
        self.assertTrue(all(c.free for c in scheduler.day_board(["T1"], D, other)["T1"]))
