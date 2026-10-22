"""End-to-end on the real notes/ (TEST_PLAN 12, E01-E17), through the CLI."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from actiontrack import cli
from actiontrack.cli import app
from ingest_helpers import NOTES, ROOT, TODAY, ingest, lst, rows, runner, skipped_section
from ingest_helpers import summary_numbers as nums

SKIPS = {"2026-09-09-notes-final-v2.md", "scratch.md", "2026-09-19-offsite-draft.txt"}
GOLDEN = ROOT / "tests" / "golden" / "list_2026-10-22.txt"


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("e2e") / "a.db"
    assert ingest(path).exit_code == 0
    return path


@pytest.fixture(scope="module")
def table(db) -> list[list[str]]:
    r = lst(db)
    assert r.exit_code == 0
    return rows(r.stdout)


def find(table, needle: str, owner: str | None = None) -> list[list[str]]:
    return [r for r in table if needle.lower() in r[4].lower() and (owner is None or r[2] == owner)]


def one(table, needle: str, owner: str | None = None) -> list[str]:
    hits = find(table, needle, owner)
    assert len(hits) == 1, (needle, hits)
    return hits[0]


# ------------------------------------------------------------------ E01 / E02


def test_e01_ingest_skips_and_warnings(tmp_path):
    r = ingest(tmp_path / "a.db")
    assert r.exit_code == 0
    assert set(skipped_section(r.stdout)) == SKIPS
    for name in (
        "untitled.md",
        "2026-10-03-sales-pipeline.md",
        "2026-09-23-standup.md",
        "2026-09-30-q4-offsite.md",
    ):
        assert name in r.stderr, name


def test_e02_ingest_twice(tmp_path):
    db = tmp_path / "a.db"
    first = ingest(db)
    before = lst(db).stdout
    second = ingest(db)
    n = nums(second.stdout)
    assert (n["new"], n["updated"], n["unchanged"]) == (0, 0, nums(first.stdout)["unique"])
    assert lst(db).stdout == before


# ------------------------------------------------------------------ E03 golden


def test_e03_golden_snapshot(db):
    if not GOLDEN.exists():
        pytest.skip(f"golden file {GOLDEN.relative_to(ROOT)} not created yet (awaiting review)")
    assert lst(db).stdout == GOLDEN.read_text()


# ------------------------------------------------------------------ E04..E08


def test_e04_duplicates_appear_once(table):
    cases = [
        # (needle, owner, status, due, merged mentions)
        ("confirm cloud budget", "Sam Okafor", "done", "2026-09-18", True),
        ("send the revised quote", "Priya Nair", "done", "2026-09-11", True),
        ("share updated wireframes", "Anita Desai", "overdue", "2026-09-24", True),
        ("freeze invoice edits", "Karan Joshi", "open", "-", True),
        ("refund affected customers", "Karan Joshi", "open", "-", False),
        ("deploy the beta to staging", "Rahul Mehta", "done", "2026-10-07", True),
        ("renewal call with Acme", "Meera Iyer", "done", "2026-09-30", True),
        ("export last quarter invoices", "Karan Joshi", "done", "2026-09-10", True),
        ("notify customers", "Priya Nair", "done", "2026-10-05", True),
    ]
    for needle, owner, status, due, merged in cases:
        row = one(table, needle, owner)
        assert (row[1], row[3]) == (status, due), (needle, row)
        assert ("(+" in row[5]) is merged, (needle, row)


def test_e05_no_guessing(db):
    r = lst(db, "--owner", "Priya")
    table = rows(r.stdout)
    ambiguous = {t[4] for t in table if t[2] == "Ambiguous (Priya)"}
    for needle in (
        "sign off the cutover checklist",  # 09-17, both Priyas present
        "circulate the go/no-go summary",  # 10-08, the un-initialled line
        "own the hiring plan",  # 09-30 offsite, all nine present
        "send the slides",  # untitled.md, no attendees
    ):
        assert any(needle in t for t in ambiguous), needle
        assert all(t[2] == "Ambiguous (Priya)" for t in table if needle in t[4])
    # Rahul side, never attributed to a full name
    rahul = rows(lst(db, "--owner", "Rahul").stdout)
    for needle in (
        "rebase the feature branch",
        "prepare the architecture overview",
        "review Anita",
    ):
        hit = [t for t in rahul if needle in t[4]]
        assert len(hit) == 1 and hit[0][2] == "Ambiguous (Rahul)", needle
    # the explicit initials resolve
    full = rows(lst(db, "--owner", "Priya Shah").stdout)
    assert any("run the invoice rounding tests" in t[4] for t in full)


def test_e06_traps_excluded(db, table):
    text = lst(db).stdout.lower()
    for needle in ("buy hardware tokens", "remediate finding", "book the venue"):
        assert needle not in text
    assert len(find(table, "refund affected customers")) == 1


def test_e07_non_deadlines(table):
    assert one(table, "freeze invoice edits")[3] == "-"
    assert one(table, "snapshot the production DB")[3] == "-"  # "before cutover" is not a date
    assert one(table, "schedule cutover for saturday")[3] == "-"
    assert one(table, "demo the portal to Acme")[3] == "-"


def test_e08_relative_dates_use_meeting_date(db):
    seen = {}
    for today in ("2026-09-02", "2026-10-22", "2027-03-01"):
        r = lst(db, today=today)
        assert r.exit_code == 0
        seen[today] = rows(r.stdout)
    dues = {t: [(r[0], r[3], r[4]) for r in rs] for t, rs in seen.items()}
    # only the sort could differ, never a due value
    keyed = {t: sorted(v) for t, v in dues.items()}
    assert keyed["2026-09-02"] == keyed["2026-10-22"] == keyed["2027-03-01"]
    # 2026-09-01 (Tuesday) "by Friday" -> 2026-09-04 whatever today is
    for rs in seen.values():
        priya_first = [r for r in rs if "send the revised quote" in r[4]]
        assert priya_first and priya_first[0][3] == "2026-09-11"  # latest non-empty (09-08)
    statuses = {t: {r[0]: r[1] for r in rs} for t, rs in seen.items()}
    assert statuses["2026-09-02"] != statuses["2027-03-01"]


# ------------------------------------------------------------------ E09..E13


def test_e09_overdue(db):
    r = lst(db, "--status", "overdue")
    rs = rows(r.stdout)
    assert rs
    assert all(x[1] == "overdue" and x[3] != "-" and x[3] < TODAY for x in rs)


def _pick_overdue(db) -> list[str]:
    return rows(lst(db, "--status", "overdue").stdout)[0]


def test_e10_e11_done_then_reingest(tmp_path):
    db = tmp_path / "a.db"
    ingest(db)
    target = _pick_overdue(db)
    iid = target[0]
    r = runner.invoke(app, ["done", iid, "--db", str(db)])
    assert r.exit_code == 0 and "Marked done" in r.stdout
    assert iid not in lst(db, "--status", "overdue").stdout
    assert iid in lst(db, "--status", "done").stdout
    before_ids = {x[0] for x in rows(lst(db).stdout)}
    again = ingest(db)
    assert again.exit_code == 0
    assert iid in lst(db, "--status", "done").stdout
    assert {x[0] for x in rows(lst(db).stdout)} == before_ids


class Recorder:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name, args):
        self.calls.append((name, args))
        return {"draft_id": f"r-{len(self.calls)}"}


def test_e12_followup_matches_list(db, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(cli, "get_mcp_client", lambda: rec)
    r = runner.invoke(app, ["followup", "Anita Desai", "--db", str(db), "--today", TODAY])
    assert r.exit_code == 0 and "nothing was sent" in r.stdout
    assert len(rec.calls) == 1
    mine = rows(lst(db, "--owner", "Anita Desai").stdout)
    over = sum(1 for x in mine if x[1] == "overdue")
    opn = sum(1 for x in mine if x[1] == "open")
    subject = rec.calls[0][1]["subject"]
    assert subject == f"Action items follow-up: Anita Desai ({over} overdue, {opn} open)"


def test_e13_full_loop(tmp_path, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(cli, "get_mcp_client", lambda: rec)
    db = tmp_path / "a.db"
    assert ingest(db).exit_code == 0
    assert lst(db).exit_code == 0
    iid = _pick_overdue(db)[0]
    assert runner.invoke(app, ["done", iid, "--db", str(db)]).exit_code == 0
    r = runner.invoke(app, ["followup", "Sam Okafor", "--db", str(db), "--today", TODAY])
    assert r.exit_code == 0
    assert ingest(db).exit_code == 0
    assert iid in lst(db, "--status", "done").stdout
    assert len(rec.calls) <= 1


# ------------------------------------------------------------------ E14..E17


def test_e14_robustness(tmp_path):
    base_db = tmp_path / "base.db"
    ingest(base_db)
    base_list = lst(base_db).stdout
    base_numbers = nums(ingest(base_db).stdout)

    src = tmp_path / "notes"
    shutil.copytree(NOTES, src)
    (src / "x-truncated-yaml.md").write_text("---\ntitle: Broken\ndate: 2026-09-1")
    (src / "x-only-dashes.md").write_text("---")
    (src / "x-huge-line.md").write_text(
        "# Meeting: Huge\nDate: 2026-09-01\nAttendees: Sam Okafor\n\n"
        + "x" * (5 * 1024 * 1024)
        + "\n- [ ] Sam to survive the huge line\n"
    )
    db = tmp_path / "e14.db"
    started = time.time()
    r = ingest(db, src)
    assert time.time() - started < 30
    assert r.exit_code == 0 and "Traceback" not in r.output
    n = nums(r.stdout)
    assert n["scanned"] == base_numbers["scanned"] + 3
    assert n["scanned"] == n["ingested"] + n["skipped"]
    for name in ("x-truncated-yaml.md", "x-only-dashes.md"):
        assert name in r.stdout or name in r.stderr, name  # skipped or warned
    # the 5 MB line is just text: the note is ingested and its real action line is kept
    assert "survive the huge line" in lst(db).stdout
    # originals unchanged: every base row is still there, byte for byte
    base_rows = {x[0]: x[1:5] for x in rows(base_list)}
    new_rows = {x[0]: x[1:5] for x in rows(lst(db).stdout)}
    for iid, vals in base_rows.items():
        assert new_rows[iid] == vals


def test_e15_performance(tmp_path):
    db = tmp_path / "a.db"
    t0 = time.time()
    assert ingest(db).exit_code == 0
    assert time.time() - t0 < 5
    t0 = time.time()
    assert lst(db).exit_code == 0
    assert time.time() - t0 < 1


def test_e16_python_dash_m_matches_script(db):
    args = ["list", "--db", str(db), "--today", TODAY]
    via_module = subprocess.run(
        [sys.executable, "-m", "actiontrack", *args], capture_output=True, text=True, cwd=ROOT
    )
    assert via_module.returncode == 0
    assert via_module.stdout.rstrip("\n") == lst(db).stdout.rstrip("\n")
    script = Path(sys.executable).parent / "actiontrack"
    if script.exists():
        via_script = subprocess.run([str(script), *args], capture_output=True, text=True)
        assert via_script.stdout == via_module.stdout


def test_e17_code_quality_gates():
    ruff = Path(sys.executable).parent / "ruff"
    if not ruff.exists():
        pytest.skip("ruff not installed")
    for cmd in (["check", "."], ["format", "--check", "."]):
        r = subprocess.run([str(ruff), *cmd], capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0, r.stdout + r.stderr
