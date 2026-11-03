"""Appointment status state machine (DM-05, IMP-15, GAP-22)."""

from enum import StrEnum
from typing import Literal

type Actor = Literal["patient", "staff", "admin", "system"]


class AppointmentStatus(StrEnum):
    BOOKED = "booked"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


_ALLOWED: dict[tuple[AppointmentStatus, AppointmentStatus], frozenset[str]] = {
    (AppointmentStatus.BOOKED, AppointmentStatus.CANCELLED): frozenset(
        {"patient", "staff", "admin", "system"}
    ),
    (AppointmentStatus.BOOKED, AppointmentStatus.COMPLETED): frozenset({"staff", "admin"}),
    (AppointmentStatus.BOOKED, AppointmentStatus.NO_SHOW): frozenset({"staff", "admin"}),
    # Attendance corrections are an admin-only fix for a mis-click (GAP-22).
    (AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW): frozenset({"admin"}),
    (AppointmentStatus.NO_SHOW, AppointmentStatus.COMPLETED): frozenset({"admin"}),
}


def can_transition(current: AppointmentStatus, new: AppointmentStatus, *, actor: Actor) -> bool:
    return actor in _ALLOWED.get((current, new), frozenset())
