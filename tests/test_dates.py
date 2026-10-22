"""Tests for dates.py (TEST_PLAN section 3, IDs D01-D65)."""

from __future__ import annotations

import datetime as real_datetime
import re
from datetime import date
from pathlib import Path

import pytest

from actiontrack import dates
from actiontrack.dates import DueResult, is_overdue, parse_header_date, resolve_due

NOTES = Path(__file__).resolve().parent.parent / "notes"


def _in_note(name: str, text: str) -> None:
    """Anchor a case to the real note it comes from (read-only)."""
    assert text in (NOTES / name).read_text(encoding="utf-8"), f"{text!r} not in {name}"


def d(s: str) -> date:
    return date.fromisoformat(s)


# --- 3.1 resolution table ------------------------------------------------------------------

RESOLUTION = [
    ("D01", "by Friday", "2026-09-01", "2026-09-04", "2026-09-01-quote-portal-kickoff.md"),
    ("D02", "by Friday", "2026-09-18", "2026-09-25", None),
    ("D03", "by Monday", "2026-09-03", "2026-09-07", "2026-09-03-billing-migration-sync.md"),
    ("D04", "by Mon", "2026-09-18", "2026-09-21", "2026-09-18-design-review.md"),
    ("D05", "by Wednesday", "2026-09-18", "2026-09-23", "2026-09-18-design-review.md"),
    ("D06", "by tomorrow", "2026-10-06", "2026-10-07", "2026-10-06-quote-portal-weekly.md"),
    ("D07", "by EOD", "2026-10-08", "2026-10-08", "2026-10-08-billing-go-no-go.md"),
    ("D08", "by EOD tomorrow", "2026-09-21", "2026-09-22", "2026-09-21-incident-review.md"),
    ("D09", "by next Tuesday", "2026-10-05", "2026-10-13", "2026-10-05-onboarding-retro.md"),
    ("D10", "by next Tuesday", "2026-09-18", "2026-09-22", None),
    (
        "D11",
        "by end of next week",
        "2026-09-03",
        "2026-09-11",
        "2026-09-03-billing-migration-sync.md",
    ),
    ("D12", "by end of month", "2026-09-14", "2026-09-30", "2026-09-14-onboarding-flow-design.md"),
    ("D13", "by mid-October", "2026-09-30", "2026-10-15", "2026-09-30-q4-offsite.md"),
    ("D14", "by 2026-10-09", "2026-10-02", "2026-10-09", "2026-10-02-finance-sync.md"),
    ("D15", "by 10 Sep", "2026-09-03", "2026-09-10", "2026-09-03-billing-migration-sync.md"),
    ("D16", "by Wed 16 Sep", "2026-09-14", "2026-09-16", "2026-09-14-onboarding-flow-design.md"),
    ("D17", "by Oct 3rd", "2026-09-30", "2026-10-03", "2026-09-30-q4-offsite.md"),
    ("D18", "results due 15 October", "2026-09-30", "2026-10-15", "2026-09-30-q4-offsite.md"),
    ("D19", "by 7 Jan", "2026-12-20", "2027-01-07", None),
    (
        "D20",
        "circulate the offsite summary tomorrow",
        "2026-09-30",
        "2026-10-01",
        None,
    ),
]


@pytest.mark.parametrize(
    ("case", "phrase", "meeting", "expected", "note"),
    RESOLUTION,
    ids=[r[0] for r in RESOLUTION],
)
def test_resolution_table(case, phrase, meeting, expected, note):
    if note and case != "D20":
        _in_note(note, phrase)
    result = resolve_due(phrase, d(meeting))
    assert isinstance(result, DueResult)
    assert result.due == d(expected)
    assert result.raw == phrase
    assert result.warning is None


def test_d20_real_note_has_trailing_tomorrow():
    text = (NOTES / "2026-09-30-q4-offsite.md").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("ACTION:") and "tomorrow" in ln)
    assert resolve_due(line, d("2026-09-30")).due == d("2026-10-01")


def test_due_result_is_frozen():
    result = resolve_due("by Friday", d("2026-09-01"))
    with pytest.raises(AttributeError):
        result.due = None  # type: ignore[misc]


# --- extra rule coverage -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("phrase", "meeting", "expected"),
    [
        ("by today", "2026-09-10", "2026-09-10"),
        ("by EOD", "2026-10-10", "2026-10-10"),
        ("by end of the month", "2026-02-10", "2026-02-28"),
        ("by end of month", "2026-12-05", "2026-12-31"),
        ("by mid-September", "2026-09-30", "2026-09-15"),  # same month: no roll
        ("by mid-August", "2026-09-30", "2027-08-15"),
        ("by mid-October", "2026-10-20", "2026-10-15"),
        ("by Mid October", "2026-09-01", "2026-10-15"),
        ("by 10 sep", "2026-09-03", "2026-09-10"),
        ("by 1 Sep", "2026-09-03", "2027-09-01"),
        ("by 3 Sep", "2026-09-03", "2026-09-03"),
        ("by 7 October 2027", "2026-09-03", "2027-10-07"),
        ("by September 22nd", "2026-09-03", "2026-09-22"),
        ("due next Monday", "2026-09-06", "2026-09-07"),
        ("by next Monday", "2026-09-07", "2026-09-14"),
        ("by next Sunday", "2026-09-07", "2026-09-20"),
        ("by Thu", "2026-09-03", "2026-09-10"),
        ("before Friday", "2026-09-01", "2026-09-04"),
        ("by FRIDAY", "2026-09-01", "2026-09-04"),
        ("by end of next week", "2026-09-06", "2026-09-11"),
        ("by 29 Feb", "2027-01-10", "2028-02-29"),
    ],
)
def test_more_phrases(phrase, meeting, expected):
    assert resolve_due(phrase, d(meeting)).due == d(expected)


def test_long_action_line_in_context():
    line = "Sam to cut cloud costs by 10% - proposal by 2026-10-09"
    assert resolve_due(line, d("2026-10-02")).due == d("2026-10-09")


# --- 3.2 non-deadlines and unresolvable ---------------------------------------------------


@pytest.mark.parametrize(
    ("case", "phrase", "meeting"),
    [
        ("D30", "before cutover", "2026-09-03"),
        ("D31", "freeze invoice edits from 9 Oct", "2026-09-29"),
        ("D32", "schedule cutover for Saturday 10 Oct", "2026-09-29"),
        ("D33", "demo the portal to Acme on 2026-10-14", "2026-10-06"),
        ("D36", "by 10%", "2026-10-02"),
        ("D37", "by sometime soon", "2026-10-02"),
        ("D40", "by 31 Feb", "2026-10-02"),
        ("extra", "before the next review", "2026-09-18"),
        ("extra", "by 45 Sep", "2026-09-18"),
        ("extra", "by 2026-13-45", "2026-09-18"),
        ("extra", "by 2026-02-30", "2026-09-18"),
        ("extra", "by", "2026-09-18"),
        ("extra", "by Friyay", "2026-09-18"),
        ("extra", "from 9 Oct", "2026-09-18"),
        ("extra", "on Friday", "2026-09-18"),
        ("extra", "for Friday", "2026-09-18"),
    ],
)
def test_non_deadlines(case, phrase, meeting):
    result = resolve_due(phrase, d(meeting))
    assert result.due is None
    assert result.raw == phrase


def test_d30_d31_real_notes_contain_the_phrases():
    _in_note("2026-09-03-billing-migration-sync.md", "before cutover")
    _in_note("2026-09-29-billing-cutover-planning.md", "from 9 Oct")
    _in_note("2026-09-29-billing-cutover-planning.md", "Saturday 10 Oct")
    _in_note("2026-10-06-quote-portal-weekly.md", "on 2026-10-14")
    _in_note("2026-10-02-finance-sync.md", "by 10%")


def test_d34_undated_note_never_uses_today():
    result = resolve_due("by Friday", None)
    assert result.due is None
    assert result.raw == "by Friday"
    _in_note("untitled.md", "by Friday")


@pytest.mark.parametrize("phrase", ["by tomorrow", "by EOD", "by next Tuesday", "by 10 Sep"])
def test_relative_phrases_unresolved_without_meeting_date(phrase):
    assert resolve_due(phrase, None).due is None


def test_d35_absolute_iso_resolves_without_meeting_date():
    assert resolve_due("by 2026-10-09", None).due == d("2026-10-09")


def test_d38_last_deadline_wins():
    phrase = "by Friday ... by 2026-10-09"
    assert resolve_due(phrase, d("2026-10-02")).due == d("2026-10-09")
    assert resolve_due("by 2026-10-09 then by Friday", d("2026-10-02")).due == d("2026-10-09")
    # Position decides, not the kind of phrase.
    assert resolve_due("by 2026-10-30, by Friday", d("2026-10-02")).due == d("2026-10-09")


def test_d39_weekday_mismatch_warns_and_date_wins():
    result = resolve_due("by Wed 17 Sep", d("2026-09-14"))
    assert result.due == d("2026-09-17")
    assert result.warning
    assert "Wed" in result.warning or "Wednesday" in result.warning


def test_weekday_match_has_no_warning():
    assert resolve_due("by Wed 16 Sep", d("2026-09-14")).warning is None


@pytest.mark.parametrize("phrase", [None, "", "   "])
def test_d41_empty_and_none(phrase):
    result = resolve_due(phrase, d("2026-09-01"))
    assert result.due is None
    assert result.warning is None


def test_d41_empty_with_no_meeting_date():
    assert resolve_due(None, None).due is None


def test_d42_today_is_never_used(monkeypatch):
    """Spy on every clock source; the result must not change and nothing may be read."""
    calls: list[str] = []
    results = []

    class SpyDate(real_datetime.date):
        @classmethod
        def today(cls):
            calls.append("date.today")
            raise AssertionError("date.today() used")

    class SpyDatetime(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            calls.append("datetime.now")
            raise AssertionError("datetime.now() used")

        @classmethod
        def today(cls):
            calls.append("datetime.today")
            raise AssertionError("datetime.today() used")

    def boom(*_a, **_k):
        calls.append("time")
        raise AssertionError("time used")

    for fake_today in (date(2020, 1, 1), date(2026, 10, 22), date(2031, 12, 31)):
        monkeypatch.setattr(real_datetime, "date", SpyDate)
        monkeypatch.setattr(real_datetime, "datetime", SpyDatetime)
        if hasattr(dates, "date"):
            monkeypatch.setattr(dates, "date", SpyDate)
        if hasattr(dates, "datetime"):
            monkeypatch.setattr(dates, "datetime", SpyDatetime)
        monkeypatch.setattr("time.time", boom)
        results.append(
            [
                resolve_due(p, d("2026-09-01"))
                for p in ("by Friday", "by tomorrow", "by EOD", "by next Tuesday", "by 10 Sep")
            ]
        )
        del fake_today
    assert calls == []
    assert results[0] == results[1] == results[2]
    assert results[0][0].due == d("2026-09-04")


def test_module_source_has_no_clock_calls():
    src = Path(dates.__file__).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert not re.search(r"\.today\(|\.now\(|import time|time\.time|utcnow", code)


def test_resolve_due_never_raises_on_garbage():
    nasty = [
        "by " + "9" * 50,
        "by 0 Jan",
        "by \x00\x01",
        "by 99999-99-99",
        "by Oct 0th",
        "due 31 Sep",
        "by mid-Smarch",
        "by end of",
        "by next",
        "by next Funday",
        "by 9999-12-31",
        "by 31 Dec 9999",
        "due next Friday",
    ]
    for phrase in nasty:
        for meeting in (d("2026-09-01"), d("9999-12-30"), None):
            result = resolve_due(phrase, meeting)
            assert isinstance(result, DueResult)


# --- 3.3 header dates ---------------------------------------------------------------------


def test_d50_header_formats():
    assert parse_header_date("2026-09-01") == d("2026-09-01")
    assert parse_header_date("9 September 2026") == d("2026-09-09")
    assert parse_header_date("Monday, 14 September 2026") == d("2026-09-14")
    _in_note("2026-09-09-qa-standup.md", "Date: 9 September 2026")
    _in_note("2026-09-14-onboarding-flow-design.md", "Date: Monday, 14 September 2026")
    _in_note("2026-09-01-quote-portal-kickoff.md", "Date: 2026-09-01")


@pytest.mark.parametrize("text", ["sometime last week", "", "13/45/2026", "   ", "2026-13-01"])
def test_d51_unparseable_header_dates(text):
    assert parse_header_date(text) is None


def test_d51_real_note():
    _in_note("2026-10-03-sales-pipeline.md", "Date: sometime last week")


def test_d52_wrong_weekday_ignored():
    assert parse_header_date("Monday, 15 September 2026") == d("2026-09-15")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  2026-09-16  ", "2026-09-16"),
        ('"2026-09-16"', "2026-09-16"),
        ("14 sep 2026", "2026-09-14"),
        ("Mon, 14 Sep 2026", "2026-09-14"),
        ("14 SEPTEMBER 2026", "2026-09-14"),
    ],
)
def test_header_date_tolerance(text, expected):
    assert parse_header_date(text) == d(expected)


@pytest.mark.parametrize(
    "text", ["31 February 2026", "2026-02-30", "0 September 2026", "9 Foo 2026"]
)
def test_header_date_invalid_calendar_returns_none(text):
    assert parse_header_date(text) is None


def test_header_date_non_string_does_not_raise():
    assert parse_header_date(None) is None  # type: ignore[arg-type]


# --- 3.4 overdue --------------------------------------------------------------------------

TODAY = d("2026-10-22")


@pytest.mark.parametrize(
    ("case", "status", "due", "today", "expected"),
    [
        ("D60", "open", d("2026-10-21"), TODAY, True),
        ("D61", "open", d("2026-10-22"), TODAY, False),
        ("D62", "open", d("2026-10-23"), TODAY, False),
        ("D63", "open", None, TODAY, False),
        ("D64", "done", d("2026-09-01"), TODAY, False),
        ("D65", "open", d("2026-10-21"), d("2026-10-21"), False),
    ],
)
def test_is_overdue(case, status, due, today, expected):
    assert is_overdue(status, due, today) is expected
