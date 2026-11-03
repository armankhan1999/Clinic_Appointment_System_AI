import pytest

from clinic.domain.appointments import Actor, AppointmentStatus, can_transition
from clinic.domain.results import ResultCode

B, C, D, N = (
    AppointmentStatus.BOOKED,
    AppointmentStatus.CANCELLED,
    AppointmentStatus.COMPLETED,
    AppointmentStatus.NO_SHOW,
)


@pytest.mark.parametrize("actor", ["patient", "staff", "admin", "system"])
def test_anyone_may_cancel_a_booking(actor: Actor) -> None:
    assert can_transition(B, C, actor=actor)


@pytest.mark.parametrize("target", [D, N])
def test_only_staff_mark_attendance(target: AppointmentStatus) -> None:
    assert can_transition(B, target, actor="staff")
    assert can_transition(B, target, actor="admin")
    assert not can_transition(B, target, actor="patient")
    assert not can_transition(B, target, actor="system")


@pytest.mark.parametrize("target", [B, D, N])
def test_cancelled_is_final(target: AppointmentStatus) -> None:
    for actor in ("patient", "staff", "admin", "system"):
        assert not can_transition(C, target, actor=actor)


def test_only_admin_corrects_attendance() -> None:
    assert can_transition(D, N, actor="admin")
    assert can_transition(N, D, actor="admin")
    assert not can_transition(D, N, actor="staff")
    assert not can_transition(N, D, actor="patient")


@pytest.mark.parametrize("status", list(AppointmentStatus))
def test_same_state_is_not_a_transition(status: AppointmentStatus) -> None:
    assert not can_transition(status, status, actor="admin")


def test_result_codes_cover_the_design_catalogue() -> None:
    expected = {
        "OK", "NO_MATCH", "NO_SLOTS", "INVALID_DATE", "AMBIGUOUS_DATE", "DOCTOR_NOT_WORKING",
        "NOT_FOUND", "PENDING_CONFIRMATION", "SLOT_UNAVAILABLE", "SLOT_TAKEN", "LIMIT_REACHED",
        "WITHIN_CUTOFF", "ALREADY_CANCELLED", "NONE", "CREATED", "ALREADY_OPEN", "INVALID_ARGS",
        "ERROR", "VALIDATION_ERROR", "FORBIDDEN", "UNAUTHENTICATED", "ACCOUNT_LOCKED", "RATE_LIMITED",
    }  # fmt: skip
    assert {code.value for code in ResultCode} == expected
