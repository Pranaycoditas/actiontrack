"""Reader tests (TEST_PLAN P60-P65, P67-P70)."""

import hashlib
import os
import sys
from pathlib import Path

import pytest

from actiontrack.errors import UsageError
from actiontrack.models import NoteFile, Skip
from actiontrack.reader import read_file, read_folder

NOTES = Path(__file__).resolve().parent.parent / "notes"


def test_p60_empty_file_real():
    result = read_file(NOTES / "2026-09-09-notes-final-v2.md")
    assert result == Skip("2026-09-09-notes-final-v2.md", "empty file (0 bytes)")


def test_p61_binary_real():
    result = read_file(NOTES / "scratch.md")
    assert result == Skip("scratch.md", "not text (binary content)")


def test_p62_txt_real():
    result = read_file(NOTES / "2026-09-19-offsite-draft.txt")
    assert result == Skip("2026-09-19-offsite-draft.txt", "not a .md file")


def test_p62_txt_never_read(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"\x00\xff binary")  # would be 'binary' if read
    assert read_file(p).reason == "not a .md file"


def test_p63_invalid_utf8(tmp_path):
    p = tmp_path / "bad.md"
    p.write_bytes(b"# Meeting: ok\n- [ ] Sam to go \xff\n")
    assert read_file(p) == Skip("bad.md", "not text (binary content)")


def test_nul_byte_is_binary(tmp_path):
    p = tmp_path / "nul.md"
    p.write_bytes(b"hello\x00world")
    assert read_file(p).reason == "not text (binary content)"


def test_p64_bom_stripped(tmp_path):
    p = tmp_path / "bom.md"
    p.write_bytes(b"\xef\xbb\xbfDate: 2026-09-01\n")
    result = read_file(p)
    assert isinstance(result, NoteFile)
    assert result.text == "Date: 2026-09-01\n"


def test_p65_crlf_real():
    result = read_file(NOTES / "2026-10-02-finance-sync.md")
    assert isinstance(result, NoteFile)
    assert "\r" not in result.text
    raw = (NOTES / "2026-10-02-finance-sync.md").read_bytes()
    assert b"\r\n" in raw  # the fixture really is CRLF
    lf = raw.decode("utf-8").replace("\r\n", "\n")
    assert result.text == lf
    assert result.content_hash == hashlib.sha256(lf.encode("utf-8")).hexdigest()


def test_p65_hash_same_for_crlf_and_lf(tmp_path):
    (tmp_path / "a.md").write_bytes(b"x\r\ny\r\n")
    (tmp_path / "b.md").write_bytes(b"x\ny\n")
    a, b = read_file(tmp_path / "a.md"), read_file(tmp_path / "b.md")
    assert a.content_hash == b.content_hash
    assert a.file == "a.md"


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX non-root")
def test_p67_unreadable(tmp_path):
    p = tmp_path / "locked.md"
    p.write_text("hi")
    p.chmod(0)
    try:
        result = read_file(p)
    finally:
        p.chmod(0o644)
    assert isinstance(result, Skip)
    assert result.file == "locked.md"
    assert result.reason  # an OS error reason, no crash


def test_p68_directory_named_md_ignored(tmp_path):
    (tmp_path / "x.md").mkdir()
    (tmp_path / "real.md").write_text("hello")
    results = read_folder(tmp_path)
    assert [r.file for r in results] == ["real.md"]


def test_p69_missing_folder(tmp_path):
    with pytest.raises(UsageError):
        read_folder(tmp_path / "nope")


def test_p69_folder_is_file(tmp_path):
    f = tmp_path / "f.md"
    f.write_text("x")
    with pytest.raises(UsageError):
        read_folder(f)


def test_p70_unicode_and_spaces(tmp_path):
    name = "2026-09-01 café notes é.md"
    (tmp_path / name).write_text("héllo", encoding="utf-8")
    [result] = read_folder(tmp_path)
    assert isinstance(result, NoteFile)
    assert result.file == name
    assert result.text == "héllo"


def test_folder_sorted_and_non_recursive(tmp_path):
    for n in ["b.md", "a.md", "c.txt"]:
        (tmp_path / n).write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.md").write_text("x")
    results = read_folder(tmp_path)
    assert [r.file for r in results] == ["a.md", "b.md", "c.txt"]
    assert isinstance(results[2], Skip)


def test_real_notes_folder_skips_exactly_three():
    skips = [r for r in read_folder(NOTES) if isinstance(r, Skip)]
    assert sorted(s.file for s in skips) == [
        "2026-09-09-notes-final-v2.md",
        "2026-09-19-offsite-draft.txt",
        "scratch.md",
    ]
