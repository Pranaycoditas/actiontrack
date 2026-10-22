"""Stage 1: turn a folder into decoded note text, or a reason to skip."""

from __future__ import annotations

import hashlib
from pathlib import Path

from actiontrack.errors import UsageError
from actiontrack.models import NoteFile, Skip


def read_folder(folder: Path) -> list[NoteFile | Skip]:
    """Read every entry of `folder` (non-recursive, sorted by name).

    Sub-directories are ignored. Raises UsageError only if `folder` is missing,
    not a directory, or cannot be listed.
    """
    folder = Path(folder)
    if not folder.exists():
        raise UsageError(f"folder not found: {folder}")
    if not folder.is_dir():
        raise UsageError(f"not a directory: {folder}")
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        raise UsageError(f"cannot read folder {folder}: {exc.strerror or exc}") from exc
    return [read_file(p) for p in entries if not p.is_dir()]


def read_file(path: Path) -> NoteFile | Skip:
    """Decode one note. Never raises: every failure is a `Skip` with a reason."""
    path = Path(path)
    name = path.name
    if path.suffix.lower() != ".md":
        return Skip(name, "not a .md file")
    try:
        data = path.read_bytes()
    except OSError as exc:
        return Skip(name, f"cannot read file: {exc.strerror or exc}")
    if not data:
        return Skip(name, "empty file (0 bytes)")
    if b"\x00" in data:
        return Skip(name, "not text (binary content)")
    try:
        text = data.decode("utf-8-sig")  # strips a leading BOM
    except UnicodeDecodeError:
        return Skip(name, "not text (binary content)")
    text = text.replace("\r\n", "\n")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return NoteFile(file=name, text=text, content_hash=digest)
