"""Nothing is ever sent (TEST_PLAN 11). Hard rule: drafts only."""

from __future__ import annotations

import ast
import re
import socket
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from actiontrack import cli
from actiontrack.cli import app
from actiontrack.drafts import DRAFT_TOOL, GmailMcpSink, InMemorySink
from actiontrack.errors import SinkUnavailable, UsageError
from actiontrack.followup import run_followup
from actiontrack.store import Store
from followup_seed import TODAY, seed

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
runner = CliRunner()

FORBIDDEN = [
    "send_message",
    "send_draft",
    "messages.send",
    "drafts.send",
    "users().messages().send",
    "smtplib",
    "sendmail",
    "SMTP(",
]


def test_n01_static_scan_of_src():
    hits = []
    for f in SRC.rglob("*.py"):
        text = f.read_text()
        hits += [(f.name, tok) for tok in FORBIDDEN if tok in text]
        hits += [(f.name, m) for m in re.findall(r"\.send\s*\(", text)]
    assert hits == []


class Recording:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name, args):
        self.calls.append((name, args))
        return {"draft_id": f"r-{len(self.calls)}"}


class StrictSink:
    """Raises for any attribute other than create_draft."""

    def __init__(self):
        self.used: list[str] = []

    def create_draft(self, draft):
        self.used.append("create_draft")
        from actiontrack.models import DraftResult

        return DraftResult(draft_id="strict", to=draft.to)

    def __getattr__(self, name):
        raise AssertionError(f"forbidden attribute access: {name}")


@pytest.fixture
def dbp(tmp_path):
    seed(tmp_path / "t.db")
    return tmp_path / "t.db"


OWNERS = ["Anita Desai", "Sam Okafor", "Priya Nair", "Priya Shah", "Karan Joshi"]


def test_n06_strict_sink_for_every_owner(dbp):
    sink = StrictSink()
    with Store(dbp) as s:
        for o in OWNERS:
            run_followup(o, s, sink, TODAY, None)
    assert set(sink.used) == {"create_draft"}
    assert len(sink.used) == 4  # Karan has nothing outstanding


def test_n04_only_draft_tool_ever_called(dbp):
    rec = Recording()
    sink = GmailMcpSink(rec)
    with Store(dbp) as s:
        for o in OWNERS:
            run_followup(o, s, sink, TODAY, {"Anita Desai": "a@x.io"})
    assert {n for n, _ in rec.calls} == {DRAFT_TOOL}
    assert len(rec.calls) == 4
    for _, args in rec.calls:
        assert set(args) == {"to", "subject", "body"}


def test_n07_real_notes_recording_client(tmp_path):
    from ingest_helpers import NOTES

    path = tmp_path / "real.db"
    assert runner.invoke(app, ["ingest", str(NOTES), "--db", str(path)]).exit_code == 0
    rec = Recording()
    sink = GmailMcpSink(rec)
    drafts = 0
    with Store(path) as s:
        people = [o for o in s.owners() if not o.startswith(("Ambiguous", "Unassigned"))]
        assert len(people) == 9
        for owner in people:
            res = run_followup(owner, s, sink, TODAY, None)
            drafts += res.draft_id is not None
    assert drafts > 0
    assert {n for n, _ in rec.calls} == {DRAFT_TOOL}
    assert len(rec.calls) == drafts


def test_n08_failures_and_dry_run_make_no_calls(dbp, monkeypatch):
    rec = Recording()
    monkeypatch.setattr(cli, "get_mcp_client", lambda: rec)
    base = ["--db", str(dbp), "--today", "2026-10-22"]
    for args in (
        ["followup", "Anita Desai", "--dry-run", *base],
        ["followup", "Zoe Unknown", *base],
        ["followup", "Priya", *base],
        ["followup", "Karan Joshi", *base],
    ):
        runner.invoke(app, args)
    assert rec.calls == []

    # SinkUnavailable: factory raises, no client call possible
    def unavailable():
        raise SinkUnavailable("no")

    monkeypatch.setattr(cli, "get_mcp_client", unavailable)
    assert runner.invoke(app, ["followup", "Anita Desai", *base]).exit_code == 1
    assert rec.calls == []


def test_n09_no_network(dbp, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", boom)
    sink = InMemorySink()
    with Store(dbp) as s:
        run_followup("Anita Desai", s, sink, TODAY, None)
        with pytest.raises(UsageError):
            run_followup("Priya", s, sink, TODAY, None)
    r = runner.invoke(app, ["followup", "Anita Desai", "--dry-run", "--db", str(dbp)])
    assert r.exit_code == 0


def test_n10_cli_surface_offers_no_send():
    for args in (["--help"], ["followup", "--help"]):
        out = runner.invoke(app, args).output.lower()
        for bad in ("--send", "--yes-send", "--now", "--deliver"):
            assert bad not in out
        assert not re.search(
            r"\bsend\b", out.replace("nothing was sent", "").replace("never sent", "")
        )
    cmds = [c.name for c in app.registered_commands]
    assert not any("send" in (c or "") for c in cmds)


def test_n11_no_mail_libraries():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())
    blob = str(deps).lower()
    for lib in ("smtplib", "yagmail", "sendgrid", "mailgun", "google-api-python-client"):
        assert lib not in blob
    banned = {"smtplib", "yagmail", "sendgrid", "mailgun", "googleapiclient", "email"}
    for f in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            assert not {m.split(".")[0] for m in mods} & banned, (f.name, mods)


def test_n13_cli_prints_nothing_was_sent(dbp, monkeypatch):
    monkeypatch.setattr(cli, "get_mcp_client", lambda: Recording())
    r = runner.invoke(app, ["followup", "Anita Desai", "--db", str(dbp), "--today", "2026-10-22"])
    assert r.exit_code == 0
    assert "nothing was sent" in r.output


def test_n14_no_send_or_full_access_oauth_scope():
    bad = ("gmail.send", "gmail.modify", "mail.google.com", "gmail.compose")
    for f in [*SRC.rglob("*.py"), ROOT / "pyproject.toml", *ROOT.glob("*.json")]:
        text = f.read_text()
        assert not any(b in text for b in bad), f.name
