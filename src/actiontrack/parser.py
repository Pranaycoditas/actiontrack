"""Stage 2: structure only. Header, attendees and candidate action lines.

Owner and due phrases are captured as raw text. Interpreting them is the job of
`owners.py` and `dates.py`. Nothing here reads the clock.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from actiontrack.models import Header, Note, NoteFile, RawLine, Skip

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_note(note: NoteFile) -> Note | Skip:
    """Parse one note. Never raises: any exception becomes a `Skip`."""
    try:
        header, warnings = _parse_header(note.text, note.file)
        lines = find_action_lines(note.text)
        warnings = warnings + _exclusion_warnings(note.text)
        return Note(file=note.file, header=header, lines=lines, warnings=warnings)
    except Exception as exc:  # noqa: BLE001 - the hard rule: a bad note is skipped, not fatal
        message = str(exc) or type(exc).__name__
        return Skip(note.file, f"parse error: {message}")


def parse_header(text: str, filename: str) -> Header:
    """Meeting title, date and attendees. See `_parse_header` for the warnings."""
    return _parse_header(text, filename)[0]


def find_action_lines(text: str) -> list[RawLine]:
    """Every action line outside fenced code, HTML comments and block quotes."""
    found: list[RawLine] = []
    table = _TableState()
    for line_no, raw, visible in _visible_lines(text, []):
        if visible is None or visible.lstrip().startswith(">"):
            table.reset()
            continue
        shown = raw if visible == raw else visible.strip()

        m = _CHECKBOX_RE.match(visible)
        if m:
            table.reset()
            body = m.group(2).strip()
            if body:
                owner, task, due = split_owner_task_due(body)
                if task:
                    found.append(
                        RawLine(line_no, "checkbox", shown, m.group(1) in "xX", owner, task, due)
                    )
            continue

        m = _ACTION_RE.match(visible)
        if m:
            table.reset()
            body = m.group(1).strip()
            if body:
                owner, task, due = split_owner_task_due(body)
                if task:
                    found.append(RawLine(line_no, "action", shown, False, owner, task, due))
            continue

        row = table.feed(visible)
        if row is not None:
            owner, task, due = row
            if task:
                found.append(RawLine(line_no, "table", shown, False, owner, task, due))
    return found


def split_owner_task_due(body: str) -> tuple[str | None, str, str | None]:
    """Split an action body into raw (owner text, task text, due phrase text).

    The due phrase is removed from the task only when it is introduced by
    `by`, `due`, `before` or is a trailing bare `tomorrow`/`today`/`EOD`. Phrases
    introduced by `from`, `for` or `on` are returned as due text but stay in the
    task, because they are not deadlines (the dates module makes that call).
    """
    body = body.strip()
    owner: str | None = None
    rest = body
    m = _HANDLE_RE.match(body)
    if m:
        owner, rest = m.group(1), m.group(2)
    else:
        m = _OWNER_TO_RE.match(body)
        if m:
            owner, rest = m.group(1), m.group(2) or ""
    task, due = _split_due(rest)
    return owner, task, due


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

_FILENAME_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_YAML_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$")
_MEETING_RE = re.compile(r"^#\s+Meeting:\s*(.*)$", re.IGNORECASE)
_H1_RE = re.compile(r"^#\s+(\S.*)$")
_DATE_LINE_RE = re.compile(r"^date:\s*(.*)$", re.IGNORECASE)
_ATTENDEES_LINE_RE = re.compile(r"^attendees:\s*(.*)$", re.IGNORECASE)
_H2_RE = re.compile(r"^#{2,}\s")
_YAML_ITEM_RE = re.compile(r"^\s*-\s+(.+)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1].strip()
    return value


def _split_list(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [name for name in (_unquote(p) for p in value.split(",")) if name]


def _filename_date(filename: str) -> date | None:
    m = _FILENAME_DATE_RE.match(Path(filename).name)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _parse_header(text: str, filename: str) -> tuple[Header, list[str]]:
    from actiontrack.dates import parse_header_date  # late import: written in parallel

    lines = text.split("\n")
    title: str | None = None
    date_text: str | None = None
    attendees: list[str] | None = None
    start = 0

    if lines and lines[0].strip() == "---":
        end = next((j for j in range(1, len(lines)) if lines[j].strip() in ("---", "...")), None)
        if end is not None:
            start = end + 1
            i = 1
            while i < end:
                m = _YAML_KEY_RE.match(lines[i])
                i += 1
                if not m:
                    continue
                key, value = m.group(1).lower(), m.group(2).strip()
                if key == "title" and title is None:
                    title = _unquote(value) or None
                elif key == "date" and date_text is None:
                    date_text = _unquote(value) or None
                elif key == "attendees" and attendees is None:
                    if value:
                        attendees = _split_list(value)
                    else:
                        attendees = []
                        while i < end and _YAML_ITEM_RE.match(lines[i]):
                            attendees.append(_unquote(_YAML_ITEM_RE.match(lines[i]).group(1)))  # type: ignore[union-attr]
                            i += 1

    h1_title: str | None = None
    for line in lines[start:]:
        if _H2_RE.match(line):
            break
        m = _MEETING_RE.match(line)
        if m:
            if title is None:
                title = m.group(1).strip() or None
            continue
        m = _H1_RE.match(line)
        if m:
            if h1_title is None:
                h1_title = m.group(1).strip()
            continue
        m = _DATE_LINE_RE.match(line)
        if m:
            if date_text is None:
                date_text = m.group(1).strip() or None
            continue
        m = _ATTENDEES_LINE_RE.match(line)
        if m and attendees is None:
            attendees = _split_list(m.group(1))
    if title is None:
        title = h1_title

    warnings: list[str] = []
    filename_date = _filename_date(filename)
    header_date = parse_header_date(date_text) if date_text else None
    resolved: date | None
    if header_date is not None:
        resolved, source = header_date, "header"
        if filename_date is not None and filename_date != header_date:
            warnings.append(
                f"header date {header_date.isoformat()} differs from filename date "
                f"{filename_date.isoformat()}; using header date"
            )
    elif filename_date is not None:
        resolved, source = filename_date, "filename"
        if date_text:
            warnings.append(
                f'date "{date_text}" unparseable; using filename date {filename_date.isoformat()}'
            )
        else:
            warnings.append(f"no date in header; using filename date {filename_date.isoformat()}")
    else:
        resolved, source = None, "none"
        if date_text:
            warnings.append(
                f'date "{date_text}" unparseable and no filename date; '
                "relative due dates unresolved"
            )
        else:
            warnings.append("no date found; relative due dates unresolved")

    header = Header(
        title=title,
        date_text=date_text,
        date=resolved,
        date_source=source,  # type: ignore[arg-type]
        attendees=attendees or [],
    )
    return header, warnings


# ---------------------------------------------------------------------------
# Line scanner: fences, comments, block quotes
# ---------------------------------------------------------------------------

_FENCE_OPEN_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def _strip_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    """Remove HTML comment text from `line`; return (visible text, still in a comment)."""
    parts: list[str] = []
    pos = 0
    while True:
        if in_comment:
            end = line.find("-->", pos)
            if end == -1:
                return "".join(parts), True
            pos = end + 3
            in_comment = False
        else:
            start = line.find("<!--", pos)
            if start == -1:
                parts.append(line[pos:])
                return "".join(parts), False
            parts.append(line[pos:start])
            pos = start + 4
            in_comment = True


def _visible_lines(text: str, warnings: list[str]) -> Iterator[tuple[int, str, str | None]]:
    """Yield (line_no, raw line, visible text). Visible is None inside a fenced block.

    Appends a warning to `warnings` for a fence or comment still open at end of file.
    """
    in_comment = False
    comment_line = 0
    fence: tuple[str, int, int] | None = None  # (char, length, opening line)
    for line_no, raw in enumerate(text.split("\n"), 1):
        if fence is not None:
            stripped = raw.strip()
            if stripped and set(stripped) == {fence[0]} and len(stripped) >= fence[1]:
                fence = None
            yield line_no, raw, None
            continue
        was_in_comment = in_comment
        visible, in_comment = _strip_comments(raw, in_comment)
        if in_comment and not was_in_comment:
            comment_line = line_no
        m = _FENCE_OPEN_RE.match(visible)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence = (m.group(1)[0], len(m.group(1)), line_no)
            yield line_no, raw, None
            continue
        yield line_no, raw, visible
    if fence is not None:
        warnings.append(f"unclosed code fence opened at line {fence[2]}; rest of file ignored")
    if in_comment:
        warnings.append(
            f"unclosed HTML comment opened at line {comment_line}; rest of file ignored"
        )


def _exclusion_warnings(text: str) -> list[str]:
    warnings: list[str] = []
    for _ in _visible_lines(text, warnings):
        pass
    return warnings


_CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s*(.*)$")
_ACTION_RE = re.compile(r"^\s*(?:[-*+]\s+)?ACTION:\s*(.*)$")


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

_OWNER_COLS = {"owner", "assignee", "who"}
_ACTION_COLS = {"action", "task", "action item", "item"}
_DUE_COLS = {"due", "due date", "deadline", "when"}
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")


def _cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    parts = stripped.split("|")[1:]
    if stripped.endswith("|"):
        parts = parts[:-1]
    return [p.strip() for p in parts]


class _TableState:
    """Streaming recogniser for Owner / Action / Due tables, mapped by header name."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.state = "none"  # none | header | live | dead
        self.header: list[str] = []
        self.cols: dict[str, int] = {}

    def feed(self, line: str) -> tuple[str | None, str, str | None] | None:
        cells = _cells(line)
        if cells is None:
            self.reset()
            return None
        if self.state in ("none", "header") and not (
            self.state == "header" and self._is_separator(cells)
        ):
            self.state = "header"
            self.header = cells
            return None
        if self.state == "header":
            self.cols = self._map_columns(self.header)
            self.state = "live" if {"owner", "action"} <= self.cols.keys() else "dead"
            return None
        if self.state == "dead" or self._is_separator(cells):
            return None
        owner = self._cell(cells, "owner")
        action = self._cell(cells, "action") or ""
        due = self._cell(cells, "due")
        if owner in ("", "-"):
            owner = None
        if due in ("", "-"):
            due = None
        if due is None:
            action, due = _split_due(action)
        return owner, action, due

    @staticmethod
    def _is_separator(cells: list[str]) -> bool:
        return bool(cells) and all(c == "" or _SEPARATOR_CELL_RE.match(c) for c in cells)

    @staticmethod
    def _map_columns(header: list[str]) -> dict[str, int]:
        cols: dict[str, int] = {}
        for index, name in enumerate(header):
            key = name.lower()
            if key in _OWNER_COLS:
                cols.setdefault("owner", index)
            elif key in _ACTION_COLS:
                cols.setdefault("action", index)
            elif key in _DUE_COLS:
                cols.setdefault("due", index)
        return cols

    def _cell(self, cells: list[str], name: str) -> str | None:
        index = self.cols.get(name)
        if index is None or index >= len(cells):
            return None
        return cells[index]


# ---------------------------------------------------------------------------
# Owner and due phrase capture
# ---------------------------------------------------------------------------

_NAME = r"[A-Z][\w'’-]*(?:\s+[A-Z]\.)?(?:\s*\([^()]*\))?"
_HANDLE_RE = re.compile(r"^(@[\w.-]+)\s*:\s*(.*)$")
_OWNER_TO_RE = re.compile(rf"^({_NAME}(?:\s*&\s*{_NAME})*)\s+to(?:\s+(.*))?$")

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_WEEKDAY = (
    r"(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?"
    r"|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
)
_ORD = r"(?:st|nd|rd|th)?"
_DAY_MONTH = rf"\d{{1,2}}{_ORD}\s+(?:of\s+)?{_MONTH}(?:\s+\d{{4}})?"
_MONTH_DAY = rf"{_MONTH}\s+\d{{1,2}}{_ORD}(?:,?\s+\d{{4}})?"
_PHRASE = (
    r"(?:\d{4}-\d{2}-\d{2}"
    rf"|(?:{_WEEKDAY},?\s+)?{_DAY_MONTH}"
    rf"|(?:{_WEEKDAY},?\s+)?{_MONTH_DAY}"
    rf"|next\s+{_WEEKDAY}"
    rf"|{_WEEKDAY}"
    r"|eod(?:\s+tomorrow)?|tomorrow|today"
    r"|end\s+of\s+(?:next\s+week|(?:this\s+)?(?:week|month))"
    rf"|mid-?\s?{_MONTH})"
)
_EVENT = r"before\s+(?:cutover|go-live|launch|release)"
_KEYWORD = r"(?:due\s+(?:by|on)|by|due|before|from|for|on)"
_END = r"(?![\w'’])"

_DUE_RE = re.compile(
    rf"(?<![\w-])(?:(?P<kw>{_KEYWORD})\s+(?P<ph>{_PHRASE})|(?P<ev>{_EVENT})){_END}",
    re.IGNORECASE,
)
_BARE_RE = re.compile(r"(?<![\w'’-])(?:eod(?:\s+tomorrow)?|tomorrow|today)[\s.!]*$", re.IGNORECASE)
_DEADLINE_KEYWORDS = ("by", "due", "before")


def _tidy(task: str) -> str:
    task = " ".join(task.split())
    task = task.replace("( ", "(").replace(" )", ")").replace("()", "")
    task = re.sub(r" ([,;.])", r"\1", " ".join(task.split()))
    return task.strip(" ,;:—–-")


def _remove_span(text: str, start: int, end: int) -> str:
    """Cut text[start:end], also dropping parentheses that wrapped exactly that span."""
    before, after = text[:start].rstrip(), text[end:].lstrip()
    if before.endswith("(") and after.startswith(")"):
        before, after = before[:-1], after[1:]
    return f"{before} {after}"


def _split_due(rest: str) -> tuple[str, str | None]:
    """Find the due phrase in `rest`. Returns (task text, due phrase text)."""
    deadlines = []
    others = []
    for m in _DUE_RE.finditer(rest):
        keyword = (m.group("kw") or m.group("ev") or "").lower()
        (deadlines if keyword.startswith(_DEADLINE_KEYWORDS) else others).append(m)
    if deadlines:
        m = deadlines[-1]
        return _tidy(_remove_span(rest, m.start(), m.end())), m.group(0)
    bare = _BARE_RE.search(rest)
    if bare:
        due = bare.group(0).strip(" .!\t")
        return _tidy(rest[: bare.start()]), due
    if others:
        return _tidy(rest), others[-1].group(0)
    return _tidy(rest), None
