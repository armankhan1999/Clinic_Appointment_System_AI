"""Deterministic guardrails that run before any LLM call (D-10, E5-S3).

A keyword list misses some phrasings; an LLM-based second check is future scope (E5-S3 note).
"""

import re
from collections.abc import Iterable

_APOSTROPHES = re.compile("['\N{RIGHT SINGLE QUOTATION MARK}\N{LEFT SINGLE QUOTATION MARK}`]")
_NON_WORD = re.compile(r"[^0-9a-z]+")


def normalise(text: str) -> str:
    """Lower case, apostrophes removed ("can't" == "cant"), other non-alphanumerics become one space."""
    folded = _APOSTROPHES.sub("", text.casefold())
    return _NON_WORD.sub(" ", folded).strip()


def is_emergency(text: str, phrases: Iterable[str]) -> bool:
    """True when any configured phrase appears as whole words in the message (E5-S3-AC1)."""
    padded = f" {normalise(text)} "
    return any(f" {phrase} " in padded for phrase in map(normalise, phrases) if phrase)
