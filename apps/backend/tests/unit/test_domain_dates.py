"""Deterministic date phrases (E2-S5, GAP-15, GAP-36). Today is Wednesday 9 January 2030 unless stated."""

from datetime import date

import pytest

from clinic.domain.dates import Ambiguous, Resolved, Unrecognised, resolve_date

TODAY = date(2030, 1, 9)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("today", date(2030, 1, 9)),
        ("Tomorrow", date(2030, 1, 10)),
        ("day after tomorrow", date(2030, 1, 11)),
        ("the day after tomorrow", date(2030, 1, 11)),
        ("friday", date(2030, 1, 11)),
        ("this Friday", date(2030, 1, 11)),
        ("wednesday", date(2030, 1, 9)),
        ("next wednesday", date(2030, 1, 16)),
        ("next friday", date(2030, 1, 11)),
        ("next Monday", date(2030, 1, 14)),
        ("2030-01-20", date(2030, 1, 20)),
        ("20 January", date(2030, 1, 20)),
        ("January 20", date(2030, 1, 20)),
        ("20th january", date(2030, 1, 20)),
        ("20 Jan 2031", date(2031, 1, 20)),
        ("the 15th", date(2030, 1, 15)),
        ("15", date(2030, 1, 15)),
        ("the 5th", date(2030, 2, 5)),
        ("  Tomorrow. ", date(2030, 1, 10)),
    ],
)
def test_phrases_resolve_from_today(phrase: str, expected: date) -> None:
    assert resolve_date(phrase, TODAY) == Resolved(expected)


def test_month_and_day_already_past_this_year_means_next_year() -> None:
    assert resolve_date("20 January", date(2030, 2, 1)) == Resolved(date(2031, 1, 20))


@pytest.mark.parametrize("phrase", ["the 5th", "30th", "the 28th"])
def test_bare_day_in_the_last_week_of_a_month_is_ambiguous(phrase: str) -> None:
    assert isinstance(resolve_date(phrase, date(2030, 1, 27)), Ambiguous)


@pytest.mark.parametrize(
    "phrase", ["", "next blursday", "31 February", "2030-02-30", "the 32nd", "soon", "13/01/2030"]
)
def test_unrecognised_phrases(phrase: str) -> None:
    assert resolve_date(phrase, TODAY) == Unrecognised()
