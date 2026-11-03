import pytest

from clinic.domain.patients import (
    InvalidNameError,
    InvalidPhoneError,
    first_name,
    normalise_name,
    normalise_phone,
)


@pytest.mark.parametrize(
    "raw", ["A", "", "   ", "x" * 61, "R2D2", "Asha 3", "---", "Asha\x00Rao", "Asha\nRao"]
)
def test_invalid_names_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidNameError):
        normalise_name(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  asha   rao ", "asha rao"),
        ("Anne-Marie O'Neil", "Anne-Marie O'Neil"),
        ("Jo", "Jo"),
        ("Priya D\N{RIGHT SINGLE QUOTATION MARK}Souza", "Priya D\N{RIGHT SINGLE QUOTATION MARK}Souza"),
        ("a" * 60, "a" * 60),
        ("Zoë Ångström", "Zoë Ångström"),
    ],
)
def test_valid_names_are_normalised(raw: str, expected: str) -> None:
    assert normalise_name(raw) == expected


def test_length_is_checked_after_whitespace_is_collapsed() -> None:
    assert normalise_name("  Jo  ") == "Jo"
    with pytest.raises(InvalidNameError):
        normalise_name("  J  ")


def test_first_name() -> None:
    assert first_name("Asha Rao") == "Asha"
    assert first_name("Jo") == "Jo"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("919876543210", "+919876543210"),
        ("+91 98765 43210", "+919876543210"),
        ("+1 202-555-0123", "+12025550123"),
    ],
)
def test_telegram_and_international_phones_become_e164(raw: str, expected: str) -> None:
    assert normalise_phone(raw) == expected


def test_national_number_uses_default_region() -> None:
    assert normalise_phone("098765 43210", default_region="IN") == "+919876543210"


@pytest.mark.parametrize("raw", ["12", "phone", "", "+0000", "+91 12345"])
def test_invalid_phones_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidPhoneError):
        normalise_phone(raw)
