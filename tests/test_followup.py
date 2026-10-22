"""followup stage (TEST_PLAN 10, F01-F23, F27, F28). F24-F26 need the real-notes ingest."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from actiontrack.drafts import GmailMcpSink, InMemorySink
from actiontrack.errors import DraftError, SinkUnavailable, UsageError
from actiontrack.followup import build_draft, load_email_map, run_followup
from actiontrack.store import Store
from followup_seed import ROWS, TODAY, seed
from ingest_helpers import ingest, lst, rows

ANITA = "Anita Desai"


@pytest.fixture
def ids(tmp_path):
    return seed(tmp_path / "t.db")


@pytest.fixture
def st(ids, tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def run(st, owner=ANITA, today=TODAY, emap=None, sink=None):
    sink = sink if sink is not None else InMemorySink()
    res = run_followup(owner, st, sink, today, emap)
    return res, sink


def body_lines(sink: InMemorySink) -> list[str]:
    return sink.drafts[0].body.split("\n")


def test_f01_f02_one_draft_and_counts(st):
    res, sink = run(st)
    assert len(sink.drafts) == 1
    assert sink.drafts[0].subject == "Action items follow-up: Anita Desai (1 overdue, 3 open)"
    assert (res.overdue, res.open) == (1, 3)
    assert res.draft_id and res.owner == ANITA


def test_f03_f04_exact_body_layout(st, ids):
    _, sink = run(st)
    f = lambda label: f"2026-10-{ROWS_N[label]:02d}-seed-{label}.md"  # noqa: E731
    expected = "\n".join(
        [
            "Hi Anita,",
            "",
            "Here are your outstanding action items as of 2026-10-22.",
            "",
            "Overdue",
            f"- share wireframes (due 2026-09-24, 28 days overdue) [{ids['a9']}] - from {f('a9')}",
            "",
            "Open",
            f"- refresh brand kit (due 2026-10-22) [{ids['a4']}] - from {f('a4')}",
            f"- audit colour contrast (due 2026-10-30) [{ids['a5']}] - from {f('a5')}",
            f"- agree on component API (with Rahul) (no due date) [{ids['a10']}] - from {f('a10')}",
            "",
            "If any of these are done or need a new date, reply and I will update the tracker.",
            "",
            "Thanks,",
        ]
    )
    assert sink.drafts[0].body == expected


ROWS_N = {r[0]: n for n, r in enumerate(ROWS, start=1)}


def test_f05_due_today_is_open(st, ids):
    _, sink = run(st)
    lines = body_lines(sink)
    open_at = lines.index("Open")
    brand = next(i for i, ln in enumerate(lines) if ids["a4"] in ln)
    assert brand > open_at


def test_f06_done_ambiguous_unassigned_never_included(st, ids):
    _, sink = run(st)
    body = sink.drafts[0].body
    for label in ("a3", "a7", "a8", "b2", "a1", "a6"):
        assert ids[label] not in body


def _only(st_path, keep):
    return seed(st_path, [r for r in ROWS if r[0] in keep])


def test_f07_only_overdue(tmp_path):
    p = tmp_path / "o.db"
    _only(p, {"a9"})
    with Store(p) as s:
        _, sink = run(s)
    assert sink.drafts[0].subject.endswith("(1 overdue)")
    assert "\nOpen\n" not in sink.drafts[0].body and "Overdue" in sink.drafts[0].body


def test_f08_only_open(tmp_path):
    p = tmp_path / "o.db"
    _only(p, {"a4", "a5", "a10"})
    with Store(p) as s:
        _, sink = run(s)
    assert sink.drafts[0].subject.endswith("(3 open)")
    assert "Overdue" not in sink.drafts[0].body


def test_f09_priya_nair_one_draft_and_warning(st, ids):
    res, sink = run(st, "Priya Nair")
    assert len(sink.drafts) == 1
    assert ids["a6"] in sink.drafts[0].body and ids["b1"] not in sink.drafts[0].body
    assert res.warnings == ['1 items for "Priya" are ambiguous and not included']


def test_no_warning_when_no_ambiguous(st):
    res, _ = run(st)
    assert res.warnings == []


def test_f10_bare_shared_first_name(st):
    with pytest.raises(UsageError) as ei:
        run(st, "Priya")
    assert str(ei.value) == 'ambiguous owner "Priya": use "Priya Nair" or "Priya Shah"'


def test_f10_case_variant_of_shared_name_still_ambiguous(st):
    with pytest.raises(UsageError, match="ambiguous owner"):
        run(st, "priya")


@pytest.mark.parametrize("name", ["Unassigned", "unassigned", "Ambiguous (Priya)", "Zoe Unknown"])
def test_f11_f12_invalid_owners_never_call_sink(st, name):
    sink = InMemorySink()
    with pytest.raises(UsageError):
        run_followup(name, st, sink, TODAY, None)
    assert sink.drafts == []


def test_f12_unknown_owner_message(st):
    with pytest.raises(UsageError, match="unknown owner"):
        run(st, "Zoe Unknown")


def test_unique_first_name_and_case_variant_resolve(st):
    res, sink = run(st, "anita")
    assert res.owner == ANITA and len(sink.drafts) == 1
    assert sink.drafts[0].owner == ANITA
    res, _ = run(st, "ANITA DESAI")
    assert res.owner == ANITA


def test_f13_nothing_outstanding(st):
    res, sink = run(st, "Karan Joshi")
    assert sink.drafts == [] and res.draft_id is None
    assert res.message == "No open or overdue items for Karan Joshi."


def test_f14_to_blank_without_map(st):
    _, sink = run(st)
    assert sink.drafts[0].to is None


def test_f15_email_map(st):
    _, sink = run(st, emap={ANITA: "anita@example.com"})
    assert sink.drafts[0].to == "anita@example.com"
    _, sink = run(st, "Sam Okafor", emap={ANITA: "anita@example.com"})
    assert sink.drafts[0].to is None
    _, sink = run(st, emap={"anita desai": "a@x.io"})
    assert sink.drafts[0].to == "a@x.io"


def test_load_email_map_ok_and_bom_and_blank(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("﻿owner,email\nAnita Desai, anita@example.com \nSam Okafor,\n", "utf-8")
    assert load_email_map(p) == {"Anita Desai": "anita@example.com"}


@pytest.mark.parametrize("content", ["name,mail\nA,b\n", "", "owner\nAnita\n"])
def test_f16_bad_header_is_usage_error(tmp_path, content):
    p = tmp_path / "m.csv"
    p.write_text(content)
    with pytest.raises(UsageError):
        load_email_map(p)


def test_f16_missing_file_and_directory(tmp_path):
    with pytest.raises(UsageError):
        load_email_map(tmp_path / "nope.csv")
    with pytest.raises(UsageError):
        load_email_map(tmp_path)


def test_f17_today_changes_output_deterministically(st):
    _, a = run(st, today=date(2026, 10, 9))
    _, b = run(st, today=date(2026, 10, 22))
    _, c = run(st, today=date(2026, 10, 22))
    assert a.drafts[0].subject.endswith("(1 overdue, 3 open)")  # a4/a5 not yet due
    assert "15 days overdue" in a.drafts[0].body and "28 days overdue" in b.drafts[0].body
    assert b.drafts[0] == c.drafts[0]
    # Oct 9: nothing due that day for Anita but Sam's a1 is due 10-09 -> open, not overdue
    _, sam9 = run(st, "Sam Okafor", today=date(2026, 10, 9))
    assert sam9.drafts[0].subject.endswith("(2 open)")


def test_f19_twice_gives_two_drafts(st):
    sink = InMemorySink()
    run(st, sink=sink)
    run(st, sink=sink)
    assert len(sink.drafts) == 2


class Boom:
    def __init__(self, exc):
        self.exc, self.calls = exc, 0

    def create_draft(self, draft):
        self.calls += 1
        raise self.exc


def test_f20_f21_sink_errors_propagate_without_retry(st):
    for exc in (SinkUnavailable("x"), DraftError("y")):
        sink = Boom(exc)
        with pytest.raises(type(exc)):
            run_followup(ANITA, st, sink, TODAY, None)
        assert sink.calls == 1


def test_f22_validation_before_sink(st):
    sink = Boom(SinkUnavailable("x"))
    with pytest.raises(UsageError):
        run_followup("Zoe Unknown", st, sink, TODAY, None)
    assert sink.calls == 0


def test_nothing_outstanding_does_not_touch_sink(st):
    sink = Boom(SinkUnavailable("x"))
    res = run_followup("Karan Joshi", st, sink, TODAY, None)
    assert sink.calls == 0 and res.draft_id is None


def test_f23_awkward_text_intact(tmp_path):
    rows = [
        ("c1", ANITA, "tidy R&D \"quotes\" 'x' <b> \U0001f680 café", date(2026, 10, 1), "open", []),
        ("c2", ANITA, "x" * 500, None, "open", []),
    ]
    p = tmp_path / "w.db"
    seed(p, rows)
    with Store(p) as s:
        _, sink = run(s)
    body = sink.drafts[0].body
    assert "tidy R&D \"quotes\" 'x' <b> \U0001f680 café" in body
    assert "x" * 500 in body


def test_f27_subject_has_no_id_or_file(st, ids):
    _, sink = run(st)
    subj = sink.drafts[0].subject
    assert ".md" not in subj and not any(i in subj for i in ids.values())


def test_f28_body_ends_with_thanks_no_name(st):
    _, sink = run(st)
    assert sink.drafts[0].body.endswith("\n\nThanks,")


def test_singular_day_overdue():
    from actiontrack.models import Item
    from followup_seed import ROWS as _r  # noqa: F401

    it = Item(
        "deadbeef",
        "k",
        ANITA,
        "person",
        [],
        "t",
        date(2026, 10, 21),
        None,
        "open",
        False,
        "f.md",
        "g.md",
        1,
    )
    d = build_draft(ANITA, [it], TODAY, None)
    assert d is not None and "(due 2026-10-21, 1 day overdue)" in d.body
    assert "from g.md" in d.body


def test_build_draft_none_when_nothing_outstanding():
    from actiontrack.models import Item

    done = Item("deadbeef", "k", ANITA, "person", [], "t", None, None, "done", False, "f", "f", 1)
    amb = Item(
        "deadbee0",
        "k",
        "Ambiguous (Priya)",
        "ambiguous",
        [],
        "t",
        None,
        None,
        "open",
        False,
        "f",
        "f",
        1,
    )
    assert build_draft(ANITA, [done, amb], TODAY, None) is None
    assert build_draft(ANITA, [], TODAY, None) is None


def test_open_sorted_due_ascending_no_due_last():
    from actiontrack.models import Item

    def mk(i, due):
        return Item(i, "k", ANITA, "person", [], f"task-{i}", due, None, "open", False, "f", "f", 1)

    items = [
        mk("00000003", None),
        mk("00000002", date(2026, 11, 5)),
        mk("00000001", date(2026, 11, 1)),
    ]
    d = build_draft(ANITA, items, TODAY, "a@b.c")
    assert d is not None and d.to == "a@b.c"
    tasks = [ln for ln in d.body.split("\n") if ln.startswith("- ")]
    assert [t.split(" ")[1] for t in tasks] == ["task-00000001", "task-00000002", "task-00000003"]


@pytest.fixture(scope="module")
def real_db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("real") / "real.db"
    assert ingest(path).exit_code == 0
    return path


BODY_ID = re.compile(r"\[([0-9a-f]{8})\]")


def real_followup(db: Path, owner: str):
    sink = InMemorySink()
    with Store(db) as s:
        res = run_followup(owner, s, sink, date(2026, 10, 22), None)
    return res, sink


def sections(body: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = None
    for ln in body.split("\n"):
        if ln in ("Overdue", "Open"):
            current = ln
            out[current] = []
        elif current and ln.startswith("- "):
            out[current].append(ln)
    return out


def test_f24_real_anita(real_db):
    res, sink = real_followup(real_db, ANITA)
    assert len(sink.drafts) == 1
    listed = rows(lst(real_db).stdout)
    by_id = {r[0]: r for r in listed}
    body_ids = BODY_ID.findall(sink.drafts[0].body)
    assert body_ids
    for iid in body_ids:
        assert iid in by_id
        assert by_id[iid][1] != "done"
        assert by_id[iid][2] == ANITA  # a resolved person, never an Ambiguous owner
        assert not by_id[iid][2].startswith("Ambiguous")


def test_f25_real_sam(real_db):
    _, sink = real_followup(real_db, "Sam Okafor")
    body = sink.drafts[0].body
    assert "confirm cloud budget" not in body  # [x] on 2026-09-22
    sec = sections(body)
    mine = rows(lst(real_db, "--owner", "Sam Okafor").stdout)
    overdue_ids = {r[0] for r in mine if r[3] != "-" and r[3] < "2026-10-22" and r[1] != "done"}
    assert overdue_ids
    assert {i for ln in sec["Overdue"] for i in BODY_ID.findall(ln)} == overdue_ids
    assert not {i for ln in sec.get("Open", []) for i in BODY_ID.findall(ln)} & overdue_ids


NINE = [
    "Priya Nair",
    "Priya Shah",
    "Rahul Mehta",
    "Rahul Verma",
    "Anita Desai",
    "Sam Okafor",
    "Meera Iyer",
    "Karan Joshi",
    "Lena Fischer",
]


class _Recording:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name, args):
        self.calls.append((name, args))
        return {"draft_id": f"r-{len(self.calls)}"}


def test_f26_real_all_owners(real_db):
    rec = _Recording()
    sink = GmailMcpSink(rec)
    with Store(real_db) as s:
        stored = set(s.owners())
        assert set(NINE) <= stored
        for owner in NINE:
            before = len(rec.calls)
            res = run_followup(owner, s, sink, date(2026, 10, 22), None)
            outstanding = s.open_items_for(owner)
            assert len(rec.calls) - before == (1 if outstanding else 0), owner
            assert (res.draft_id is not None) == bool(outstanding)
        calls_for_nine = len(rec.calls)
        for fake in ("Ambiguous (Priya)", "Ambiguous (Rahul)", "Unassigned"):
            with pytest.raises(UsageError):
                run_followup(fake, s, sink, date(2026, 10, 22), None)
        for bare in ("Priya", "Rahul"):
            with pytest.raises(UsageError):
                run_followup(bare, s, sink, date(2026, 10, 22), None)
    assert len(rec.calls) == calls_for_nine <= len(NINE)
    for _, args in rec.calls:
        assert "Ambiguous" not in args["subject"] and "Unassigned" not in args["subject"]


def test_followup_module_never_reads_clock():
    src = Path(__file__).parent.parent / "src" / "actiontrack" / "followup.py"
    text = src.read_text()
    assert "date.today" not in text and "datetime.now" not in text
