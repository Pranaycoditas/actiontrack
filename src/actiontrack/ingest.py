"""Orchestration (ARCHITECTURE 4.9): read, parse, normalise, regroup, store.

Contains no parsing and no SQL of its own. A bad file becomes a `Skip`, never an exception.
Only a database failure (`StoreError`) or a missing folder (`UsageError`) escapes.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from actiontrack.dates import DueResult, resolve_due
from actiontrack.dedupe import group_mentions, make_item, task_key
from actiontrack.models import IngestResult, Mention, Note, NoteFile, RawLine, Skip
from actiontrack.owners import Roster, build_roster, resolve_owner
from actiontrack.parser import parse_note
from actiontrack.reader import read_folder
from actiontrack.store import Store

__all__ = ["run_ingest"]

_AMBIGUOUS_FIRST = re.compile(r"^Ambiguous \((.+)\)$")


def run_ingest(folder: Path, store: Store) -> IngestResult:
    entries = read_folder(Path(folder))  # raises UsageError for a bad folder
    skipped: list[Skip] = [e for e in entries if isinstance(e, Skip)]
    warnings: list[str] = []

    # Pass 1: parse every readable file; the roster needs all attendee lists.
    parsed: list[tuple[NoteFile, Note]] = []
    for entry in entries:
        if isinstance(entry, Skip):
            continue
        result = _safe_parse(entry)
        if isinstance(result, Skip):
            skipped.append(result)
        else:
            parsed.append((entry, result))
    roster = build_roster([note.header.attendees for _, note in parsed])

    # Pass 2: owners and dates per action line.
    known = store.known_hashes()
    reread: list[Note] = []
    fresh: list[Mention] = []
    ingested = 0
    for nf, note in parsed:
        try:
            mentions, note_warnings = _mentions_for(note, roster)
        except Exception as exc:  # noqa: BLE001 - a bad note is skipped, never fatal
            skipped.append(Skip(note.file, f"parse error: {str(exc) or type(exc).__name__}"))
            continue
        ingested += 1
        warnings.extend(f"{note.file}: {w}" for w in note_warnings)
        if known.get(note.file) == nf.content_hash:
            continue  # unchanged: its stored mentions are reused below
        reread.append(replace(note, content_hash=nf.content_hash))
        fresh.extend(mentions)

    # Regroup everything: fresh mentions plus stored ones of unchanged / vanished files (D10).
    reread_files = {n.file for n in reread}
    kept = [m for m in store.all_mentions() if m.file not in reread_files]
    all_mentions = kept + fresh
    taken: set[str] = set()
    items = []
    link: dict[tuple[str, int], str] = {}
    for group in group_mentions(all_mentions):
        item = make_item(group, taken)
        taken.add(item.id)
        items.append(item)
        for m in group.mentions:
            link[(m.file, m.line_no)] = item.id
    linked = [replace(m, item_id=link[(m.file, m.line_no)]) for m in all_mentions]

    counts = store.apply_ingest(reread, linked, items)
    return IngestResult(
        scanned=len(entries),
        ingested=ingested,
        items_found=len(linked),
        items_unique=len(items),
        counts=counts,
        skipped=sorted(skipped, key=lambda s: s.file),
        warnings=warnings,
    )


def _safe_parse(nf: NoteFile) -> Note | Skip:
    try:
        return parse_note(nf)
    except Exception as exc:  # noqa: BLE001 - parse_note should not raise; belt and braces
        return Skip(nf.file, f"parse error: {str(exc) or type(exc).__name__}")


def _resolve_line_due(line: RawLine, note: Note) -> DueResult:
    """Resolve one line's due text against the MEETING date (never today).

    A table's Due cell is a deadline by definition, so it has no `by` to introduce it: resolve
    it as `by <cell>` and keep the cell text as the raw phrase.
    """
    text = line.due_text
    if line.syntax == "table" and text and text.strip():
        res = resolve_due(f"by {text.strip()}", note.header.date)
        return replace(res, raw=text.strip())
    return resolve_due(text, note.header.date)


def _mentions_for(note: Note, roster: Roster) -> tuple[list[Mention], list[str]]:
    """Mentions of one note plus its warnings (parser, dates, owners, missing metadata)."""
    attendees = note.header.attendees
    warnings = list(note.warnings)
    out: list[Mention] = []
    ambiguous: list[str] = []
    unresolved_relative = False
    for line in note.lines:
        res = resolve_owner(line.owner_text, attendees, roster)
        due = _resolve_line_due(line, note)
        if res.kind == "ambiguous":
            m = _AMBIGUOUS_FIRST.match(res.owner)
            ambiguous.append(m.group(1) if m else res.owner)
        elif res.warning:
            warnings.append(f"line {line.line_no}: {res.warning}")
        if due.warning:
            warnings.append(f"line {line.line_no}: {due.warning}")
        if note.header.date is None and due.due is None and due.raw:
            unresolved_relative = True
        out.append(
            Mention(
                file=note.file,
                line_no=line.line_no,
                syntax=line.syntax,
                raw_line=line.raw_line,
                owner_raw=line.owner_text,
                owner=res.owner,
                owner_kind=res.kind,
                collaborators=list(res.collaborators),
                task=line.task_text,
                task_key=task_key(line.task_text),
                due=due.due,
                due_raw=due.raw,
                checked=line.checked,
                meeting_date=note.header.date,
            )
        )
    if ambiguous:
        names = ", ".join(dict.fromkeys(ambiguous))
        n = len(ambiguous)
        why = "no attendees; " if not attendees else ""
        warnings.append(f"{why}{n} owner{'s' if n != 1 else ''} ambiguous ({names})")
    if note.header.date is None and not attendees:
        tail = ", relative due dates unresolved" if unresolved_relative else ""
        n = len(out)
        warnings.append(f"no date, no attendees; {n} item{'s' if n != 1 else ''} ingested{tail}")
    return out, warnings
