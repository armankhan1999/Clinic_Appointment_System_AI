"""Patient name and phone rules (E1-S2-AC3, DM-01)."""

import unicodedata

import phonenumbers

NAME_MIN, NAME_MAX = 2, 60
_NAME_PUNCTUATION = frozenset(" -'.\N{RIGHT SINGLE QUOTATION MARK}")
_PHONE_CHARS = frozenset("0123456789+-() ")


class InvalidNameError(ValueError):
    """The name breaks the registration rule: 2-60 characters, letters only, no digits."""


class InvalidPhoneError(ValueError):
    """The value is not a valid phone number."""


def normalise_name(raw: str) -> str:
    if any(unicodedata.category(ch).startswith("C") for ch in raw):
        raise InvalidNameError("control characters are not allowed")
    name = " ".join(raw.split())
    if not NAME_MIN <= len(name) <= NAME_MAX:
        raise InvalidNameError(f"must be {NAME_MIN}-{NAME_MAX} characters")
    if any(ch.isdigit() for ch in name):
        raise InvalidNameError("digits are not allowed")
    if not any(ch.isalpha() for ch in name):
        raise InvalidNameError("must contain letters")
    for ch in name:
        if not (ch.isalpha() or unicodedata.category(ch).startswith("M") or ch in _NAME_PUNCTUATION):
            raise InvalidNameError("only letters, spaces, hyphens, apostrophes and dots are allowed")
    return name


def first_name(full_name: str) -> str:
    return full_name.split(" ", 1)[0]


def normalise_phone(raw: str, default_region: str | None = None) -> str:
    """Return E.164. Telegram contacts arrive as international digits without a leading plus."""
    value = raw.strip()
    if not value or not set(value) <= _PHONE_CHARS:
        raise InvalidPhoneError("unexpected characters")
    if not value.startswith("+") and default_region is None:
        value = "+" + value
    try:
        parsed = phonenumbers.parse(value, None if value.startswith("+") else default_region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhoneError("not a phone number") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneError("not a valid phone number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
