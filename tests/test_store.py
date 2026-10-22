import dataclasses
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from actiontrack import store as store_mod
from actiontrack.errors import StoreError, UsageError
from actiontrack.models import Header, IngestCounts, Item, Mention, Note
from actiontrack.store import ListResult, Store

TODAY = date(2026, 10, 22)
KICKOFF = "2026-09-01-quote-portal-kickoff.md"
WEEKLY1 = "2026-09-15-quote-portal-weekly.md"
WEEKLY2 = "2026-09-22-quote-portal-weekly.md"
WEEKLY0 = "2026-09-08-quote-portal-weekly.md"


def note(file: str, d: date | None = None, h: str | None = None, att=None) -> Note:
    hdr = Header(
        title=None,
        date_text=None,
        date=d,
        date_source="header" if d else "none",
        attendees=att or [],
    )
    return Note(file=file, header=hdr, content_hash=h or f"hash-{file}")


def mention(file, line, owner, key, task=None, due=None, due_raw=None, checked=False, **kw):
    kind = kw.pop("owner_kind", None) or (
        "unassigned"
        if owner == "Unassigned"
        else "ambiguous"
        if owner.startswith("Ambiguous")
        else "person"
    )
    return Mention(
        file=file,
        line_no=line,
        syntax="checkbox",
        raw_line=f"- [ ] {owner} to {task or key}",
        owner_raw=owner.split()[0],
        owner=owner,
        owner_kind=kind,
        collaborators=kw.pop("collaborators", []),
        task=task or key,
        task_key=key,
        due=due,
        due_raw=due_raw,
        checked=checked,
        item_id=kw.pop("item_id"),
        **kw,
    )


def item(id_, owner, task, due=None, status="open", first=KICKOFF, latest=None, n=1, **kw):
    kind = kw.pop("owner_kind", None) or (
        "unassigned"
        if owner == "Unassigned"
        else "ambiguous"
        if owner.startswith("Ambiguous")
        else "person"
    )
    return Item(
        id=id_,
        id_key=f"{owner}|{task}",
        owner=owner,
        owner_kind=kind,
        collaborators=kw.pop("collaborators", []),
        task=task,
        due=due,
        due_raw=kw.pop("due_raw", None),
        status=status,
        done_manual=kw.pop("done_manual", False),
        first_file=first,
        latest_file=latest or first,
        mention_count=n,
    )


def sam_priya():
    """Real fixtures from DATA_MODEL 6.2 and 6.3: two items, three mentions each."""
    sam_key = "confirm cloud budget finance"
    pri_key = "send revised quote acme"
    sam = item(
        "b48cced6",
        "Sam Okafor",
        "confirm cloud budget with finance",
        due=date(2026, 9, 18),
        due_raw="by Friday",
        status="done",
        first=KICKOFF,
        latest=WEEKLY2,
        n=3,
    )
    pri = item(
        "cfc90787",
        "Priya Nair",
        "send revised quote to Acme",
        due=date(2026, 9, 11),
        due_raw="by Friday",
        status="done",
        first=KICKOFF,
        latest=WEEKLY1,
        n=3,
    )
    sid, pid = sam.id, pri.id
    ms = [
        mention(
            KICKOFF, 12, "Sam Okafor", sam_key, "confirm cloud budget with finance", item_id=sid
        ),
        mention(
            WEEKLY1,
            11,
            "Sam Okafor",
            sam_key,
            "confirm cloud budget with finance",
            due=date(2026, 9, 18),
            due_raw="by Friday",
            item_id=sid,
        ),
        mention(
            WEEKLY2,
            10,
            "Sam Okafor",
            sam_key,
            "confirm cloud budget with finance",
            checked=True,
            item_id=sid,
        ),
        mention(
            KICKOFF,
            9,
            "Priya Nair",
            pri_key,
            "send revised quote to Acme",
            due=date(2026, 9, 4),
            due_raw="by Friday",
            item_id=pid,
        ),
        mention(
            WEEKLY0,
            9,
            "Priya Nair",
            pri_key,
            "send revised quote to Acme",
            due=date(2026, 9, 11),
            due_raw="by Friday",
            item_id=pid,
        ),
        mention(
            WEEKLY1,
            9,
            "Priya Nair",
            pri_key,
            "send revised quote to Acme",
            checked=True,
            item_id=pid,
        ),
    ]
    notes = [
        note(KICKOFF, date(2026, 9, 1)),
        note(WEEKLY0, date(2026, 9, 8)),
        note(WEEKLY1, date(2026, 9, 15)),
        note(WEEKLY2, date(2026, 9, 22)),
    ]
    return notes, ms, [sam, pri]


@pytest.fixture
def st(tmp_path) -> Store:
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def raw_rows(path: Path, table: str, order: str) -> list[tuple]:
    c = sqlite3.connect(path)
    try:
        return c.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()  # noqa: S608
    finally:
        c.close()


# ---------------------------------------------------------------- S01, S20, S22
def test_s01_schema_pragmas_and_indexes(tmp_path):
    p = tmp_path / "new.db"
    s = Store(p)
    try:
        assert s._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        s.close()
    c = sqlite3.connect(p)
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
    c.close()
    assert {"meetings", "mentions", "items", "mentions_item", "items_owner"} <= names


def test_s01_reopen_existing_database_is_fine(tmp_path):
    p = tmp_path / "x.db"
    notes, ms, items = sam_priya()
    s = Store(p)
    s.apply_ingest(notes, ms, items)
    s.close()
    s2 = Store(p)
    try:
        assert s2.get_item("b48cced6") is not None
    finally:
        s2.close()


def test_s20_unwritable_path_raises_store_error(tmp_path):
    bad = tmp_path / "no_such_dir" / "x.db"
    with pytest.raises(StoreError):
        Store(bad)
    assert not bad.exists()
    assert not bad.parent.exists()


def test_s22_ingested_at_never_affects_items(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    notes, ms, items = sam_priya()
    s = Store(p)
    monkeypatch.setattr(store_mod, "_utc_now", lambda: "2026-10-22T09:00:00Z")
    s.apply_ingest(notes, ms, items)
    first = raw_rows(p, "items", "id")
    monkeypatch.setattr(store_mod, "_utc_now", lambda: "2027-01-01T00:00:00Z")
    s.apply_ingest(notes, ms, items)
    s.close()
    assert raw_rows(p, "items", "id") == first
    stamps = {r[0] for r in sqlite3.connect(p).execute("SELECT ingested_at FROM meetings")}
    assert stamps  # informational only


# ---------------------------------------------------------------- S02 .. S07
def test_first_ingest_counts_and_roundtrip(st):
    notes, ms, items = sam_priya()
    counts = st.apply_ingest(notes, ms, items)
    assert counts == IngestCounts(new=2, updated=0, unchanged=0)
    got = st.get_item("b48cced6")
    assert got == items[0]
    assert got.due == date(2026, 9, 18) and got.status == "done"
    assert st.get_item("cfc90787").mention_count == 3
    assert st.get_item("deadbeef") is None


def test_s02_s03_s04_reingest_identical(tmp_path):
    p = tmp_path / "t.db"
    notes, ms, items = sam_priya()
    s = Store(p)
    s.apply_ingest(notes, ms, items)
    items_before = raw_rows(p, "items", "id")
    mentions_before = raw_rows(p, "mentions", "file, line_no")
    ids_before = {i[0] for i in items_before}
    counts = s.apply_ingest(notes, ms, items)
    s.close()
    assert counts == IngestCounts(new=0, updated=0, unchanged=2)
    assert raw_rows(p, "items", "id") == items_before  # S03 all columns
    assert len(raw_rows(p, "mentions", "file, line_no")) == len(mentions_before) == 6  # S04
    assert {r[0] for r in raw_rows(p, "items", "id")} == ids_before  # S02


def test_s05_edit_changes_due_not_id(st):
    notes, ms, items = sam_priya()
    st.apply_ingest(notes, ms, items)
    new_pri = dataclasses.replace(items[1], due=date(2026, 9, 14), due_raw="by Monday")
    counts = st.apply_ingest(
        [note(WEEKLY0, date(2026, 9, 8), h="changed")], ms, [items[0], new_pri]
    )
    assert counts == IngestCounts(new=0, updated=1, unchanged=1)
    assert st.get_item("cfc90787").due == date(2026, 9, 14)
    assert st.get_item("b48cced6") == items[0]
    assert st.known_hashes()[WEEKLY0] == "changed"


def test_s06_unchanged_file_mentions_not_rewritten(tmp_path):
    p = tmp_path / "t.db"
    notes, ms, items = sam_priya()
    s = Store(p)
    s.apply_ingest(notes, ms, items)
    before = raw_rows(p, "mentions", "file, line_no")  # includes surrogate ids
    s.apply_ingest([], ms, items)  # no file re-read
    s.close()
    assert raw_rows(p, "mentions", "file, line_no") == before


def test_s04_reread_file_mentions_replaced_not_appended(st, tmp_path):
    notes, ms, items = sam_priya()
    st.apply_ingest(notes, ms, items)
    st.apply_ingest(notes, ms, items)  # every file re-read
    assert len(st.all_mentions()) == 6


def test_known_hashes_and_all_mentions_roundtrip(st):
    notes, ms, items = sam_priya()
    st.apply_ingest(notes, ms, items)
    assert st.known_hashes()[KICKOFF] == f"hash-{KICKOFF}"
    got = {(m.file, m.line_no): m for m in st.all_mentions()}
    assert len(got) == 6
    m = got[(WEEKLY1, 11)]
    assert m.due == date(2026, 9, 18) and m.due_raw == "by Friday"
    assert m.meeting_date == date(2026, 9, 15)
    assert got[(WEEKLY2, 10)].checked is True
    assert m.owner_kind == "person" and m.collaborators == []


def test_all_mentions_ordering_and_undated_first(st):
    notes = [note("untitled.md", None), note(KICKOFF, date(2026, 9, 1))]
    ms = [
        mention(KICKOFF, 2, "Sam Okafor", "a b", item_id="aaaaaaaa", meeting_date=None),
        mention("untitled.md", 5, "Sam Okafor", "c d", item_id="bbbbbbbb"),
    ]
    items = [item("aaaaaaaa", "Sam Okafor", "a b"), item("bbbbbbbb", "Sam Okafor", "c d")]
    st.apply_ingest(notes, ms, items)
    assert [m.file for m in st.all_mentions()] == ["untitled.md", KICKOFF]


# ---------------------------------------------------------------- S08 .. S13
def test_s08_mark_done(st):
    notes, ms, items = sam_priya()
    open_item = dataclasses.replace(items[1], status="open")
    st.apply_ingest(notes, ms, [items[0], open_item])
    assert st.mark_done("cfc90787") is True
    got = st.get_item("cfc90787")
    assert got.status == "done" and got.done_manual is True


def test_s09_manual_done_is_sticky(st):
    notes, ms, items = sam_priya()
    open_item = dataclasses.replace(items[1], status="open")
    st.apply_ingest(notes, ms, [items[0], open_item])
    st.mark_done("cfc90787")
    counts = st.apply_ingest(notes, ms, [items[0], open_item])  # note still shows open
    got = st.get_item("cfc90787")
    assert got.status == "done" and got.done_manual is True
    assert counts.new == 0


def test_s10_mark_done_already_done_or_unknown(st):
    notes, ms, items = sam_priya()
    st.apply_ingest(notes, ms, items)  # both already done via latest [x]
    before = st.get_item("b48cced6")
    assert st.mark_done("b48cced6") is False
    assert st.get_item("b48cced6") == before
    assert before.done_manual is False  # no-op must not flip the manual flag
    assert st.mark_done("ffffffff") is False


def test_mark_done_id_is_case_insensitive(st):
    notes, ms, items = sam_priya()
    st.apply_ingest(notes, ms, [items[0], dataclasses.replace(items[1], status="open")])
    assert st.mark_done("CFC90787") is True


def test_s11_checked_note_is_done_not_manual(st):
    notes, ms, items = sam_priya()
    st.apply_ingest(notes, ms, items)
    got = st.get_item("b48cced6")
    assert got.status == "done" and got.done_manual is False


def test_s12_missing_file_keeps_items_and_mentions(st):
    notes, ms, items = sam_priya()
    st.apply_ingest(notes, ms, items)
    # folder now lacks every file: caller passes stored mentions back unchanged
    counts = st.apply_ingest([], st.all_mentions(), items)
    assert counts.unchanged == 2
    assert st.get_item("b48cced6") is not None
    assert len(st.all_mentions()) == 6


def test_reingest_with_stored_mentions_keeps_links(st):
    notes, ms, items = sam_priya()
    st.apply_ingest(notes, ms, items)
    # a mention that arrives without an item link must fail the whole transaction
    stored = st.all_mentions()
    with pytest.raises(StoreError):
        st.apply_ingest([], [dataclasses.replace(m, item_id=None) for m in stored], items)
    assert len(st.all_mentions()) == 6  # rolled back


def test_s13_deleted_task_removes_item_only_if_no_mentions_left(st):
    notes, ms, items = sam_priya()
    st.apply_ingest(notes, ms, items)
    # WEEKLY2 re-read, Sam's line gone: item keeps 2 mentions
    ms2 = [m for m in ms if (m.file, m.line_no) != (WEEKLY2, 10)]
    sam2 = dataclasses.replace(items[0], mention_count=2, latest_file=WEEKLY1)
    st.apply_ingest([note(WEEKLY2, date(2026, 9, 22), h="v2")], ms2, [sam2, items[1]])
    assert st.get_item("b48cced6").mention_count == 2
    # now Priya's three files re-read with her lines gone, and Sam's only line removed too
    ms3 = [m for m in ms2 if m.owner == "Sam Okafor"]
    st.apply_ingest(
        [note(f, date(2026, 9, 1), h="v3") for f in (KICKOFF, WEEKLY0, WEEKLY1)],
        [m for m in ms3 if False],
        [],
    )
    assert st.get_item("cfc90787") is None
    assert st.get_item("b48cced6") is None
    assert len(st.all_mentions()) == 0


def test_manual_done_item_without_mentions_is_deleted(st):
    notes, ms, items = sam_priya()
    st.apply_ingest(notes, ms, [items[0], dataclasses.replace(items[1], status="open")])
    st.mark_done("cfc90787")
    st.apply_ingest([note(f, date(2026, 9, 1), h="x") for f in (KICKOFF, WEEKLY0, WEEKLY1)], [], [])
    assert st.get_item("cfc90787") is None


# ---------------------------------------------------------------- S14 .. S17, S19, S21
def test_s14_midway_failure_rolls_back_byte_identical(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    notes, ms, items = sam_priya()
    s = Store(p)
    s.apply_ingest(notes, ms, items)
    before = p.read_bytes()

    def boom(*a, **k):
        raise RuntimeError("injected")

    monkeypatch.setattr(Store, "_write_mentions", boom)
    changed = dataclasses.replace(items[0], task="different wording")
    with pytest.raises(StoreError):
        s.apply_ingest([note(KICKOFF, date(2026, 9, 1), h="new")], ms, [changed, items[1]])
    s.close()
    assert p.read_bytes() == before


def test_s14_after_failure_store_still_usable(st, monkeypatch):
    notes, ms, items = sam_priya()
    monkeypatch.setattr(Store, "_write_mentions", lambda *a, **k: 1 / 0)
    with pytest.raises(StoreError):
        st.apply_ingest(notes, ms, items)
    monkeypatch.undo()
    assert st.apply_ingest(notes, ms, items).new == 2


def test_s15_mention_with_missing_file_is_store_error(st):
    it = item("aaaaaaaa", "Sam Okafor", "x y")
    m = mention("ghost.md", 1, "Sam Okafor", "x y", item_id="aaaaaaaa")
    with pytest.raises(StoreError):
        st.apply_ingest([], [m], [it])
    assert st.get_item("aaaaaaaa") is None


def test_s15_mention_pointing_at_unknown_item_is_store_error(st):
    m = mention(KICKOFF, 1, "Sam Okafor", "x y", item_id="zzzzzzzz")
    with pytest.raises(StoreError):
        st.apply_ingest([note(KICKOFF, date(2026, 9, 1))], [m], [])
    assert st.known_hashes() == {}


def test_s16_overdue_status_is_rejected(st):
    notes, ms, items = sam_priya()
    bad = dataclasses.replace(items[0], status="overdue")  # type: ignore[arg-type]
    with pytest.raises(StoreError):
        st.apply_ingest(notes, ms, [bad, items[1]])
    assert st.get_item("b48cced6") is None and st.known_hashes() == {}


def test_s17_invalid_owner_kind_is_rejected(st):
    notes, ms, items = sam_priya()
    bad = dataclasses.replace(items[0], owner_kind="robot")  # type: ignore[arg-type]
    with pytest.raises(StoreError):
        st.apply_ingest(notes, ms, [bad, items[1]])
    bad_m = dataclasses.replace(ms[0], owner_kind="robot")  # type: ignore[arg-type]
    with pytest.raises(StoreError):
        st.apply_ingest(notes, [bad_m, *ms[1:]], items)


def test_s19_injection_owner_is_inert(st):
    notes, ms, items = sam_priya()
    st.apply_ingest(notes, ms, items)
    evil = "x'; DROP TABLE items;--"
    assert st.list_items(evil, None, None, TODAY).items == []
    assert st.open_items_for(evil) == []
    assert st.ambiguous_count(evil) == 0
    assert st.get_item(evil) is None
    assert st.mark_done(evil) is False
    assert st.get_item("b48cced6") is not None


def test_s19_source_has_no_string_built_values():
    src = Path(store_mod.__file__).read_text()
    assert "% (" not in src and ".format(" not in src
    assert 'f"SELECT' not in src and 'f"UPDATE' not in src and 'f"DELETE' not in src


def test_s21_locked_database_fails_cleanly(tmp_path):
    p = tmp_path / "t.db"
    notes, ms, items = sam_priya()
    s = Store(p, timeout=0.2)
    s.apply_ingest(notes, ms, items)
    before = p.read_bytes()
    other = sqlite3.connect(p, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")  # a second writer holds the lock
    try:
        with pytest.raises(StoreError):
            s.apply_ingest(notes, ms, [items[0], dataclasses.replace(items[1], task="z")])
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert p.read_bytes() == before
    assert s.apply_ingest(notes, ms, items).unchanged == 2  # recovers once unlocked
    s.close()


# ---------------------------------------------------------------- S18 / L-seed
def seed(st: Store) -> dict[str, str]:
    """The 8-item L-case table (TEST_PLAN 8). Returns label -> 8-hex id."""
    rows = [
        ("a1", "Sam Okafor", "cut cloud costs", date(2026, 10, 9), "open"),
        ("a2", "Sam Okafor", "propose on-call rotation", date(2026, 10, 15), "open"),
        ("a3", "Sam Okafor", "confirm cloud budget", date(2026, 9, 18), "done"),
        ("a4", "Anita Desai", "refresh brand kit", date(2026, 10, 22), "open"),
        ("a5", "Anita Desai", "audit colour contrast", date(2026, 10, 30), "open"),
        ("a6", "Priya Nair", "send revised quote", None, "open"),
        ("a7", "Ambiguous (Priya)", "own the hiring plan", None, "open"),
        ("a8", "Unassigned", "write the changelog", None, "open"),
    ]
    ids = {label: f"a{label[1]}000000" for label, *_ in rows}
    notes, ms, items = [], [], []
    for n, (label, owner, task, due, status) in enumerate(rows, start=1):
        f = f"2026-10-0{n}-seed.md"
        notes.append(note(f, date(2026, 10, n)))
        ms.append(mention(f, 3, owner, task, due=due, item_id=ids[label], checked=status == "done"))
        items.append(item(ids[label], owner, task, due=due, status=status, first=f))
    st.apply_ingest(notes, ms, items)
    return ids


@pytest.fixture
def seeded(st):
    return st, seed(st)


def labels(res: ListResult, ids: dict[str, str]) -> list[str]:
    inv = {v: k for k, v in ids.items()}
    return [inv[i.id] for i in res.items]


def test_l01_all_sorted_due_then_nodue_last(seeded):
    s, ids = seeded
    res = s.list_items(None, None, None, TODAY)
    assert labels(res, ids) == ["a3", "a1", "a2", "a4", "a5", "a6", "a7", "a8"]
    assert res.warnings == []


def test_l02_overdue(seeded):
    s, ids = seeded
    assert labels(s.list_items(None, "overdue", None, TODAY), ids) == ["a1", "a2"]


def test_l03_open_excludes_overdue_and_done(seeded):
    s, ids = seeded
    assert labels(s.list_items(None, "open", None, TODAY), ids) == ["a4", "a5", "a6", "a7", "a8"]


def test_l04_done(seeded):
    s, ids = seeded
    assert labels(s.list_items(None, "done", None, TODAY), ids) == ["a3"]


def test_l05_l06_due_before_strict(seeded):
    s, ids = seeded
    assert labels(s.list_items(None, None, date(2026, 10, 22), TODAY), ids) == ["a3", "a1", "a2"]
    assert labels(s.list_items(None, None, date(2026, 10, 23), TODAY), ids) == [
        "a3",
        "a1",
        "a2",
        "a4",
    ]


@pytest.mark.parametrize("arg", ["Sam Okafor", "sam okafor", "Sam", "SAM"])
def test_l07_l08_l09_sam(seeded, arg):
    s, ids = seeded
    res = s.list_items(arg, None, None, TODAY)
    assert labels(res, ids) == ["a3", "a1", "a2"]
    assert res.warnings == []


def test_l10_full_name_excludes_ambiguous_with_warning(seeded):
    s, ids = seeded
    res = s.list_items("Priya Nair", None, None, TODAY)
    assert labels(res, ids) == ["a6"]
    assert res.warnings == ['1 items owned by "Ambiguous (Priya)" not included']


def test_l11_bare_first_name_includes_ambiguous_and_warns(seeded):
    s, ids = seeded
    res = s.list_items("Priya", None, None, TODAY)
    assert labels(res, ids) == ["a6", "a7"]
    assert len(res.warnings) == 1 and "Priya" in res.warnings[0] and "shared" in res.warnings[0]


def test_l12_unassigned(seeded):
    s, ids = seeded
    assert labels(s.list_items("Unassigned", None, None, TODAY), ids) == ["a8"]
    assert labels(s.list_items("unassigned", None, None, TODAY), ids) == ["a8"]


def test_l13_l14_filters_combine_with_and(seeded):
    s, ids = seeded
    assert labels(s.list_items("Sam Okafor", "overdue", None, TODAY), ids) == ["a1", "a2"]
    assert labels(s.list_items(None, "overdue", date(2026, 10, 10), TODAY), ids) == ["a1"]


def test_l15_unknown_owner_empty_no_warning(seeded):
    s, _ = seeded
    res = s.list_items("Nobody", None, None, TODAY)
    assert res.items == [] and res.warnings == []


def test_l19_l20_today_moves_overdue_boundary(seeded):
    s, ids = seeded
    assert labels(s.list_items(None, "overdue", None, date(2026, 10, 9)), ids) == []
    assert labels(s.list_items(None, "overdue", None, date(2026, 10, 10)), ids) == ["a1"]
    assert labels(s.list_items(None, "overdue", None, date(2026, 10, 16)), ids) == ["a1", "a2"]
    assert "a1" in labels(s.list_items(None, "open", None, date(2026, 10, 9)), ids)


def test_overdue_is_never_stored(seeded, tmp_path):
    s, _ = seeded
    s.list_items(None, "overdue", None, TODAY)
    statuses = {i.status for i in s.list_items(None, None, None, TODAY).items}
    assert statuses <= {"open", "done"}


def test_invalid_status_is_usage_error(seeded):
    s, _ = seeded
    with pytest.raises(UsageError):
        s.list_items(None, "late", None, TODAY)


def test_list_sort_tiebreak_source_date_then_id(st):
    d = date(2026, 10, 1)
    notes = [note("2026-09-02-b.md", date(2026, 9, 2)), note("2026-09-01-a.md", date(2026, 9, 1))]
    ms = [
        mention("2026-09-02-b.md", 1, "Sam Okafor", "k1", due=d, item_id="11111111"),
        mention("2026-09-01-a.md", 1, "Sam Okafor", "k2", due=d, item_id="22222222"),
        mention("2026-09-01-a.md", 2, "Sam Okafor", "k3", due=d, item_id="00000003"),
    ]
    items = [
        item("11111111", "Sam Okafor", "k1", due=d, first="2026-09-02-b.md"),
        item("22222222", "Sam Okafor", "k2", due=d, first="2026-09-01-a.md"),
        item("00000003", "Sam Okafor", "k3", due=d, first="2026-09-01-a.md"),
    ]
    st.apply_ingest(notes, ms, items)
    got = [i.id for i in st.list_items(None, None, None, TODAY).items]
    assert got == ["00000003", "22222222", "11111111"]


def test_bare_first_name_shared_by_two_people_warns_even_without_ambiguous(st):
    notes = [note(KICKOFF, date(2026, 9, 1))]
    ms = [
        mention(KICKOFF, 1, "Priya Nair", "a b", item_id="aaaaaaaa"),
        mention(KICKOFF, 2, "Priya Shah", "c d", item_id="bbbbbbbb"),
        mention(KICKOFF, 3, "Priyanka Rao", "e f", item_id="cccccccc"),
    ]
    items = [
        item("aaaaaaaa", "Priya Nair", "a b"),
        item("bbbbbbbb", "Priya Shah", "c d"),
        item("cccccccc", "Priyanka Rao", "e f"),
    ]
    st.apply_ingest(notes, ms, items)
    res = st.list_items("Priya", None, None, TODAY)
    assert sorted(i.id for i in res.items) == ["aaaaaaaa", "bbbbbbbb"]  # not Priyanka
    assert len(res.warnings) == 1
    assert st.list_items("Priya Shah", None, None, TODAY).warnings == []


def test_wildcards_in_owner_do_not_match_everything(seeded):
    s, _ = seeded
    assert s.list_items("%", None, None, TODAY).items == []
    assert s.list_items("S_m", None, None, TODAY).items == []


# ---------------------------------------------------------------- helpers
def test_open_items_for_only_open_person_items(seeded):
    s, ids = seeded
    got = s.open_items_for("Sam Okafor")
    assert [i.id for i in got] == [ids["a1"], ids["a2"]]  # a3 done
    assert [i.id for i in s.open_items_for("sam okafor")] == [ids["a1"], ids["a2"]]
    assert s.open_items_for("Unassigned") == []
    assert s.open_items_for("Ambiguous (Priya)") == []
    assert s.open_items_for("Priya") == []  # bare names never match here


def test_ambiguous_count(seeded):
    s, _ = seeded
    assert s.ambiguous_count("Priya") == 1
    assert s.ambiguous_count("priya") == 1
    assert s.ambiguous_count("Rahul") == 0


def test_owners_distinct_sorted(seeded):
    s, _ = seeded
    assert s.owners() == [
        "Ambiguous (Priya)",
        "Anita Desai",
        "Priya Nair",
        "Sam Okafor",
        "Unassigned",
    ]


def test_collaborators_and_due_raw_roundtrip(st):
    notes = [note(KICKOFF, date(2026, 9, 1))]
    it = item(
        "aaaaaaaa",
        "Anita Desai",
        "agree on component API",
        collaborators=["Rahul Mehta", "Ambiguous (Rahul)"],
        due_raw="before cutover",
    )
    m = mention(
        KICKOFF,
        1,
        "Anita Desai",
        "agree component api",
        collaborators=["Rahul Mehta", "Ambiguous (Rahul)"],
        due_raw="before cutover",
        item_id="aaaaaaaa",
    )
    st.apply_ingest(notes, [m], [it])
    assert st.get_item("aaaaaaaa") == it
    assert st.all_mentions()[0].collaborators == ["Rahul Mehta", "Ambiguous (Rahul)"]
    assert st.all_mentions()[0].due is None and st.all_mentions()[0].due_raw == "before cutover"


def test_meeting_attendees_stored_as_json(st):
    n = note(KICKOFF, date(2026, 9, 1), att=["Priya Nair", "Sam Okafor"])
    st.apply_ingest([n], [], [])
    row = st._conn.execute("SELECT attendees, date_source FROM meetings").fetchone()
    assert row["attendees"] == '["Priya Nair", "Sam Okafor"]' and row["date_source"] == "header"
