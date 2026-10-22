"""Ingest orchestration and summary (TEST_PLAN 7, I01-I21)."""

from __future__ import annotations

import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from actiontrack.cli import app
from actiontrack.errors import UsageError
from actiontrack.ingest import run_ingest
from actiontrack.store import Store
from ingest_helpers import NOTES, ingest, lst, runner, skipped_section, summary_numbers

GOOD = "# Meeting: T\nDate: 2026-09-01\nAttendees: Sam Okafor, Anita Desai\n\n"
EXPECTED_SKIPS = {
    "2026-09-09-notes-final-v2.md": "empty file (0 bytes)",
    "scratch.md": "not text (binary content)",
    "2026-09-19-offsite-draft.txt": "not a .md file",
}


@pytest.fixture(scope="module")
def real_run(tmp_path_factory):
    db = tmp_path_factory.mktemp("real") / "a.db"
    r = ingest(db)
    return r, db


def warnings_for(r, name: str) -> list[str]:
    return [ln for ln in r.stderr.splitlines() if name in ln]


def test_i01_i02_skipped_exactly_three_with_reasons(real_run):
    r, _ = real_run
    assert r.exit_code == 0, r.output
    assert skipped_section(r.stdout) == EXPECTED_SKIPS
    # each on its own line
    for name, reason in EXPECTED_SKIPS.items():
        assert any(name in ln and reason in ln for ln in r.stdout.splitlines())


def test_i03_untitled_warning(real_run):
    r, _ = real_run
    w = " ".join(warnings_for(r, "untitled.md"))
    assert "no date, no attendees" in w
    assert "2 items" in w and "relative due dates unresolved" in w


def test_i04_sales_pipeline_filename_date(real_run):
    r, db = real_run
    assert warnings_for(r, "2026-10-03-sales-pipeline.md")
    with sqlite3.connect(db) as c:
        row = c.execute(
            "SELECT meeting_date, date_source FROM meetings WHERE file = ?",
            ("2026-10-03-sales-pipeline.md",),
        ).fetchone()
    assert row == ("2026-10-03", "filename")


def test_i05_standup_rahul_ambiguous(real_run):
    r, db = real_run
    w = " ".join(warnings_for(r, "2026-09-23-standup.md"))
    assert "Rahul" in w and "ambiguous" in w
    with sqlite3.connect(db) as c:
        owner = c.execute(
            "SELECT owner FROM mentions WHERE file = ? AND task LIKE 'rebase%'",
            ("2026-09-23-standup.md",),
        ).fetchone()
    assert owner == ("Ambiguous (Rahul)",)


def test_i06_offsite_warns_priya_and_rahul(real_run):
    r, _ = real_run
    w = " ".join(warnings_for(r, "2026-09-30-q4-offsite.md"))
    assert "Priya" in w and "Rahul" in w


def test_i07_finance_sync_no_format_warnings(real_run):
    r, _ = real_run
    assert warnings_for(r, "2026-10-02-finance-sync.md") == []


def test_i08_counts_reconcile(real_run):
    r, _ = real_run
    n = summary_numbers(r.stdout)
    assert n["scanned"] == n["ingested"] + n["skipped"] == 36
    assert n["found"] == n["unique"] + n["merged"]
    assert n["new"] == n["unique"] and n["updated"] == 0 and n["unchanged"] == 0


def test_i09_only_malformed(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    for name in EXPECTED_SKIPS:
        shutil.copy(NOTES / name, src / name)
    r = ingest(tmp_path / "a.db", src)
    assert r.exit_code == 0
    assert skipped_section(r.stdout) == EXPECTED_SKIPS
    assert summary_numbers(r.stdout)["found"] == 0


def test_i10_empty_folder(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    r = ingest(tmp_path / "a.db", src)
    assert r.exit_code == 0
    assert "Scanned 0 files" in r.stdout
    assert "Skipped files" not in r.stdout and "Warnings" not in r.stdout + r.stderr


def test_i11_one_good_four_malformed(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "good.md").write_text(GOOD + "- [ ] Sam to ship it by Friday\n")
    (src / "empty.md").write_bytes(b"")
    (src / "bin.md").write_bytes(b"\x00\x01\xff")
    (src / "x.txt").write_text("- [ ] Sam to nothing")
    (src / "bad.md").write_bytes(b"ok \xff\xfe")
    db = tmp_path / "a.db"
    r = ingest(db, src)
    assert r.exit_code == 0
    assert set(skipped_section(r.stdout)) == {"empty.md", "bin.md", "x.txt", "bad.md"}
    assert "ship it" in lst(db).stdout


def test_i12_malformed_first_does_not_stop_run(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "0-bad.md").write_bytes(b"")
    (src / "1-good.md").write_text(GOOD + "- [ ] Sam to ship it\n")
    r = ingest(tmp_path / "a.db", src)
    assert r.exit_code == 0 and summary_numbers(r.stdout)["found"] == 1


def test_i12b_parse_exception_becomes_skip(tmp_path, monkeypatch):
    src = tmp_path / "in"
    src.mkdir()
    (src / "1-boom.md").write_text(GOOD + "- [ ] Sam to boom\n")
    (src / "2-good.md").write_text(GOOD + "- [ ] Anita to fine\n")
    import actiontrack.ingest as mod

    real = mod.resolve_due

    def flaky(phrase, meeting):
        raise ValueError("kaboom")

    monkeypatch.setattr(mod, "resolve_due", flaky)
    db = tmp_path / "a.db"
    r = ingest(db, src)
    assert r.exit_code == 0
    assert skipped_section(r.stdout)["1-boom.md"] == "parse error: kaboom"
    assert "Traceback" not in r.output
    monkeypatch.setattr(mod, "resolve_due", real)


def test_i13_missing_folder_exit_2_no_db(tmp_path):
    db = tmp_path / "a.db"
    r = ingest(db, tmp_path / "nope")
    assert r.exit_code == 2 and "error:" in r.stderr
    assert not db.exists()
    f = tmp_path / "file.md"
    f.write_text("x")
    r = ingest(db, f)
    assert r.exit_code == 2 and not db.exists()


def test_run_ingest_raises_usage_error(tmp_path):
    with Store(tmp_path / "a.db") as s, pytest.raises(UsageError):
        run_ingest(tmp_path / "nope", s)


def test_i14_not_recursive(tmp_path):
    src = tmp_path / "in"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "deep.md").write_text(GOOD + "- [ ] Sam to hide\n")
    (src / "top.md").write_text(GOOD + "- [ ] Sam to show\n")
    r = ingest(tmp_path / "a.db", src)
    assert "deep.md" not in r.output
    assert summary_numbers(r.stdout)["scanned"] == 1


def test_i15_same_date_empty_and_standup(real_run):
    r, db = real_run
    sk = skipped_section(r.stdout)
    assert "2026-09-09-notes-final-v2.md" in sk and "2026-09-09-qa-standup.md" not in sk
    with sqlite3.connect(db) as c:
        assert c.execute(
            "SELECT count(*) FROM meetings WHERE file = '2026-09-09-qa-standup.md'"
        ).fetchone() == (1,)


def test_i16_saturday_notes_no_warning(real_run):
    r, db = real_run
    assert warnings_for(r, "2026-10-10-sales-weekly.md") == []
    with sqlite3.connect(db) as c:
        d = c.execute("SELECT meeting_date FROM meetings WHERE file LIKE '2026-10-10%'").fetchone()
    assert d == ("2026-10-10",)


def test_i17_stream_split(real_run):
    r, _ = real_run
    assert "Warnings:" in r.stderr and "untitled.md" in r.stderr
    assert "Warnings" not in r.stdout and "untitled.md" not in r.stdout.split("Skipped files:")[0]
    assert r.stdout.startswith("Scanned 36 files in ")
    assert "Skipped files:" in r.stdout


def test_i18_db_option_elsewhere(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    other = tmp_path / "elsewhere"
    other.mkdir()
    r = ingest(other / "x.db", NOTES)
    assert r.exit_code == 0
    assert (other / "x.db").exists()
    assert list(cwd.iterdir()) == []


def test_default_db_in_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ACTIONTRACK_DB", raising=False)
    r = runner.invoke(app, ["ingest", str(NOTES)])
    assert r.exit_code == 0 and (tmp_path / "actiontrack.db").exists()


def test_i19_db_flag_beats_env(tmp_path, monkeypatch):
    env_db, flag_db = tmp_path / "env.db", tmp_path / "flag.db"
    monkeypatch.setenv("ACTIONTRACK_DB", str(env_db))
    assert ingest(flag_db).exit_code == 0
    assert flag_db.exists() and not env_db.exists()
    r = runner.invoke(app, ["ingest", str(NOTES)])  # env alone
    assert r.exit_code == 0 and env_db.exists()


def test_i20_no_traceback(real_run):
    r, _ = real_run
    assert "Traceback" not in r.stdout + r.stderr


def test_i21_hostile_content(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    long_task = "word " * 2000
    body = (
        GOOD
        + f"- [ ] Sam to {long_task.strip()}\n"
        + "- [ ] Anita to \U0001f680 launch שלום السلام now\n"
    )
    (src / "h.md").write_text(body, encoding="utf-8")
    db = tmp_path / "a.db"
    r = ingest(db, src)
    assert r.exit_code == 0 and "Traceback" not in r.output
    with sqlite3.connect(db) as c:
        tasks = [t for (t,) in c.execute("SELECT task FROM mentions ORDER BY line_no")]
    assert tasks[0] == long_task.strip() and len(tasks[0]) >= 9999
    assert "\U0001f680 launch שלום السلام" in tasks[1]


# ------------------------------------------------------------------ idempotence


def dump(db: Path) -> dict[str, list]:
    with sqlite3.connect(db) as c:
        return {
            "items": c.execute("SELECT * FROM items ORDER BY id").fetchall(),
            "mentions": c.execute(
                "SELECT item_id, file, line_no, syntax, raw_line, owner_raw, owner, owner_kind,"
                " collaborators, task, task_key, due, due_raw, checked FROM mentions"
                " ORDER BY file, line_no"
            ).fetchall(),
            "meetings": c.execute(
                "SELECT file, title, meeting_date, date_source, attendees, content_hash"
                " FROM meetings ORDER BY file"
            ).fetchall(),
        }


def test_reingest_unchanged_identical(tmp_path):
    db = tmp_path / "a.db"
    first = ingest(db)
    before = dump(db)
    second = ingest(db)
    after = dump(db)
    n1, n2 = summary_numbers(first.stdout), summary_numbers(second.stdout)
    assert (n2["new"], n2["updated"], n2["unchanged"]) == (0, 0, n1["unique"])
    assert n2["found"] == n1["found"] and n2["unique"] == n1["unique"]
    assert before == after  # IDs, row counts and every column, no duplicate rows
    with sqlite3.connect(db) as c:
        n_items = c.execute("SELECT count(*) FROM items").fetchone()[0]
    assert n_items == n1["unique"]
    assert skipped_section(second.stdout) == EXPECTED_SKIPS


def test_edit_one_file_updates_without_id_change(tmp_path):
    src = tmp_path / "notes"
    shutil.copytree(NOTES, src)
    db = tmp_path / "a.db"
    ingest(db, src)
    before = dump(db)
    target = src / "2026-09-15-quote-portal-weekly.md"
    text = target.read_text()
    assert "finance by Friday" in text
    target.write_text(text.replace("finance by Friday", "finance by Monday"))
    r = ingest(db, src)
    n = summary_numbers(r.stdout)
    assert (n["new"], n["updated"]) == (0, 1) and n["unchanged"] == n["unique"] - 1
    after = dump(db)
    assert {i[0] for i in before["items"]} == {i[0] for i in after["items"]}
    assert len(before["mentions"]) == len(after["mentions"])


def test_removed_file_items_kept(tmp_path):
    src = tmp_path / "notes"
    shutil.copytree(NOTES, src)
    db = tmp_path / "a.db"
    ingest(db, src)
    before = dump(db)
    (src / "untitled.md").unlink()
    r = ingest(db, src)
    assert r.exit_code == 0
    assert dump(db) == before  # D10: stored mentions and items stay
    assert summary_numbers(r.stdout)["found"] == len(before["mentions"])


def test_ids_independent_of_clock(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    ingest(a)
    ingest(b)
    assert dump(a)["items"] == dump(b)["items"]


def test_store_failure_exit_1(tmp_path):
    bad = tmp_path / "missing-dir" / "a.db"
    r = ingest(bad)
    assert r.exit_code == 1 and "error:" in r.stderr and "Traceback" not in r.output


def test_summary_shape(tmp_path):
    db = tmp_path / "a.db"
    r = ingest(db)
    lines = r.stdout.splitlines()
    assert re.fullmatch(r"Scanned 36 files in .*notes", lines[0])
    assert re.fullmatch(r"  Ingested:\s+33 notes", lines[1])
    assert re.fullmatch(r"  Skipped:\s+3 files", lines[2])
    assert re.match(r"  Items:\s+\d+ found -> \d+ unique \(\d+ duplicates merged\)", lines[3])
    assert re.fullmatch(r"\s+new \d+, updated 0, unchanged 0", lines[4])
    assert lines[5] == "" and lines[6] == "Skipped files:"
    assert lst(db).exit_code == 0


def test_table_due_column_is_a_deadline(tmp_path):
    """A table's Due cell is a deadline even with no `by` (found on the real offsite note)."""
    src = tmp_path / "in"
    src.mkdir()
    (src / "t.md").write_text(
        GOOD
        + "| Owner | Action | Due |\n|---|---|---|\n"
        + "| Anita | Refresh the kit | 2026-10-09 |\n"
        + "| Sam | Tidy the wiki | Friday |\n"
        + "| Sam | Book the room | |\n"
    )
    db = tmp_path / "a.db"
    assert ingest(db, src).exit_code == 0
    with sqlite3.connect(db) as c:
        got = {t: (d, raw) for t, d, raw in c.execute("SELECT task, due, due_raw FROM mentions")}
    assert got["Refresh the kit"] == ("2026-10-09", "2026-10-09")
    assert got["Tidy the wiki"][0] == "2026-09-04"  # Friday after Tuesday 2026-09-01
    assert got["Book the room"] == (None, None)
