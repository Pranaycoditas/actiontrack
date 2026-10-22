"""CLI tests for `list` (TEST_PLAN 8) and `done` (TEST_PLAN 9) on a seeded database."""

import re
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from actiontrack.cli import app, render_table
from actiontrack.models import Header, Item, Mention, Note
from actiontrack.store import Store
from ingest_helpers import NOTES, rows

runner = CliRunner()
TODAY = "2026-10-22"

# (key, owner, owner_kind, task, due, status, mention_count)
SEED = [
    ("a1", "Sam Okafor", "person", "cut cloud costs", date(2026, 10, 9), "open", 1),
    ("a2", "Sam Okafor", "person", "propose on-call rotation", date(2026, 10, 15), "open", 1),
    ("a3", "Sam Okafor", "person", "confirm cloud budget", date(2026, 9, 18), "done", 1),
    ("a4", "Anita Desai", "person", "refresh brand kit", date(2026, 10, 22), "open", 1),
    ("a5", "Anita Desai", "person", "audit colour contrast", date(2026, 10, 30), "open", 3),
    ("a6", "Priya Nair", "person", "send revised quote", None, "open", 1),
    ("a7", "Ambiguous (Priya)", "ambiguous", "own the hiring plan", None, "open", 1),
    ("a8", "Unassigned", "unassigned", "write the changelog", None, "open", 1),
]


def iid(key: str) -> str:
    """8-hex id for a seed key: a1 -> a1000000."""
    return f"{key}000000"


def build(db_path: Path, seed=SEED) -> None:
    notes, mentions, items = [], [], []
    for key, owner, kind, task, due, status, count in seed:
        file = f"2026-09-{int(key[1:]):02d}-{key}.md"
        notes.append(
            Note(
                file=file,
                header=Header(None, None, date(2026, 9, int(key[1:])), "header"),
                content_hash=f"h-{key}",
            )
        )
        mentions.append(
            Mention(
                file=file, line_no=1, syntax="checkbox", raw_line=task, owner_raw=None,
                owner=owner, owner_kind=kind, collaborators=[], task=task, task_key=task,
                due=due, due_raw=None, checked=status == "done",
                meeting_date=date(2026, 9, int(key[1:])), item_id=iid(key),
            )
        )  # fmt: skip
        items.append(
            Item(
                id=iid(key), id_key=task, owner=owner, owner_kind=kind, collaborators=[],
                task=task, due=due, due_raw=None, status=status, done_manual=False,
                first_file=file, latest_file=file, mention_count=count,
            )
        )  # fmt: skip
    with Store(db_path) as s:
        s.apply_ingest(notes, mentions, items)


@pytest.fixture
def seeded(tmp_path: Path) -> Path:
    p = tmp_path / "seed.db"
    build(p)
    return p


def run(db: Path, *args: str):
    return runner.invoke(app, [*args, "--db", str(db)])


def ids_of(out: str) -> list[str]:
    lines = out.strip().splitlines()[1:-1]  # drop header and footer
    return [ln.split()[0] for ln in lines]


def keys(result) -> list[str]:
    return [i[:2] for i in ids_of(result.stdout)]


def lst(db: Path, *args: str):
    return run(db, "list", "--today", TODAY, *args)


# ------------------------------------------------------------------ list
def test_l01_all_sorted(seeded):
    r = lst(seeded)
    assert r.exit_code == 0
    assert keys(r) == ["a3", "a1", "a2", "a4", "a5", "a6", "a7", "a8"]
    assert r.stdout.strip().splitlines()[-1] == "8 items"


def test_l02_overdue(seeded):
    assert keys(lst(seeded, "--status", "overdue")) == ["a1", "a2"]


def test_l03_open(seeded):
    assert keys(lst(seeded, "--status", "open")) == ["a4", "a5", "a6", "a7", "a8"]


def test_l04_done(seeded):
    assert keys(lst(seeded, "--status", "done")) == ["a3"]


def test_l05_due_before_strict(seeded):
    assert keys(lst(seeded, "--due-before", "2026-10-22")) == ["a3", "a1", "a2"]


def test_l06_due_before_next_day(seeded):
    assert keys(lst(seeded, "--due-before", "2026-10-23")) == ["a3", "a1", "a2", "a4"]


def test_l07_owner_full(seeded):
    assert keys(lst(seeded, "--owner", "Sam Okafor")) == ["a3", "a1", "a2"]


def test_l08_owner_case_insensitive(seeded):
    assert keys(lst(seeded, "--owner", "sam okafor")) == ["a3", "a1", "a2"]


def test_l09_owner_first_name(seeded):
    assert keys(lst(seeded, "--owner", "Sam")) == ["a3", "a1", "a2"]


def test_l10_owner_priya_full_warns(seeded):
    r = lst(seeded, "--owner", "Priya Nair")
    assert keys(r) == ["a6"]
    assert "Ambiguous (Priya)" in r.stderr
    assert "Ambiguous" not in r.stdout


def test_l11_owner_priya_first_name(seeded):
    r = lst(seeded, "--owner", "Priya")
    assert keys(r) == ["a6", "a7"]
    assert "shared first name" in r.stderr


def test_l12_unassigned(seeded):
    assert keys(lst(seeded, "--owner", "Unassigned")) == ["a8"]


def test_l13_owner_and_status(seeded):
    assert keys(lst(seeded, "--owner", "Sam Okafor", "--status", "overdue")) == ["a1", "a2"]


def test_l14_status_and_due_before(seeded):
    assert keys(lst(seeded, "--status", "overdue", "--due-before", "2026-10-10")) == ["a1"]


def test_l15_no_match(seeded):
    r = lst(seeded, "--owner", "Nobody")
    assert r.exit_code == 0
    assert r.stdout.strip() == "No items found."


def test_l16_bad_status(seeded):
    r = lst(seeded, "--status", "late")
    assert r.exit_code == 2
    assert "open" in r.stderr and "done" in r.stderr and "overdue" in r.stderr


def test_l17_bad_due_before(seeded):
    r = lst(seeded, "--due-before", "10/10/2026")
    assert r.exit_code == 2
    assert "--due-before" in r.stderr


def test_l18_bad_today(seeded):
    r = run(seeded, "list", "--today", "2026-13-01")
    assert r.exit_code == 2
    assert "--today" in r.stderr


def test_l19_due_today_not_overdue(seeded):
    r = run(seeded, "list", "--today", "2026-10-09")
    rows = {ln.split()[0][:2]: ln.split()[1] for ln in r.stdout.splitlines()[1:-1]}
    assert rows["a1"] == "open"
    assert r.stdout == run(seeded, "list", "--today", "2026-10-09").stdout


def test_l20_later_today(seeded):
    r = run(seeded, "list", "--today", "2026-10-16", "--status", "overdue")
    assert keys(r) == ["a1", "a2"]


def test_l21_columns_and_rendering(seeded):
    r = lst(seeded)
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["ID", "STATUS", "OWNER", "DUE", "TASK", "SOURCE"]
    by = {ln.split()[0][:2]: ln for ln in lines[1:-1]}
    assert "overdue" in by["a1"] and "done" in by["a3"] and " open " in by["a4"]
    assert "2026-09-05-a5.md (+2)" in by["a5"]
    assert "2026-09-04-a4.md" in by["a4"] and "(+" not in by["a4"]
    assert "Ambiguous (Priya)" in by["a7"] and "Unassigned" in by["a8"]
    assert " -  " in by["a6"]  # empty due


def test_render_table_singular_footer():
    it = Item(
        id="deadbeef", id_key="k", owner="Sam Okafor", owner_kind="person", collaborators=[],
        task="t", due=None, due_raw=None, status="open", done_manual=False,
        first_file="f.md", latest_file="f.md", mention_count=1,
    )  # fmt: skip
    out = render_table([it], date(2026, 10, 22))
    assert out.splitlines()[-1] == "1 item"
    assert render_table([], date(2026, 10, 22)) == "No items found."


def test_l22_empty_db(tmp_path):
    db = tmp_path / "empty.db"
    Store(db).close()
    r = lst(db)
    assert r.exit_code == 0 and r.stdout.strip() == "No items found."


def test_l23_missing_db_exit0_and_not_created(tmp_path):
    db = tmp_path / "nope.db"
    r = lst(db)
    assert r.exit_code == 0 and r.stdout.strip() == "No items found."
    assert not db.exists()


@pytest.fixture(scope="module")
def real_db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("real") / "real.db"
    assert runner.invoke(app, ["ingest", str(NOTES), "--db", str(path)]).exit_code == 0
    return path


def test_l24_real_notes(real_db):
    out = lst(real_db).stdout
    table = rows(out)
    assert table and len(table) == int(out.strip().splitlines()[-1].split()[0])
    for row in table:
        iid, status, owner, due = row[:4]
        assert re.fullmatch(r"[0-9a-f]{8}", iid)
        assert owner != "Priya" and owner != "Rahul"  # never a bare shared first name
        if status == "overdue":
            assert due != "-" and due < TODAY
        if due != "-" and due < TODAY and status != "done":
            assert status == "overdue"
    assert {r[1] for r in table} == {"open", "overdue", "done"}
    done = rows(lst(real_db, "--status", "done").stdout)
    assert done and all(r[1] == "done" for r in done)
    assert "Ambiguous (Priya)" in out


def test_l25_real_notes_deterministic(real_db):
    first = lst(real_db).stdout
    assert first == lst(real_db).stdout
    assert lst(real_db, "--status", "overdue").stdout == lst(real_db, "--status", "overdue").stdout


def test_list_output_deterministic_on_fixture(seeded):
    assert lst(seeded).stdout == lst(seeded).stdout


def test_list_uses_env_db(seeded, monkeypatch):
    monkeypatch.setenv("ACTIONTRACK_DB", str(seeded))
    r = runner.invoke(app, ["list", "--today", TODAY])
    assert r.exit_code == 0 and "8 items" in r.stdout


# ------------------------------------------------------------------ done
def status_of(db: Path, key: str) -> str:
    with Store(db) as s:
        item = s.get_item(iid(key))
        assert item is not None
        return item.status


def test_dn01_done(seeded):
    r = run(seeded, "done", iid("a1"))
    assert r.exit_code == 0
    assert r.stdout.strip() == f"Marked done: {iid('a1')}  Sam Okafor  cut cloud costs"
    assert "a1" in keys(lst(seeded, "--status", "done"))


def test_dn02_idempotent(seeded):
    run(seeded, "done", iid("a1"))
    r = run(seeded, "done", iid("a1"))
    assert r.exit_code == 0 and r.stdout.strip() == f"Already done: {iid('a1')}"
    assert status_of(seeded, "a1") == "done"


def test_dn02b_already_done_in_seed(seeded):
    r = run(seeded, "done", iid("a3"))
    assert r.exit_code == 0 and "Already done" in r.stdout


def test_dn03_unknown(seeded):
    r = run(seeded, "done", "ffffffff")
    assert r.exit_code == 2
    assert "error: no item with id ffffffff" in r.stderr


def test_dn04_uppercase(seeded):
    r = run(seeded, "done", iid("a1").upper())
    assert r.exit_code == 0 and "Marked done" in r.stdout
    assert status_of(seeded, "a1") == "done"


def test_dn05_prefix_rejected(seeded):
    r = run(seeded, "done", "a100")
    assert r.exit_code == 2
    assert status_of(seeded, "a1") == "open"


def test_dn06_no_argument(seeded):
    r = runner.invoke(app, ["done", "--db", str(seeded)])
    assert r.exit_code == 2


def test_dn07_ambiguous_and_unassigned(seeded):
    for key in ("a7", "a8"):
        r = run(seeded, "done", iid(key))
        assert r.exit_code == 0 and "Marked done" in r.stdout
        assert status_of(seeded, key) == "done"


def test_dn08_reingest(tmp_path):
    db = tmp_path / "real.db"
    ingest = ["ingest", str(NOTES), "--db", str(db)]
    assert runner.invoke(app, ingest).exit_code == 0
    open_row = rows(lst(db, "--status", "open").stdout)[0]
    iid = open_row[0]
    assert run(db, "done", iid).exit_code == 0
    ids_before = {r[0] for r in rows(lst(db).stdout)}
    assert runner.invoke(app, ingest).exit_code == 0  # note still shows the item open
    after = rows(lst(db).stdout)
    assert {r[0] for r in after} == ids_before
    assert [r[1] for r in after if r[0] == iid] == ["done"]
    with sqlite3.connect(db) as c:
        assert c.execute(
            "SELECT status, done_manual FROM items WHERE id = ?", (iid,)
        ).fetchone() == (
            "done",
            1,
        )


def test_dn09_followup_excludes_done(tmp_path):
    from actiontrack.drafts import InMemorySink
    from actiontrack.followup import run_followup
    from followup_seed import TODAY as F_TODAY
    from followup_seed import seed

    path = tmp_path / "f.db"
    ids = seed(path)
    sink = InMemorySink()
    with Store(path) as s:
        run_followup("Anita Desai", s, sink, F_TODAY, None)
    assert f"[{ids['a9']}]" in sink.drafts[0].body
    assert run(path, "done", ids["a9"]).exit_code == 0
    sink = InMemorySink()
    with Store(path) as s:
        run_followup("Anita Desai", s, sink, F_TODAY, None)
    assert f"[{ids['a9']}]" not in sink.drafts[0].body


def test_dn10_overdue_then_done(seeded):
    run(seeded, "done", iid("a1"))
    assert keys(lst(seeded, "--status", "overdue")) == ["a2"]


def test_dn11_whitespace_trimmed(seeded):
    r = run(seeded, "done", f"  {iid('a2')} ")
    assert r.exit_code == 0 and "Marked done" in r.stdout
    assert status_of(seeded, "a2") == "done"


def test_done_sets_done_manual(seeded):
    run(seeded, "done", iid("a1"))
    with Store(seeded) as s:
        row = s._conn.execute("SELECT done_manual FROM items WHERE id = ?", [iid("a1")])
        assert row.fetchone()[0] == 1


def test_done_missing_db_not_created(tmp_path):
    db = tmp_path / "nope.db"
    r = run(db, "done", "ffffffff")
    assert r.exit_code == 2 and "no item with id" in r.stderr
    assert not db.exists()


def test_dn12_racing_done(seeded):
    cmd = [sys.executable, "-m", "actiontrack", "done", iid("a1"), "--db", str(seeded)]
    procs = [
        subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(2)
    ]
    outs = [p.communicate() for p in procs]
    assert [p.returncode for p in procs] == [0, 0]
    texts = sorted(o[0].split(":")[0] for o in outs)
    assert texts == ["Already done", "Marked done"]
    assert status_of(seeded, "a1") == "done"
