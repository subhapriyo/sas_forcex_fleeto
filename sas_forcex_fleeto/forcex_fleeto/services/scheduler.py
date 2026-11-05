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
    technician: str
    day: dt.date
    start: dt.time
    end: dt.time
    ticket: str = ""
    status: str = "Assigned"


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
    validate_booking(new)
    return [
        e for e in existing
        if e.status in BUSY_STATUSES
        and not (new.ticket and e.ticket == new.ticket)  # editing own booking
        and overlaps(new, e)
    ]


def free_slots(technician: str, day: dt.date, existing: list[Booking],
               slots: list[Slot] = DEFAULT_SLOTS) -> list[Slot]:
    """Slots still open for one technician — feeds the green 'AVAILABLE' cells."""
    probe = lambda s: Booking(technician, day, s.start, s.end)  # noqa: E731
    return [s for s in slots if not find_conflicts(probe(s), existing)]
