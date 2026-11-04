"""The E2E fixtures' own rules: free-time search and the clean-up marker guard."""

from datetime import UTC, datetime, timedelta

import pytest

from clinic.db.models import Patient
from tests.e2e_support.cleanup import is_e2e_patient
from tests.e2e_support.common import FixtureError, first_free_start, random_letters

QUARTER = timedelta(minutes=15)
NINE = datetime(2030, 1, 7, 9, 0, tzinfo=UTC)


def test_first_free_start_keeps_a_free_time() -> None:
    assert first_free_start(NINE, QUARTER, [], QUARTER) == NINE


def test_first_free_start_moves_past_booked_ranges_in_the_given_direction() -> None:
    booked = [(NINE, NINE + QUARTER), (NINE + QUARTER, NINE + 2 * QUARTER)]
    assert first_free_start(NINE, QUARTER, booked, QUARTER) == NINE + 2 * QUARTER
    assert first_free_start(NINE + QUARTER, QUARTER, booked, -QUARTER) == NINE - QUARTER


def test_first_free_start_treats_touching_ranges_as_free() -> None:
    assert (
        first_free_start(
            NINE, QUARTER, [(NINE - QUARTER, NINE), (NINE + QUARTER, NINE + QUARTER * 2)], QUARTER
        )
        == NINE
    )


def test_first_free_start_gives_up_instead_of_looping() -> None:
    with pytest.raises(FixtureError):
        first_free_start(NINE, QUARTER, [(NINE - timedelta(days=5), NINE + timedelta(days=5))], QUARTER)


def test_random_letters_has_no_digits() -> None:
    name = random_letters(12)
    assert len(name) == 12
    assert name.isalpha()


@pytest.mark.parametrize(
    ("full_name", "registered_via", "telegram_user_id", "expected"),
    [
        ("Playwright Walkin Abcdef", "staff", None, True),
        ("Asha Verma", "staff", None, False),
        ("Playwright Walkin Abcdef", "bot", None, False),
        ("Playwright Walkin Abcdef", "staff", 12345, False),
        (None, "staff", None, False),
    ],
)
def test_clean_up_only_accepts_marked_staff_registered_patients(
    full_name: str | None, registered_via: str, telegram_user_id: int | None, expected: bool
) -> None:
    patient = Patient(full_name=full_name, registered_via=registered_via, telegram_user_id=telegram_user_id)
    assert is_e2e_patient(patient) is expected
