"""Emergency phrase matching (E5-S3-AC1): deterministic, normalised, word-bounded."""

import pytest

from clinic.agent.guardrails import is_emergency, normalise

PHRASES = ("chest pain", "can't breathe", "unconscious", "severe bleeding", "stroke")


@pytest.mark.parametrize(
    "message",
    [
        "I have chest pain",
        "CHEST-PAIN since morning!!",
        "I can't breathe",
        "i cant breathe",
        "I can\N{RIGHT SINGLE QUOTATION MARK}t breathe",
        "my father is unconscious",
        "there is severe   bleeding",
        "I think she had a stroke.",
    ],
)
def test_emergency_phrasings_match(message: str) -> None:
    assert is_emergency(message, PHRASES)


@pytest.mark.parametrize(
    "message",
    ["I want to book a check-up", "my chest x-ray report", "breathing exercises class", "keystroke", ""],
)
def test_ordinary_messages_do_not_match(message: str) -> None:
    assert not is_emergency(message, PHRASES)


def test_normalise_folds_case_punctuation_apostrophes_and_spaces() -> None:
    assert normalise("  Can\N{RIGHT SINGLE QUOTATION MARK}T   Breathe!! ") == "cant breathe"


def test_phrases_in_other_scripts_match() -> None:
    hindi = "सीने में दर्द"  # "chest pain" in Hindi
    assert is_emergency(f"मुझे {hindi} है!", [hindi])
    assert not is_emergency("नमस्ते", [hindi])
    assert normalise(hindi) == hindi
