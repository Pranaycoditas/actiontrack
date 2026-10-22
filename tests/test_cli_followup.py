"""CLI `followup` (SPEC 3.4)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from actiontrack import cli
from actiontrack.cli import app
from actiontrack.errors import SinkUnavailable
from followup_seed import seed

runner = CliRunner()
BASE = ["--today", "2026-10-22"]


class Client:
    def __init__(self, result=None, exc=None):
        self.calls: list[tuple[str, dict]] = []
        self.result, self.exc = result or {"draft_id": "r-8812345"}, exc

    def __call__(self, name, args):
        self.calls.append((name, args))
        if self.exc:
            raise self.exc
        return self.result


@pytest.fixture
def dbp(tmp_path):
    seed(tmp_path / "t.db")
    return str(tmp_path / "t.db")


@pytest.fixture
def client(monkeypatch):
    c = Client()
    monkeypatch.setattr(cli, "get_mcp_client", lambda: c)
    return c


def invoke(dbp, *args):
    return runner.invoke(app, ["followup", *args, "--db", dbp, *BASE])


def test_success_output_matches_spec(dbp, client):
    r = invoke(dbp, "Anita Desai")
    assert r.exit_code == 0
    assert r.stdout.splitlines() == [
        "Draft created for Anita Desai (To: <blank>): 1 overdue, 3 open",
        "Draft id: r-8812345 (review it in Gmail Drafts; nothing was sent)",
    ]
    assert len(client.calls) == 1
    name, args = client.calls[0]
    assert name == "create_draft" and args["to"] == ""
    assert args["subject"] == "Action items follow-up: Anita Desai (1 overdue, 3 open)"


def test_email_map_sets_to(dbp, client, tmp_path):
    m = tmp_path / "m.csv"
    m.write_text("owner,email\nAnita Desai,anita@example.com\n")
    r = invoke(dbp, "Anita Desai", "--email-map", str(m))
    assert "(To: anita@example.com)" in r.stdout
    assert client.calls[0][1]["to"] == "anita@example.com"


def test_f16_bad_map_exit_2_no_drafts(dbp, client, tmp_path):
    r = invoke(dbp, "Anita Desai", "--email-map", str(tmp_path / "missing.csv"))
    assert r.exit_code == 2 and client.calls == []
    bad = tmp_path / "bad.csv"
    bad.write_text("name,mail\nA,b\n")
    r = invoke(dbp, "Anita Desai", "--email-map", str(bad))
    assert r.exit_code == 2 and client.calls == []


def test_f18_dry_run_prints_email_no_client(dbp, client):
    r = invoke(dbp, "Anita Desai", "--dry-run")
    assert r.exit_code == 0 and client.calls == []
    assert "Subject: Action items follow-up: Anita Desai (1 overdue, 3 open)" in r.stdout
    assert "Hi Anita," in r.stdout and "Thanks," in r.stdout
    assert "Draft created" not in r.stdout


def test_f19_twice_two_drafts(dbp, client):
    assert invoke(dbp, "Anita Desai").exit_code == 0
    assert invoke(dbp, "Anita Desai").exit_code == 0
    assert len(client.calls) == 2


def test_f20_unavailable_exit_1(dbp, monkeypatch):
    c = Client(exc=SinkUnavailable("Gmail connector is not authorized"))
    monkeypatch.setattr(cli, "get_mcp_client", lambda: c)
    r = invoke(dbp, "Anita Desai")
    assert r.exit_code == 1 and len(c.calls) == 1
    assert "not authorized" in r.stderr and "Draft created" not in r.stdout


def test_default_factory_raises_unavailable_with_instructions(dbp):
    r = invoke(dbp, "Anita Desai")  # real get_mcp_client, no monkeypatch
    assert r.exit_code == 1
    assert "authorize" in r.stderr.lower() and "gmail" in r.stderr.lower()
    assert "Draft created" not in r.stdout


def test_f21_draft_error_exit_1_no_retry(dbp, monkeypatch):
    c = Client(exc=ValueError("rejected"))
    monkeypatch.setattr(cli, "get_mcp_client", lambda: c)
    r = invoke(dbp, "Anita Desai")
    assert r.exit_code == 1 and len(c.calls) == 1


def test_f22_unknown_owner_exit_2_even_if_sink_unavailable(dbp):
    r = invoke(dbp, "Zoe Unknown")  # default factory would raise SinkUnavailable
    assert r.exit_code == 2 and "unknown owner" in r.stderr


def test_f10_f11_exit_2(dbp, client):
    r = invoke(dbp, "Priya")
    assert r.exit_code == 2
    assert 'ambiguous owner "Priya": use "Priya Nair" or "Priya Shah"' in r.stderr
    assert invoke(dbp, "Unassigned").exit_code == 2
    assert client.calls == []


def test_f13_nothing_outstanding_exit_0(dbp, client):
    r = invoke(dbp, "Karan Joshi")
    assert r.exit_code == 0 and client.calls == []
    assert r.stdout.strip() == "No open or overdue items for Karan Joshi."


def test_f09_warning_on_stderr_after_draft(dbp, client):
    r = invoke(dbp, "Priya Nair")
    assert r.exit_code == 0
    assert 'warning: 1 items for "Priya" are ambiguous and not included' in r.stderr
    assert "warning" not in r.stdout


def test_bad_today_exit_2(dbp, client):
    r = runner.invoke(app, ["followup", "Anita Desai", "--db", dbp, "--today", "nope"])
    assert r.exit_code == 2 and client.calls == []


def test_db_from_env(dbp, client, monkeypatch):
    monkeypatch.setenv("ACTIONTRACK_DB", dbp)
    r = runner.invoke(app, ["followup", "Anita Desai", *BASE])
    assert r.exit_code == 0


# --------------------------------------------------------------------------- --out (D25)


def test_out_writes_file_no_gmail(dbp, client, tmp_path):
    out = tmp_path / "drafts"
    r = invoke(dbp, "Anita Desai", "--out", str(out))
    f = out / "anita-desai.txt"
    assert r.exit_code == 0 and client.calls == []
    assert r.stdout.splitlines() == [
        "Wrote follow-up for Anita Desai (To: <blank>): 1 overdue, 3 open",
        f"File: {f} (no Gmail draft was created; nothing was sent)",
    ]
    text = f.read_text(encoding="utf-8")
    assert text.startswith(
        "To:\nSubject: Action items follow-up: Anita Desai (1 overdue, 3 open)\n\nHi Anita,"
    )
    assert text.endswith("Thanks,\n")


def test_out_file_matches_dry_run(dbp, client, tmp_path):
    dry = invoke(dbp, "Anita Desai", "--dry-run").stdout
    dry = dry[: dry.index("Dry run for")]  # drop the trailing summary line
    invoke(dbp, "Anita Desai", "--out", str(tmp_path / "o"))
    assert (tmp_path / "o" / "anita-desai.txt").read_text() == dry


def test_out_uses_email_map(dbp, client, tmp_path):
    m = tmp_path / "m.csv"
    m.write_text("owner,email\nAnita Desai,anita@example.com\n")
    out = tmp_path / "o"
    r = invoke(dbp, "Anita Desai", "--email-map", str(m), "--out", str(out))
    assert "(To: anita@example.com)" in r.stdout
    assert (out / "anita-desai.txt").read_text().startswith("To: anita@example.com\n")


def test_out_one_file_per_owner(dbp, client, tmp_path):
    out = tmp_path / "o"
    for who in ("Anita Desai", "Priya Shah", "Priya Nair"):
        assert invoke(dbp, who, "--out", str(out)).exit_code == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "anita-desai.txt",
        "priya-nair.txt",
        "priya-shah.txt",
    ]
    assert "Priya Shah" in (out / "priya-shah.txt").read_text()


def test_out_nothing_outstanding_writes_nothing(dbp, client, tmp_path):
    out = tmp_path / "o"
    r = invoke(dbp, "Karan Joshi", "--out", str(out))
    assert r.exit_code == 0 and "No open or overdue items for Karan Joshi." in r.stdout
    assert not out.exists() and client.calls == []


def test_out_ambiguous_warning_still_printed(dbp, client, tmp_path):
    r = invoke(dbp, "Priya Nair", "--out", str(tmp_path))
    assert r.exit_code == 0
    assert 'warning: 1 items for "Priya" are ambiguous and not included' in r.output


@pytest.mark.parametrize("who", ["Priya", "Unassigned", "Nobody Here"])
def test_out_usage_errors_write_nothing(dbp, client, tmp_path, who):
    out = tmp_path / "o"
    r = invoke(dbp, who, "--out", str(out))
    assert r.exit_code == 2 and not out.exists() and client.calls == []


def test_out_with_dry_run_is_usage_error(dbp, client, tmp_path):
    out = tmp_path / "o"
    r = invoke(dbp, "Anita Desai", "--out", str(out), "--dry-run")
    assert r.exit_code == 2 and "--out" in r.output and "--dry-run" in r.output
    assert not out.exists() and client.calls == []


def test_out_existing_file_is_usage_error(dbp, client, tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    r = invoke(dbp, "Anita Desai", "--out", str(f))
    assert r.exit_code == 2 and f.read_text() == "x" and client.calls == []


def test_out_write_failure_exit_1(dbp, client, tmp_path):
    (tmp_path / "anita-desai.txt").mkdir()
    r = invoke(dbp, "Anita Desai", "--out", str(tmp_path))
    assert r.exit_code == 1 and "error:" in r.output and client.calls == []


def test_out_rerun_overwrites_not_duplicates(dbp, client, tmp_path):
    out = tmp_path / "o"
    invoke(dbp, "Anita Desai", "--out", str(out))
    first = (out / "anita-desai.txt").read_text()
    invoke(dbp, "Anita Desai", "--out", str(out))
    assert [p.name for p in out.iterdir()] == ["anita-desai.txt"]
    assert (out / "anita-desai.txt").read_text() == first


# --------------------------------------------------------------------------- --all (D26)

PEOPLE = ["Anita Desai", "Priya Nair", "Priya Shah", "Sam Okafor"]  # owners with open items


def run_all(dbp, *args):
    return runner.invoke(app, ["followup", "--all", *args, "--db", dbp, *BASE])


def test_all_with_owner_is_usage_error(dbp, client, tmp_path):
    out = tmp_path / "o"
    r = run_all(dbp, "Anita Desai", "--out", str(out))
    assert r.exit_code == 2 and "--all" in r.stderr
    assert not out.exists() and client.calls == []


def test_neither_owner_nor_all_is_usage_error(dbp, client):
    r = runner.invoke(app, ["followup", "--db", dbp, *BASE])
    assert r.exit_code == 2 and "--all" in r.stderr and client.calls == []


def test_all_out_one_file_per_owner_with_items(dbp, client, tmp_path):
    out = tmp_path / "o"
    r = run_all(dbp, "--out", str(out))
    assert r.exit_code == 0 and client.calls == []
    assert sorted(p.name for p in out.iterdir()) == [
        "anita-desai.txt",
        "priya-nair.txt",
        "priya-shah.txt",
        "sam-okafor.txt",
    ]  # no Karan (all done), no ambiguous, no unassigned
    assert "4 files written to" in r.stdout
    assert (
        "Subject: Action items follow-up: Sam Okafor (2 overdue)"
        in (out / "sam-okafor.txt").read_text()
    )


def test_all_lists_skipped_ambiguous_and_unassigned(dbp, client, tmp_path):
    r = run_all(dbp, "--out", str(tmp_path / "o"))
    lines = r.stdout.splitlines()
    i = lines.index("Skipped (no resolved owner):")
    assert [" ".join(x.split()) for x in lines[i + 1 : i + 3]] == [
        "Ambiguous (Priya) 1 item",
        "Unassigned 1 item",
    ]
    assert "ambiguous and not included" not in r.stderr  # replaced by the skipped list


def test_all_gmail_creates_one_draft_per_owner(dbp, client):
    r = run_all(dbp)
    assert r.exit_code == 0
    assert [c[0] for c in client.calls] == ["create_draft"] * 4
    assert [c[1]["subject"].split(": ")[1].split(" (")[0] for c in client.calls] == PEOPLE
    assert "4 drafts created" in r.stdout and "nothing was sent" in r.stdout


def test_all_dry_run_creates_nothing(dbp, client):
    r = run_all(dbp, "--dry-run")
    assert r.exit_code == 0 and client.calls == []
    assert r.stdout.count("Subject: Action items follow-up:") == 4
    assert "4 emails previewed" in r.stdout


def test_all_out_and_dry_run_is_usage_error(dbp, client, tmp_path):
    r = run_all(dbp, "--out", str(tmp_path / "o"), "--dry-run")
    assert r.exit_code == 2 and client.calls == []


def test_all_lists_owners_without_address_and_never_crashes(dbp, client, tmp_path):
    m = tmp_path / "m.csv"
    m.write_text("owner,email\nAnita Desai,anita@example.com\nSam Okafor,\n\n")
    out = tmp_path / "o"
    r = run_all(dbp, "--email-map", str(m), "--out", str(out))
    assert r.exit_code == 0
    assert "No email address for 3 owners: Priya Nair, Priya Shah, Sam Okafor" in r.stdout
    assert (out / "anita-desai.txt").read_text().startswith("To: anita@example.com\n")
    assert (out / "sam-okafor.txt").read_text().startswith("To:\n")
    assert len(list(out.iterdir())) == 4


def test_all_no_map_lists_everyone_singular_and_plural(dbp, client, tmp_path):
    r = run_all(dbp, "--out", str(tmp_path / "o"))
    assert "No email address for 4 owners: Anita Desai, Priya Nair, Priya Shah, Sam Okafor" in (
        r.stdout
    )
    m = tmp_path / "m.csv"
    m.write_text("owner,email\n" + "".join(f"{p},{p[0]}@x.org\n" for p in PEOPLE[:3]))
    r = run_all(dbp, "--email-map", str(m), "--out", str(tmp_path / "o2"))
    assert "No email address for 1 owner: Sam Okafor" in r.stdout


def test_all_addresses_everywhere_prints_no_missing_line(dbp, client, tmp_path):
    m = tmp_path / "m.csv"
    m.write_text("owner,email\n" + "".join(f"{p},{p[0]}@x.org\n" for p in PEOPLE))
    r = run_all(dbp, "--email-map", str(m), "--out", str(tmp_path / "o"))
    assert "No email address" not in r.stdout


def test_all_nothing_outstanding(tmp_path, client):
    from datetime import date

    p = tmp_path / "d.db"
    seed(p, rows=[("z1", "Karan Joshi", "freeze", date(2026, 10, 1), "done", [])])
    r = run_all(str(p), "--out", str(tmp_path / "o"))
    assert r.exit_code == 0 and "No open or overdue items for any owner." in r.stdout
    assert not (tmp_path / "o").exists() and client.calls == []


def test_all_connector_failure_stops_without_retry(dbp, monkeypatch):
    class Flaky(Client):
        def __call__(self, name, args):
            self.calls.append((name, args))
            if len(self.calls) == 2:
                raise ValueError("rejected")
            return {"draft_id": f"r-{len(self.calls)}"}

    c = Flaky()
    monkeypatch.setattr(cli, "get_mcp_client", lambda: c)
    r = run_all(dbp)
    assert r.exit_code == 1 and len(c.calls) == 2  # no retry, no third owner
    assert "Draft created for Anita Desai" in r.stdout
    assert "Priya Nair" in r.stderr  # the error names the owner that failed


def test_all_unavailable_connector_exit_1_no_drafts(dbp):
    r = run_all(dbp)  # real get_mcp_client raises SinkUnavailable
    assert r.exit_code == 1 and "Draft created" not in r.stdout


# --------------------------------------------------------------------------- --email-map (D27)


def test_email_map_name_header_alias(dbp, client, tmp_path):
    m = tmp_path / "m.csv"
    m.write_text("name,email\nanita  desai,anita@example.com\n")
    r = invoke(dbp, "Anita Desai", "--email-map", str(m))
    assert r.exit_code == 0 and "(To: anita@example.com)" in r.stdout


def test_missing_address_single_owner_still_drafts(dbp, client, tmp_path):
    m = tmp_path / "m.csv"
    m.write_text("owner,email\nSam Okafor,sam@example.com\nAnita Desai,\n")
    r = invoke(dbp, "Anita Desai", "--email-map", str(m))
    assert r.exit_code == 0 and "(To: <blank>)" in r.stdout
    assert client.calls[0][1]["to"] == ""


def test_map_first_name_row_does_not_match_full_name(dbp, client, tmp_path):
    m = tmp_path / "m.csv"
    m.write_text("owner,email\nPriya,priya@example.com\n")
    r = invoke(dbp, "Priya Nair", "--email-map", str(m))
    assert "(To: <blank>)" in r.stdout


def test_map_with_only_header_is_fine(dbp, client, tmp_path):
    m = tmp_path / "m.csv"
    m.write_text("owner,email\n")
    assert invoke(dbp, "Anita Desai", "--email-map", str(m)).exit_code == 0
