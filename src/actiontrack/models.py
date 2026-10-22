"""Frozen dataclasses shared by all stages. No logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

Syntax = Literal["checkbox", "action", "table"]
OwnerKind = Literal["person", "unassigned", "ambiguous"]
DateSource = Literal["header", "filename", "none"]
Status = Literal["open", "done"]


@dataclass(frozen=True)
class NoteFile:
    file: str
    text: str  # normalised: BOM stripped, CRLF -> LF
    content_hash: str  # sha256 of text


@dataclass(frozen=True)
class Skip:
    file: str
    reason: str  # exact text from SPEC 5.5


@dataclass(frozen=True)
class Header:
    title: str | None
    date_text: str | None
    date: date | None
    date_source: DateSource
    attendees: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RawLine:
    line_no: int
    syntax: Syntax
    raw_line: str
    checked: bool
    owner_text: str | None
    task_text: str
    due_text: str | None


@dataclass(frozen=True)
class Note:
    file: str
    header: Header
    lines: list[RawLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    content_hash: str = ""  # sha256 of the normalised text; set by ingest, stored on `meetings`


@dataclass(frozen=True)
class Mention:
    """A row of `mentions` (DATA_MODEL 2.2) minus `id` and `item_id`."""

    file: str
    line_no: int
    syntax: Syntax
    raw_line: str
    owner_raw: str | None
    owner: str
    owner_kind: OwnerKind
    collaborators: list[str]
    task: str
    task_key: str
    due: date | None
    due_raw: str | None
    checked: bool
    meeting_date: date | None = None  # from the meeting; used for ordering, not stored here
    item_id: str | None = None  # link to the merged item; set by ingest before apply_ingest


@dataclass(frozen=True)
class Item:
    """A row of `items` (DATA_MODEL 2.3)."""

    id: str
    id_key: str
    owner: str
    owner_kind: OwnerKind
    collaborators: list[str]
    task: str
    due: date | None
    due_raw: str | None
    status: Status
    done_manual: bool
    first_file: str
    latest_file: str
    mention_count: int


@dataclass(frozen=True)
class Draft:
    owner: str
    to: str | None
    subject: str
    body: str


@dataclass(frozen=True)
class DraftResult:
    draft_id: str
    to: str | None


@dataclass(frozen=True)
class IngestCounts:
    new: int = 0
    updated: int = 0
    unchanged: int = 0


@dataclass(frozen=True)
class IngestResult:
    scanned: int
    ingested: int
    items_found: int
    items_unique: int
    counts: IngestCounts
    skipped: list[Skip] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
