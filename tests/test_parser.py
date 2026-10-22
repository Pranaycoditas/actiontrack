"""Parser tests (TEST_PLAN P01-P50, P66, P71)."""

import time
from datetime import date
from pathlib import Path

import pytest

from actiontrack import parser
from actiontrack.models import Note, NoteFile, RawLine, Skip
from actiontrack.parser import (
    find_action_lines,
    parse_header,
    parse_note,
    split_owner_task_due,
)

NOTES = Path(__file__).resolve().parent.parent / "notes"


def load(name: str) -> NoteFile:
    text = (NOTES / name).read_bytes().decode("utf-8").replace("\r\n", "\n")
    return NoteFile(file=name, text=text, content_hash="x")


def real_lines(name: str) -> list[RawLine]:
    return find_action_lines(load(name).text)


def by_task(lines: list[RawLine], fragment: str) -> RawLine:
    [match] = [ln for ln in lines if fragment in ln.task_text]
    return match


def tasks(lines: list[RawLine]) -> list[str]:
    return [ln.task_text for ln in lines]


# ---- 2.1 syntaxes ----------------------------------------------------------


def test_p01_checkbox_open():
    ln = by_task(real_lines("2026-09-01-quote-portal-kickoff.md"), "revised quote")
    assert ln.syntax == "checkbox"
    assert ln.checked is False
    assert ln.owner_text == "Priya"
    assert ln.task_text == "send the revised quote to Acme"
    assert ln.due_text == "by Friday"
    assert ln.raw_line == "- [ ] Priya to send the revised quote to Acme by Friday"


def test_p02_checked_no_due():
    ln = by_task(real_lines("2026-09-22-quote-portal-weekly.md"), "confirm cloud budget")
    assert ln.checked is True
    assert ln.owner_text == "Sam"
    assert ln.due_text is None


def test_p03_uppercase_x_crlf():
    lines = real_lines("2026-10-02-finance-sync.md")
    ln = by_task(lines, "approve the Q4 cloud spend")
    assert ln.checked is True
    for item in lines:
        assert "\r" not in item.raw_line + item.task_text + (item.due_text or "")


def test_p04_star_bullet_due_not_percent():
    ln = by_task(real_lines("2026-10-02-finance-sync.md"), "cut cloud costs")
    assert ln.syntax == "checkbox"
    assert ln.due_text == "by 2026-10-09"
    assert "—" in ln.task_text and "proposal" in ln.task_text
    assert "2026-10-09" not in ln.task_text
    assert ln.task_text.startswith("cut cloud costs by 10%")


def test_p05_plus_bullet():
    ln = by_task(real_lines("2026-09-30-q4-offsite.md"), "on-call rotation")
    assert ln.due_text == "by mid-October"
    assert ln.owner_text == "Sam"


def test_p06_indented():
    ln = by_task(real_lines("2026-09-30-q4-offsite.md"), "validate targets")
    assert ln.due_text == "by Oct 5th"
    assert ln.raw_line.startswith("  - [ ]")
    assert ln.owner_text == "Karan"


def test_p07_action_prefix():
    ln = by_task(real_lines("2026-09-30-q4-offsite.md"), "offsite summary")
    assert ln.syntax == "action"
    assert ln.checked is False
    assert ln.owner_text == "Karan"
    assert ln.task_text == "circulate the offsite summary"
    assert ln.due_text == "tomorrow"


def test_p08_table_row():
    lines = real_lines("2026-09-30-q4-offsite.md")
    [row] = [ln for ln in lines if ln.syntax == "table"]
    assert row.owner_text == "Anita"
    assert row.task_text == "Refresh the brand kit"
    assert row.due_text == "2026-10-09"
    assert row.checked is False
    assert not any(t in ("Action", "Owner", "---") for t in tasks(lines))


def test_p09_items_anywhere_in_offsite():
    lines = real_lines("2026-09-30-q4-offsite.md")
    assert any("own the hiring plan" in t for t in tasks(lines))
    assert len(lines) == 9
    assert [ln.syntax for ln in lines].count("checkbox") == 7


def test_p10_untitled():
    lines = real_lines("untitled.md")
    assert [(ln.owner_text, ln.task_text, ln.due_text) for ln in lines] == [
        ("Sam", "chase the vendor", None),
        ("Priya", "send the slides", "by Friday"),
    ]


def test_p11_table_column_order_by_name():
    text = "| Due | Owner | Action |\n|---|---|---|\n| 2026-10-09 | Anita | Refresh the kit |\n"
    [ln] = find_action_lines(text)
    assert (ln.owner_text, ln.task_text, ln.due_text) == ("Anita", "Refresh the kit", "2026-10-09")
    assert ln.line_no == 3


def test_table_requires_owner_and_action_columns():
    text = "| Name | Notes |\n|---|---|\n| Anita | whatever |\n"
    assert find_action_lines(text) == []


def test_table_empty_due_cell_and_ends_at_blank_line():
    text = (
        "| Owner | Action | Due |\n|---|---|---|\n| Sam | Do it |  |\n\n| Bob | Not a row | x |\n"
    )
    [ln] = find_action_lines(text)
    assert ln.due_text is None
    assert ln.owner_text == "Sam"


def test_p12_adjacent_open_and_done():
    lines = find_action_lines("- [ ] Sam to a\n- [x] Sam to b\n")
    assert [ln.checked for ln in lines] == [False, True]
    assert [ln.line_no for ln in lines] == [1, 2]


# ---- 2.2 exclusions --------------------------------------------------------


def test_p20_blockquote_real():
    lines = real_lines("2026-09-21-incident-review.md")
    refunds = [ln for ln in lines if "refund affected customers" in ln.task_text]
    assert len(refunds) == 1
    assert refunds[0].due_text is None
    assert not refunds[0].raw_line.startswith(">")


def test_p21_p22_fence_and_comment_real():
    lines = real_lines("2026-10-09-security-review.md")
    joined = " ".join(tasks(lines))
    assert "remediate" not in joined
    assert "hardware tokens" not in joined
    assert len(lines) == 4


def test_p23_multiline_comment():
    text = (
        "<!--\n- [ ] Sam to hidden one\n- [ ] Sam to hidden two\n"
        "--> - [ ] Sam to visible after close\n- [ ] Sam to normal\n"
    )
    assert tasks(find_action_lines(text)) == ["visible after close", "normal"]


def test_comment_inline_and_unclosed():
    text = "- [ ] Sam to a <!-- hide --> by Friday\n<!-- never closed\n- [ ] Sam to hidden\n"
    lines = find_action_lines(text)
    assert tasks(lines) == ["a"]
    assert lines[0].due_text == "by Friday"
    assert len(lines) == 1


def test_p24_indented_fences():
    text = (
        "   ```\n- [ ] Sam to in backticks\n   ```\n- [ ] Sam to after one\n"
        "  ~~~\n- [ ] Sam to in tildes\n  ~~~\n- [ ] Sam to after two\n"
    )
    assert tasks(find_action_lines(text)) == ["after one", "after two"]


def test_fence_longer_closer_and_mismatch():
    text = "````\n```\n- [ ] Sam to inside\n````\n- [ ] Sam to out\n"
    assert tasks(find_action_lines(text)) == ["out"]


def test_p25_prose_not_extracted():
    lines = real_lines("2026-09-09-qa-standup.md")
    assert len([t for t in tasks(lines) if "vendor" in t]) == 1
    off = real_lines("2026-09-30-q4-offsite.md")
    assert not any("offered to help recruit" in t for t in tasks(off))
    fin = real_lines("2026-10-02-finance-sync.md")
    assert len([t for t in tasks(fin) if "cut" in t]) == 1


def test_p26_unclosed_fence_warns():
    text = "- [ ] Sam to before\n```\n- [ ] Sam to inside\n"
    note = parse_note(NoteFile("f.md", text, "h"))
    assert isinstance(note, Note)
    assert tasks(note.lines) == ["before"]
    assert any("unclosed" in w and "fence" in w for w in note.warnings)


def test_p27_empty_checkbox():
    text = "- [ ]\n- [ ]   \n- [x]\n- [ ] Sam to ok\n"
    assert tasks(find_action_lines(text)) == ["ok"]


def test_empty_action_line():
    assert find_action_lines("ACTION:\nACTION:   \n") == []


# ---- 2.3 owner / due capture ----------------------------------------------


def design() -> list[RawLine]:
    return real_lines("2026-09-18-design-review.md")


def test_p30_handle():
    ln = by_task(design(), "colour contrast")
    assert ln.owner_text == "@anita"
    assert ln.task_text == "audit colour contrast on the dashboard"
    assert ln.due_text == "by Mon"


def test_p31_joint():
    ln = by_task(design(), "component API")
    assert ln.owner_text == "Anita & Rahul"
    assert ln.due_text == "by Wednesday"


def test_p32_with_collaborator():
    ln = by_task(design(), "user feedback")
    assert ln.owner_text == "Lena (with Priya)"
    assert ln.due_text == "by 2026-09-25"
    assert ln.task_text == "collect user feedback on the prototype"


def test_p33_everyone():
    ln = by_task(design(), "review the prototype")
    assert ln.owner_text == "Everyone"
    assert ln.due_text is None
    assert ln.task_text == "review the prototype before the next review"


def test_p34_tbd():
    ln = by_task(design(), "changelog")
    assert ln.owner_text == "TBD"
    assert ln.task_text == "write the design-system changelog"


def test_p35_initial_and_emdash():
    ln = by_task(real_lines("2026-09-08-quote-portal-weekly.md"), "revised quote")
    assert ln.owner_text == "Priya N."
    assert ln.due_text == "by Friday"
    assert ln.task_text == "send revised quote to Acme"


def test_p36_owner_named_in_task():
    ln = by_task(real_lines("2026-10-07-standup.md"), "Anita's PR")
    assert ln.owner_text == "Rahul"
    assert ln.due_text == "by tomorrow"
    assert ln.task_text == "review Anita's PR"


def test_p37_no_owner():
    [ln] = find_action_lines("- [ ] Book the venue\n")
    assert ln.owner_text is None
    assert ln.task_text == "Book the venue"
    assert ln.due_text is None


def test_p38_from_date_kept_in_task():
    ln = by_task(real_lines("2026-09-29-billing-cutover-planning.md"), "freeze invoice edits")
    assert ln.task_text == "freeze invoice edits from 9 Oct"
    assert ln.due_text == "from 9 Oct"
    assert ln.owner_text == "Karan"


def test_p39_prose_not_due():
    lines = real_lines("2026-09-23-standup.md")
    # The real file does carry an action line for Sam, but with no due phrase:
    # "after the weekend" lives only in the Discussion prose and is never picked up.
    sam = by_task(lines, "staging credentials")
    assert sam.due_text is None
    assert all("weekend" not in ln.task_text for ln in lines)


@pytest.mark.parametrize(
    ("body", "owner", "task", "due"),
    [
        ("Priya S. to run the tests by Thursday", "Priya S.", "run the tests", "by Thursday"),
        ("@anita: audit stuff", "@anita", "audit stuff", None),
        ("Sam to snapshot the DB before cutover", "Sam", "snapshot the DB", "before cutover"),
        (
            "Lena to run the survey, results due 15 October",
            "Lena",
            "run the survey, results",
            "due 15 October",
        ),
        ("Rahul to wait by Wed 16 Sep", "Rahul", "wait", "by Wed 16 Sep"),
        (
            "Sam to demo the portal to Acme on 2026-10-14",
            "Sam",
            "demo the portal to Acme on 2026-10-14",
            "on 2026-10-14",
        ),
        ("Sam to ship by end of next week", "Sam", "ship", "by end of next week"),
        ("Sam to ship (by Friday) soon", "Sam", "ship soon", "by Friday"),
        ("Sam to ship by EOD tomorrow", "Sam", "ship", "by EOD tomorrow"),
        ("Sam to ship by Monday and then by Friday", "Sam", "ship by Monday and then", "by Friday"),
        ("Sam to cut costs by 10%", "Sam", "cut costs by 10%", None),
        ("Sam to ship by 7 Jan", "Sam", "ship", "by 7 Jan"),
        ("Sam to ship by next Tuesday", "Sam", "ship", "by next Tuesday"),
        ("Sam to ship by end of month", "Sam", "ship", "by end of month"),
        ("Sam to ship by Oct 3rd", "Sam", "ship", "by Oct 3rd"),
        ("Sam to ship by Fridays", "Sam", "ship by Fridays", None),
        ("Sam to", "Sam", "", None),
        ("Book the venue by Friday", None, "Book the venue", "by Friday"),
        ("Update CRM notes", None, "Update CRM notes", None),
    ],
)
def test_split_owner_task_due(body, owner, task, due):
    assert split_owner_task_due(body) == (owner, task, due)


# ---- 2.4 header ------------------------------------------------------------


def hdr(name: str):
    note = load(name)
    return parse_header(note.text, note.file)


def test_p40_iso():
    h = hdr("2026-09-01-quote-portal-kickoff.md")
    assert h.date == date(2026, 9, 1)
    assert h.date_source == "header"
    assert h.date_text == "2026-09-01"


def test_p41_day_month_year():
    assert hdr("2026-09-09-qa-standup.md").date == date(2026, 9, 9)


def test_p42_weekday_prefix():
    assert hdr("2026-09-14-onboarding-flow-design.md").date == date(2026, 9, 14)


@pytest.mark.parametrize("name", ["2026-09-16-standup.md", "2026-09-30-standup.md"])
def test_p43_front_matter(name):
    h = hdr(name)
    assert h.date_source == "header"
    assert h.title
    assert h.date is not None
    assert len(h.attendees) >= 2


def test_p43_front_matter_values():
    h = hdr("2026-09-16-standup.md")
    assert h.title == "Team standup"
    assert h.date == date(2026, 9, 16)
    assert h.attendees == ["Anita Desai", "Lena Fischer", "Meera Iyer"]


def test_front_matter_block_list_and_quotes():
    text = (
        '---\ntitle: "Hello: x"\nDate: 2026-09-16\nattendees:\n  - A One\n  - "B Two"\n---\nbody\n'
    )
    h = parse_header(text, "x.md")
    assert h.title == "Hello: x"
    assert h.attendees == ["A One", "B Two"]
    assert h.date == date(2026, 9, 16)


def test_p44_filename_fallback_with_warning():
    note = parse_note(load("2026-10-03-sales-pipeline.md"))
    assert isinstance(note, Note)
    assert note.header.date == date(2026, 10, 3)
    assert note.header.date_source == "filename"
    assert note.header.date_text == "sometime last week"
    assert note.warnings == [
        'date "sometime last week" unparseable; using filename date 2026-10-03'
    ]


def test_p45_no_attendees():
    h = hdr("2026-09-23-standup.md")
    assert h.attendees == []
    assert h.date == date(2026, 9, 23)


def test_p46_comma_attendees():
    h = hdr("2026-09-01-quote-portal-kickoff.md")
    assert len(h.attendees) == 4
    assert all(a == a.strip() and a for a in h.attendees)


def test_p47_nine_attendees():
    assert len(hdr("2026-09-30-q4-offsite.md").attendees) == 9


def test_p48_title_kept_header_used():
    note = parse_note(load("2026-10-05-onboarding-retro.md"))
    assert isinstance(note, Note)
    assert note.header.title == "Onboarding flow checkpoint"
    assert note.warnings == []


def test_p49_header_filename_disagree():
    text = "# Meeting: X\nDate: 2026-09-02\nAttendees: A B\n"
    note = parse_note(NoteFile("2026-09-01-x.md", text, "h"))
    assert isinstance(note, Note)
    assert note.header.date == date(2026, 9, 2)
    assert note.header.date_source == "header"
    assert len(note.warnings) == 1
    assert "2026-09-02" in note.warnings[0] and "2026-09-01" in note.warnings[0]


def test_p50_no_date_anywhere():
    note = parse_note(load("untitled.md"))
    assert isinstance(note, Note)
    assert note.header.date is None
    assert note.header.date_source == "none"
    assert note.header.attendees == []
    assert note.header.title is None
    assert len(note.lines) == 2
    assert note.warnings  # undated warning


def test_missing_header_date_uses_filename():
    note = parse_note(NoteFile("2026-09-05-x.md", "# Meeting: X\n- [ ] Sam to a\n", "h"))
    assert isinstance(note, Note)
    assert note.header.date == date(2026, 9, 5)
    assert note.header.date_source == "filename"
    assert note.header.date_text is None
    assert note.warnings == ["no date in header; using filename date 2026-09-05"]


def test_filename_impossible_date_ignored():
    note = parse_note(NoteFile("2026-13-45-x.md", "hello\n", "h"))
    assert isinstance(note, Note)
    assert note.header.date is None


def test_header_ignores_date_in_body():
    text = "# Meeting: X\n\n## Notes\nDate: 2026-01-01\nAttendees: Z\n"
    h = parse_header(text, "x.md")
    assert h.date is None and h.attendees == []


def test_p00_real_notes_all_parse():
    """Every real .md note that is text parses without a Skip."""
    for path in sorted(NOTES.glob("*.md")):
        data = path.read_bytes()
        if not data or b"\x00" in data:
            continue
        result = parse_note(load(path.name))
        assert isinstance(result, Note), path.name


# ---- 2.5 errors, performance ----------------------------------------------


def test_p66_parse_exception_becomes_skip(monkeypatch):
    real = parser.find_action_lines

    def boom(text, *a, **k):
        if "BOOM" in text:
            raise ValueError("boom")
        return real(text, *a, **k)

    monkeypatch.setattr(parser, "find_action_lines", boom)
    bad = parse_note(NoteFile("bad.md", "BOOM\n", "h"))
    good = parse_note(NoteFile("good.md", "- [ ] Sam to ok\n", "h"))
    assert bad == Skip("bad.md", "parse error: boom")
    assert isinstance(good, Note)
    assert len(good.lines) == 1


def test_parse_error_never_raises_even_for_empty_message(monkeypatch):
    def boom(text, *a, **k):
        raise RuntimeError()

    monkeypatch.setattr(parser, "find_action_lines", boom)
    result = parse_note(NoteFile("b.md", "x", "h"))
    assert isinstance(result, Skip)
    assert result.reason.startswith("parse error: ")


@pytest.mark.parametrize(
    "line",
    [
        "- [ ] Sam to " + "word " * 200_000,
        "- [ ] " + "by " * 340_000,
        "- [ ] " + "A" * 1_000_000,
        "- [ ] Sam to " + " " * 1_000_000 + "x",
        "- [ ] " + "A & " * 250_000,
        "| Owner | Action |\n|---|---|\n| " + "x" * 1_000_000 + " | y |",
    ],
)
def test_p71_one_megabyte_line(line):
    start = time.perf_counter()
    result = parse_note(NoteFile("big.md", line + "\n", "h"))
    elapsed = time.perf_counter() - start
    assert isinstance(result, (Note, Skip))
    assert elapsed < 2.0
