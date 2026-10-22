"""DraftSink implementations (ARCHITECTURE 5). Includes N02-N05 and N12."""

from __future__ import annotations

import inspect

import pytest

from actiontrack import drafts
from actiontrack.drafts import (
    DryRunSink,
    FileSink,
    GmailMcpSink,
    InMemorySink,
    LazySink,
)
from actiontrack.errors import DraftError, SinkUnavailable
from actiontrack.models import Draft, DraftResult

DRAFT = Draft(owner="Anita Desai", to="anita@example.com", subject="S", body="B")
BLANK = Draft(owner="Anita Desai", to=None, subject="S", body="B")


class Recorder:
    def __init__(self, result=None, exc=None):
        self.calls: list[tuple[str, dict]] = []
        self.result = {"draft_id": "r-1"} if result is None else result
        self.exc = exc

    def __call__(self, name: str, args: dict) -> dict:
        self.calls.append((name, args))
        if self.exc:
            raise self.exc
        return self.result


def test_reexports_models():
    assert drafts.Draft is Draft and drafts.DraftResult is DraftResult


def test_n02_protocol_members_exactly_create_draft():
    members = [n for n in vars(drafts.DraftSink) if not n.startswith("_")]
    assert members == ["create_draft"]


@pytest.mark.parametrize("cls", [GmailMcpSink, DryRunSink, FileSink, InMemorySink, LazySink])
def test_n03_no_send_reply_schedule_attributes(cls):
    for name in dir(cls):
        low = name.lower()
        assert not low.startswith(("send", "reply", "schedule")), name
    public = [n for n in dir(cls) if not n.startswith("_")]
    assert public == ["create_draft"] or set(public) <= {"create_draft", "drafts"}


def test_in_memory_records():
    s = InMemorySink()
    r = s.create_draft(DRAFT)
    s.create_draft(BLANK)
    assert s.drafts == [DRAFT, BLANK]
    assert isinstance(r, DraftResult) and r.to == "anita@example.com"
    assert r.draft_id != s.create_draft(DRAFT).draft_id


def test_dry_run_prints_and_returns_dry_run(capsys):
    r = DryRunSink().create_draft(DRAFT)
    out = capsys.readouterr().out
    assert r == DraftResult(draft_id="dry-run", to="anita@example.com")
    assert "To: anita@example.com" in out and "Subject: S" in out and "B" in out


def test_dry_run_blank_to(capsys):
    DryRunSink().create_draft(BLANK)
    assert "To:\n" in capsys.readouterr().out


def test_n04_gmail_sink_calls_only_draft_tool_once():
    rec = Recorder({"draft_id": "r-9"})
    r = GmailMcpSink(rec).create_draft(DRAFT)
    assert [c[0] for c in rec.calls] == [drafts.DRAFT_TOOL] == ["create_draft"]
    assert r == DraftResult("r-9", "anita@example.com")


def test_n12_payload_keys_only_to_subject_body():
    rec = Recorder()
    GmailMcpSink(rec).create_draft(DRAFT)
    GmailMcpSink(rec).create_draft(BLANK)
    for _, args in rec.calls:
        assert set(args) == {"to", "subject", "body"}
    assert rec.calls[0][1] == {"to": "anita@example.com", "subject": "S", "body": "B"}
    assert rec.calls[1][1]["to"] == ""


@pytest.mark.parametrize("name", ["send_message", "send_draft", "delete_draft", "", "Create_Draft"])
def test_n05_allow_list_rejects_before_client(name):
    rec = Recorder()
    sink = GmailMcpSink(rec)
    with pytest.raises(DraftError):
        sink._invoke(name, {"to": "", "subject": "", "body": ""})
    assert rec.calls == []


def test_allow_list_is_exactly_one_name():
    assert drafts.ALLOWED_TOOLS == frozenset({drafts.DRAFT_TOOL})


@pytest.mark.parametrize("exc", [ConnectionError("down"), PermissionError("401"), TimeoutError()])
def test_connection_and_auth_failures_are_sink_unavailable(exc):
    with pytest.raises(SinkUnavailable):
        GmailMcpSink(Recorder(exc=exc)).create_draft(DRAFT)


def test_other_failures_are_draft_error_not_unavailable():
    rec = Recorder(exc=ValueError("rejected"))
    with pytest.raises(DraftError) as ei:
        GmailMcpSink(rec).create_draft(DRAFT)
    assert not isinstance(ei.value, SinkUnavailable)
    assert len(rec.calls) == 1  # no retry


def test_sink_unavailable_from_client_passes_through_no_retry():
    rec = Recorder(exc=SinkUnavailable("not authorized"))
    with pytest.raises(SinkUnavailable, match="not authorized"):
        GmailMcpSink(rec).create_draft(DRAFT)
    assert len(rec.calls) == 1


@pytest.mark.parametrize("bad", [{}, {"error": "x"}, {"draft_id": ""}])
def test_result_without_draft_id_is_draft_error(bad):
    with pytest.raises(DraftError):
        GmailMcpSink(Recorder(bad)).create_draft(DRAFT)


def test_accepts_alternative_id_keys():
    assert GmailMcpSink(Recorder({"id": "x1"})).create_draft(DRAFT).draft_id == "x1"
    assert GmailMcpSink(Recorder({"draftId": "x2"})).create_draft(DRAFT).draft_id == "x2"


def test_lazy_sink_builds_once_on_first_use():
    built = []
    inner = InMemorySink()

    def factory():
        built.append(1)
        return inner

    lazy = LazySink(factory)
    assert built == []
    lazy.create_draft(DRAFT)
    lazy.create_draft(DRAFT)
    assert built == [1] and len(inner.drafts) == 2


def test_create_draft_signature_single_arg():
    assert list(inspect.signature(GmailMcpSink.create_draft).parameters) == ["self", "draft"]


# --------------------------------------------------------------------------- FileSink (D25)


def test_file_sink_writes_to_subject_body(tmp_path):
    r = FileSink(tmp_path).create_draft(DRAFT)
    f = tmp_path / "anita-desai.txt"
    assert f.read_text(encoding="utf-8") == "To: anita@example.com\nSubject: S\n\nB\n"
    assert r == DraftResult(draft_id=str(f), to="anita@example.com")


def test_file_sink_blank_to_matches_dry_run(tmp_path, capsys):
    FileSink(tmp_path).create_draft(BLANK)
    DryRunSink().create_draft(BLANK)
    assert (tmp_path / "anita-desai.txt").read_text() == capsys.readouterr().out
    assert (tmp_path / "anita-desai.txt").read_text().startswith("To:\nSubject: S\n")


def test_file_sink_creates_missing_folder_with_parents(tmp_path):
    FileSink(tmp_path / "a" / "b").create_draft(DRAFT)
    assert (tmp_path / "a" / "b" / "anita-desai.txt").is_file()


@pytest.mark.parametrize(
    ("owner", "name"),
    [
        ("Priya Nair", "priya-nair.txt"),
        ("Priya Shah", "priya-shah.txt"),
        ("Rahul  Mehta", "rahul-mehta.txt"),
        ("Zoë O'Neil-Smith", "zo-o-neil-smith.txt"),
        ("../../etc/passwd", "etc-passwd.txt"),
    ],
)
def test_file_sink_slug(tmp_path, owner, name):
    FileSink(tmp_path).create_draft(Draft(owner=owner, to=None, subject="S", body="B"))
    assert [p.name for p in tmp_path.iterdir()] == [name]


def test_file_sink_rerun_overwrites_only_that_owner(tmp_path):
    other = Draft(owner="Sam Okafor", to=None, subject="S", body="other")
    sink = FileSink(tmp_path)
    sink.create_draft(other)
    sink.create_draft(DRAFT)
    sink.create_draft(Draft(owner="Anita Desai", to=None, subject="S2", body="B2"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["anita-desai.txt", "sam-okafor.txt"]
    assert (tmp_path / "anita-desai.txt").read_text() == "To:\nSubject: S2\n\nB2\n"
    assert (tmp_path / "sam-okafor.txt").read_text().endswith("other\n")


def test_file_sink_unwritable_is_draft_error(tmp_path):
    (tmp_path / "anita-desai.txt").mkdir()  # a directory is in the way
    with pytest.raises(DraftError):
        FileSink(tmp_path).create_draft(DRAFT)


def test_file_sink_empty_slug_is_draft_error(tmp_path):
    with pytest.raises(DraftError):
        FileSink(tmp_path).create_draft(Draft(owner="???", to=None, subject="S", body="B"))
