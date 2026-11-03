"""Grounding check (E2-S2-AC4, AGT-09): a reply may only state times and fees that came from tool results.

Evidence is the code-authored data of tool results in the conversation plus code-authored notes (for
example a booking confirmation). Not evidence: the patient's words, the model's earlier replies, and
INVALID_ARGS / ERROR results, which can echo text the model itself supplied.

Residual risk: times written fully in words ("half past ten") are not recognised; the evaluation suite
measures how often the model writes them.
"""

import json
import re
from collections.abc import Iterable, Sequence

from clinic.agent.llm import ModelText, ToolResults, TranscriptItem
from clinic.domain.results import ResultCode

UNTRUSTED_RESULTS = frozenset({ResultCode.INVALID_ARGS, ResultCode.ERROR})

_TWELVE_HOUR = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?\s*m\b", re.IGNORECASE)
_TWENTY_FOUR_HOUR = re.compile(r"(?<![\d:.])(\d{1,2}):(\d{2})(?!\d)(?!\s*[ap]\.?\s*m\b)", re.IGNORECASE)
_OCLOCK = re.compile(r"\b(\d{1,2})\s*o\s*['\N{RIGHT SINGLE QUOTATION MARK}]?\s*clock\b", re.IGNORECASE)
_NAMED = {"noon": 12 * 60, "midday": 12 * 60, "midnight": 0}
_NAMED_TIME = re.compile(r"\b(" + "|".join(_NAMED) + r")\b", re.IGNORECASE)
_NUMBER = r"(\d{1,3}(?:,\d{2,3})+|\d+)"
# No word boundary after the marker, so compact forms such as "Rs500" and "INR700" are caught too.
_AMOUNT_BEFORE = re.compile(r"(?:\brs\.?|\binr|\N{INDIAN RUPEE SIGN})\s*" + _NUMBER, re.IGNORECASE)
_AMOUNT_AFTER = re.compile(_NUMBER + r"\s*(?:/-|rupees?\b|rs\b\.?|inr\b)", re.IGNORECASE)


def extract_times(text: str) -> set[int]:
    """Minutes after midnight for every unambiguous clock time in the text (12-hour, 24-hour, noon)."""
    minutes: set[int] = set()
    for hour_text, minute_text, meridiem in _TWELVE_HOUR.findall(text):
        hour, minute = int(hour_text), int(minute_text or 0)
        if 1 <= hour <= 12 and minute < 60:
            minutes.add((hour % 12 + (12 if meridiem.lower() == "p" else 0)) * 60 + minute)
    for hour_text, minute_text in _TWENTY_FOUR_HOUR.findall(text):
        hour, minute = int(hour_text), int(minute_text)
        if hour < 24 and minute < 60:
            minutes.add(hour * 60 + minute)
    minutes.update(_NAMED[name.lower()] for name in _NAMED_TIME.findall(text))
    return minutes


def _oclock_candidates(text: str) -> list[set[int]]:
    """Candidates for "10 o'clock": 10:00 AM or PM; either one in the evidence is enough."""
    return [{(int(h) % 12) * 60, (int(h) % 12 + 12) * 60} for h in _OCLOCK.findall(text) if 1 <= int(h) <= 12]


def extract_amounts(text: str) -> set[int]:
    found = _AMOUNT_BEFORE.findall(text) + _AMOUNT_AFTER.findall(text)
    return {int(amount.replace(",", "")) for amount in found}


def sources_from(transcript: Sequence[TranscriptItem]) -> list[str]:
    sources: list[str] = []
    for item in transcript:
        if isinstance(item, ToolResults):
            sources.extend(
                json.dumps(result.payload(), ensure_ascii=False)
                for _, result in item.results
                if result.code not in UNTRUSTED_RESULTS
            )
        elif isinstance(item, ModelText) and item.trusted:
            sources.append(item.text)
    return sources


def is_grounded(reply: str, sources: Iterable[str]) -> bool:
    evidence = "\n".join(sources)
    evidence_times = extract_times(evidence)
    times_ok = extract_times(reply) <= evidence_times
    oclock_ok = all(candidates & evidence_times for candidates in _oclock_candidates(reply))
    amounts_ok = extract_amounts(reply) <= extract_amounts(evidence)
    return times_ok and oclock_ok and amounts_ok
