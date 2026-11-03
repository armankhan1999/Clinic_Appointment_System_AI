"""Deterministic guardrails that run before any LLM call (D-10, E5-S3).

A keyword list misses some phrasings; an LLM-based second check is future scope (E5-S3 note).
"""

import unicodedata
from collections.abc import Iterable

_APOSTROPHES = frozenset("'`\N{RIGHT SINGLE QUOTATION MARK}\N{LEFT SINGLE QUOTATION MARK}")
# Punctuation, symbols, separators and control characters split words. Letters and combining marks in
# any script are kept, so phrases configured in Hindi or other languages still match.
_SEPARATOR_CATEGORIES = ("P", "S", "Z", "C")


def normalise(text: str) -> str:
    """Case-folded, apostrophes removed ("can't" == "cant"), other punctuation and spacing → one space."""
    characters = []
    for character in text.casefold():
        if character in _APOSTROPHES:
            continue
        separator = unicodedata.category(character).startswith(_SEPARATOR_CATEGORIES)
        characters.append(" " if separator else character)
    return " ".join("".join(characters).split())


def is_emergency(text: str, phrases: Iterable[str]) -> bool:
    """True when any configured phrase appears as whole words in the message (E5-S3-AC1)."""
    padded = f" {normalise(text)} "
    return any(f" {phrase} " in padded for phrase in map(normalise, phrases) if phrase)
