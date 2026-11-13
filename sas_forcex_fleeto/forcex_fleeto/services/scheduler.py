"""
Field-technician calendar (Screen 3) — pure overlap maths.

The DB-level guarantee against double booking lives in the DocType
controller (row lock); this module answers "would this clash?" so the
calendar UI and the server share one definition of "busy".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

# Statuses that occupy the technician. "Blocked" = transit / leave / training.
BUSY_STATUSES = {"Assigned", "In Progress", "Blocked"}


@dataclass
class Booking:
    """One booking, as the overlap rules see it."""

    technician: str
    day: dt.date
    start: dt.time
    end: dt.time
    ticket: str = ""
    status: str = "Assigned"
    name: str = ""   # the booking record's name; identifies "this same booking" when it is edited


@dataclass(frozen=True)
class Slot:
    start: dt.time
    end: dt.time

    @property
    def label(self) -> str:
        return f"{self.start:%I:%M %p} - {self.end:%I:%M %p}"


# Standard roster columns from the SOW prototype. Override in FX Service Settings.
DEFAULT_SLOTS = [
    Slot(dt.time(9, 0), dt.time(11, 0)),
    Slot(dt.time(11, 30), dt.time(13, 30)),
    Slot(dt.time(14, 30), dt.time(16, 30)),
    Slot(dt.time(17, 0), dt.time(19, 0)),
]


def validate_booking(b: Booking) -> None:
    if b.end <= b.start:
        raise ValueError(f"Booking end {b.end} must be after start {b.start}")


def overlaps(a: Booking, b: Booking) -> bool:
    """Half-open intervals: 09-11 and 11-13 do NOT overlap."""
    return a.technician == b.technician and a.day == b.day and a.start < b.end and b.start < a.end


def find_conflicts(new: Booking, existing: list[Booking]) -> list[Booking]:
    """Busy bookings that overlap `new`. The booking being edited (same name) never clashes with itself."""
    validate_booking(new)
    return [
        e for e in existing
        if e.status in BUSY_STATUSES
        and not (new.name and e.name == new.name)  # the booking being edited is not its own clash
        and overlaps(new, e)
    ]


def free_slots(technician: str, day: dt.date, existing: list[Booking],
               slots: list[Slot] = DEFAULT_SLOTS) -> list[Slot]:
    """Slots still open for one technician — feeds the green 'AVAILABLE' cells."""
    probe = lambda s: Booking(technician, day, s.start, s.end)  # noqa: E731
    return [s for s in slots if not find_conflicts(probe(s), existing)]


@dataclass
class Cell:
    """One roster slot for one technician on the Technician Board."""

    slot: Slot
    bookings: list[Booking]   # every booking touching the slot, cancelled/done included

    @property
    def free(self) -> bool:
        return not any(b.status in BUSY_STATUSES for b in self.bookings)


def day_board(technicians: list[str], day: dt.date, bookings: list[Booking],
              slots: list[Slot] = DEFAULT_SLOTS) -> dict[str, list[Cell]]:
    """{technician: [Cell per slot]} for one day, technicians in the order given.

    A booking appears in every slot it overlaps, so a 12:00-15:00 job shows in
    both the 11:30 and the 14:30 column; the same overlap rule as the conflict check.
    """
    board = {}
    for tech in technicians:
        mine = [b for b in bookings if b.technician == tech and b.day == day]
        board[tech] = [Cell(s, [b for b in mine if b.start < s.end and s.start < b.end]) for s in slots]
    return board
