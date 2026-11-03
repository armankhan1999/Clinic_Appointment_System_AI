"""Grounding check (E2-S2-AC4, AGT-09): a reply may only state times and fees that came from tool results.

Evidence is the tool results of the conversation plus code-authored notes (for example a booking
confirmation). The patient's own words and the model's earlier replies are not evidence.
"""

import json
import re
from collections.abc import Iterable, Sequence

from clinic.agent.llm import ModelText, ToolResults, TranscriptItem

_TWELVE_HOUR = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?\s*m\b", re.IGNORECASE)
_TWENTY_FOUR_HOUR = re.compile(r"(?<![\d:.])(\d{1,2}):(\d{2})(?!\d)(?!\s*[ap]\.?\s*m\b)", re.IGNORECASE)
_NUMBER = r"(\d{1,3}(?:,\d{2,3})+|\d+)"
_AMOUNT_BEFORE = re.compile(r"(?:\brs\b\.?|\binr\b|\N{INDIAN RUPEE SIGN})\s*" + _NUMBER, re.IGNORECASE)
_AMOUNT_AFTER = re.compile(_NUMBER + r"\s*(?:rupees?\b|rs\b|inr\b)", re.IGNORECASE)


def extract_times(text: str) -> set[int]:
    """Minutes after midnight for every clock time in the text (12-hour or 24-hour)."""
    minutes: set[int] = set()
    for hour_text, minute_text, meridiem in _TWELVE_HOUR.findall(text):
        hour, minute = int(hour_text), int(minute_text or 0)
        if 1 <= hour <= 12 and minute < 60:
            minutes.add((hour % 12 + (12 if meridiem.lower() == "p" else 0)) * 60 + minute)
    for hour_text, minute_text in _TWENTY_FOUR_HOUR.findall(text):
        hour, minute = int(hour_text), int(minute_text)
        if hour < 24 and minute < 60:
            minutes.add(hour * 60 + minute)
    return minutes


def extract_amounts(text: str) -> set[int]:
    found = _AMOUNT_BEFORE.findall(text) + _AMOUNT_AFTER.findall(text)
    return {int(amount.replace(",", "")) for amount in found}


def sources_from(transcript: Sequence[TranscriptItem]) -> list[str]:
    sources: list[str] = []
    for item in transcript:
        if isinstance(item, ToolResults):
            sources.extend(json.dumps(result.payload(), ensure_ascii=False) for _, result in item.results)
        elif isinstance(item, ModelText) and item.trusted:
            sources.append(item.text)
    return sources


def is_grounded(reply: str, sources: Iterable[str]) -> bool:
    evidence = "\n".join(sources)
    times_ok = extract_times(reply) <= extract_times(evidence)
    amounts_ok = extract_amounts(reply) <= extract_amounts(evidence)
    return times_ok and amounts_ok
