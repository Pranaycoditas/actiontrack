"""Date logic for actiontrack: header dates, due-phrase resolution and the overdue rule.

Everything here is a pure function. The clock is never read: relative phrases resolve against
the meeting date only, and ``is_overdue`` receives ``today`` as an argument (SPEC 6 and 7.1).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

__all__ = ["DueResult", "is_overdue", "parse_header_date", "resolve_due"]


@dataclass(frozen=True)
class DueResult:
    """Outcome of resolving a due phrase. ``raw`` is the phrase as given (stripped)."""

    due: date | None
    raw: str | None
    warning: str | None = None


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_WEEKDAYS = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "weds": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}
_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WEEKDAY_RE = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))
_FLAGS = re.IGNORECASE

# --- header dates --------------------------------------------------------------------------

_ISO_FULL = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_HEADER_LONG = re.compile(
    rf"(?:(?:{_WEEKDAY_RE})\.?,?\s+)?(\d{{1,2}})\s+({_MONTH_RE})\.?,?\s+(\d{{4}})",
    _FLAGS,
)


def parse_header_date(text: str) -> date | None:
    """Parse a note's header date. Accepts ISO, ``9 September 2026`` and a leading weekday.

    The weekday is ignored even when wrong. Anything else returns None. Never raises.
    """
    try:
        if not isinstance(text, str):
            return None
        s = text.strip().strip("\"'").strip()
        m = _ISO_FULL.fullmatch(s)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = _HEADER_LONG.fullmatch(s)
        if m:
            return date(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))
    except (ValueError, OverflowError):
        return None
    return None


# --- due phrases ---------------------------------------------------------------------------

_KEYWORD = re.compile(r"\b(?:by|due|before)\b[\s:]*", _FLAGS)
_TRAILING_BARE = re.compile(r"\b(eod tomorrow|eod|today|tomorrow)\W*$", _FLAGS)

_ORD = r"(?:st|nd|rd|th)?"
_P_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?![\w-])")
_P_WD_DATE = re.compile(
    rf"(?P<wd>{_WEEKDAY_RE})\.?,?\s+"
    rf"(?:(?P<d1>\d{{1,2}}){_ORD}\s+(?:of\s+)?(?P<m1>{_MONTH_RE})"
    rf"|(?P<m2>{_MONTH_RE})\.?\s+(?P<d2>\d{{1,2}}){_ORD})"
    rf"(?:,?\s+(?P<y>\d{{4}}))?\b(?!%)",
    _FLAGS,
)
_P_DAY_MONTH = re.compile(
    rf"(?:(?P<d1>\d{{1,2}}){_ORD}\s+(?:of\s+)?(?P<m1>{_MONTH_RE})"
    rf"|(?P<m2>{_MONTH_RE})\.?\s+(?P<d2>\d{{1,2}}){_ORD})"
    rf"(?:,?\s+(?P<y>\d{{4}}))?\b(?!%)",
    _FLAGS,
)
_P_EOD_TOMORROW = re.compile(r"(?:eod|end\s+of\s+day)\s+tomorrow\b", _FLAGS)
_P_EOD = re.compile(r"(?:eod|end\s+of\s+day|today)\b", _FLAGS)
_P_TOMORROW = re.compile(r"tomorrow\b", _FLAGS)
_P_END_NEXT_WEEK = re.compile(r"end\s+of\s+(?:the\s+)?next\s+week\b", _FLAGS)
_P_END_MONTH = re.compile(r"end\s+of\s+(?:the\s+)?month\b", _FLAGS)
_P_MID = re.compile(rf"mid[-\s]+(?P<m>{_MONTH_RE})\b", _FLAGS)
_P_NEXT_WD = re.compile(rf"next\s+(?P<wd>{_WEEKDAY_RE})\b", _FLAGS)
_P_WD = re.compile(rf"(?P<wd>{_WEEKDAY_RE})\b", _FLAGS)


def _day_month_year(day: int, month: int, year: int | None, meeting: date | None) -> date | None:
    """Day-month with optional year. Without a year it rolls to the next year if before M."""
    if year is not None:
        return date(year, month, day)
    if meeting is None:
        return None
    for y in (meeting.year, meeting.year + 1):
        try:
            candidate = date(y, month, day)
        except ValueError:
            continue
        if candidate >= meeting:
            return candidate
    return None


def _parse_expression(expr: str, meeting: date | None) -> tuple[date | None, str | None]:
    """Resolve a date expression anchored at the start of ``expr``. Returns (date, warning)."""
    m = _P_ISO.match(expr)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3])), None

    m = _P_WD_DATE.match(expr)
    if m:
        month = _MONTHS[(m["m1"] or m["m2"]).lower()]
        day = int(m["d1"] or m["d2"])
        year = int(m["y"]) if m["y"] else None
        found = _day_month_year(day, month, year, meeting)
        if found is None:
            return None, None
        weekday = _WEEKDAYS[m["wd"].lower()]
        warning = None
        if found.weekday() != weekday:
            warning = (
                f"weekday {_WEEKDAY_NAMES[weekday]} does not match {found.isoformat()} "
                f"({_WEEKDAY_NAMES[found.weekday()]}); using the date"
            )
        return found, warning

    m = _P_DAY_MONTH.match(expr)
    if m:
        month = _MONTHS[(m["m1"] or m["m2"]).lower()]
        day = int(m["d1"] or m["d2"])
        year = int(m["y"]) if m["y"] else None
        return _day_month_year(day, month, year, meeting), None

    # Everything below is relative to the meeting date.
    if meeting is None:
        return None, None

    if _P_EOD_TOMORROW.match(expr) or _P_TOMORROW.match(expr):
        return meeting + timedelta(days=1), None
    if _P_EOD.match(expr):
        return meeting, None
    if _P_END_NEXT_WEEK.match(expr):
        return _monday_of_next_week(meeting) + timedelta(days=4), None
    if _P_END_MONTH.match(expr):
        return date(
            meeting.year, meeting.month, calendar.monthrange(meeting.year, meeting.month)[1]
        ), None
    m = _P_MID.match(expr)
    if m:
        month = _MONTHS[m["m"].lower()]
        year = meeting.year + 1 if month < meeting.month else meeting.year
        return date(year, month, 15), None
    m = _P_NEXT_WD.match(expr)
    if m:
        return _monday_of_next_week(meeting) + timedelta(days=_WEEKDAYS[m["wd"].lower()]), None
    m = _P_WD.match(expr)
    if m:
        delta = (_WEEKDAYS[m["wd"].lower()] - meeting.weekday()) % 7 or 7
        return meeting + timedelta(days=delta), None
    return None, None


def _monday_of_next_week(meeting: date) -> date:
    return meeting - timedelta(days=meeting.weekday()) + timedelta(days=7)


def resolve_due(phrase: str | None, meeting_date: date | None) -> DueResult:
    """Resolve the deadline in ``phrase`` against the meeting date (SPEC 6.1). Never raises.

    ``phrase`` may be just the due text (``by Friday``) or a whole action line. Only dates after
    ``by``/``due``/``before`` and a trailing bare ``tomorrow``/``today``/``EOD`` are deadlines.
    If several are present the last one wins. When nothing resolves, ``due`` is None and ``raw``
    keeps the phrase.
    """
    if not isinstance(phrase, str) or not phrase.strip():
        return DueResult(None, None, None)
    raw = phrase.strip()
    try:
        return _resolve(raw, meeting_date)
    except (ValueError, OverflowError):
        return DueResult(None, raw, None)


def _resolve(raw: str, meeting: date | None) -> DueResult:
    candidates: list[tuple[int, date, str | None]] = []
    for kw in _KEYWORD.finditer(raw):
        try:
            found, warning = _parse_expression(raw[kw.end() :], meeting)
        except (ValueError, OverflowError):
            continue
        if found is not None:
            candidates.append((kw.start(), found, warning))

    bare = _TRAILING_BARE.search(raw)
    if bare and meeting is not None:
        try:
            found, warning = _parse_expression(raw[bare.start() :], meeting)
        except (ValueError, OverflowError):
            found, warning = None, None
        if found is not None:
            candidates.append((bare.start(), found, warning))

    if not candidates:
        return DueResult(None, raw, None)
    _, due, warning = max(candidates, key=lambda c: c[0])
    return DueResult(due, raw, warning)


def is_overdue(status: str, due: date | None, today: date) -> bool:
    """The single definition of overdue: not done, has a due date, and due < today."""
    return status != "done" and due is not None and due < today
