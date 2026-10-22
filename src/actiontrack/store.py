"""SQLite persistence (stage 5) and every query. The only module that imports sqlite3."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path

from actiontrack.errors import StoreError, UsageError
from actiontrack.models import IngestCounts, Item, Mention, Note

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
  file          TEXT PRIMARY KEY,
  title         TEXT,
  meeting_date  TEXT,
  date_source   TEXT NOT NULL CHECK (date_source IN ('header','filename','none')),
  attendees     TEXT NOT NULL DEFAULT '[]',
  content_hash  TEXT NOT NULL,
  ingested_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
  id               TEXT PRIMARY KEY,
  id_key           TEXT NOT NULL,
  owner            TEXT NOT NULL,
  owner_kind       TEXT NOT NULL CHECK (owner_kind IN ('person','unassigned','ambiguous')),
  collaborators    TEXT NOT NULL DEFAULT '[]',
  task             TEXT NOT NULL,
  due              TEXT,
  due_raw          TEXT,
  status           TEXT NOT NULL CHECK (status IN ('open','done')),
  done_manual      INTEGER NOT NULL DEFAULT 0 CHECK (done_manual IN (0,1)),
  first_file       TEXT NOT NULL,
  latest_file      TEXT NOT NULL,
  mention_count    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS items_owner ON items(owner);
CREATE TABLE IF NOT EXISTS mentions (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id        TEXT REFERENCES items(id),
  file           TEXT NOT NULL REFERENCES meetings(file),
  line_no        INTEGER NOT NULL,
  syntax         TEXT NOT NULL CHECK (syntax IN ('checkbox','action','table')),
  raw_line       TEXT NOT NULL,
  owner_raw      TEXT,
  owner          TEXT NOT NULL,
  owner_kind     TEXT NOT NULL CHECK (owner_kind IN ('person','unassigned','ambiguous')),
  collaborators  TEXT NOT NULL DEFAULT '[]',
  task           TEXT NOT NULL,
  task_key       TEXT NOT NULL,
  due            TEXT,
  due_raw        TEXT,
  checked        INTEGER NOT NULL CHECK (checked IN (0,1)),
  UNIQUE (file, line_no)
);
CREATE INDEX IF NOT EXISTS mentions_item ON mentions(item_id);
"""

STATUSES = ("open", "done", "overdue")

# Constant SQL fragments; every value is bound as a parameter, never formatted in.
_SORT = "ORDER BY i.due IS NULL, i.due, m.meeting_date, i.id"
_FROM = "FROM items i LEFT JOIN meetings m ON m.file = i.latest_file"


@dataclass(frozen=True)
class ListResult:
    """Result of `list_items`: the matching items plus human-readable owner warnings.

    `warnings` is empty unless the owner filter touches a shared first name or excludes
    ambiguous items (SPEC 3.2). The CLI prints each entry to stderr.
    """

    items: list[Item]
    warnings: list[str] = field(default_factory=list)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _day(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _item_from_row(r: sqlite3.Row) -> Item:
    return Item(
        id=r["id"],
        id_key=r["id_key"],
        owner=r["owner"],
        owner_kind=r["owner_kind"],
        collaborators=json.loads(r["collaborators"]),
        task=r["task"],
        due=_day(r["due"]),
        due_raw=r["due_raw"],
        status=r["status"],
        done_manual=bool(r["done_manual"]),
        first_file=r["first_file"],
        latest_file=r["latest_file"],
        mention_count=r["mention_count"],
    )


def _item_values(it: Item) -> tuple:
    return (
        it.id,
        it.id_key,
        it.owner,
        it.owner_kind,
        json.dumps(it.collaborators),
        it.task,
        _iso(it.due),
        it.due_raw,
        it.status,
        int(it.done_manual),
        it.first_file,
        it.latest_file,
        it.mention_count,
    )


class Store:
    def __init__(self, path: Path, timeout: float = 30.0) -> None:
        try:
            # isolation_level=None: transactions are explicit (BEGIN IMMEDIATE ... COMMIT).
            self._conn = sqlite3.connect(str(path), timeout=timeout, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA)
        except sqlite3.Error as exc:
            raise StoreError(f"cannot open database {path}: {exc}") from exc

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ reads
    def known_hashes(self) -> dict[str, str]:
        rows = self._query("SELECT file, content_hash FROM meetings")
        return {r["file"]: r["content_hash"] for r in rows}

    def all_mentions(self) -> list[Mention]:
        """Every stored mention in (meeting_date, file, line_no) order, undated first.

        `item_id` carries the stored link; ingest regroups and sets fresh links.
        """
        rows = self._query(
            "SELECT n.*, m.meeting_date FROM mentions n JOIN meetings m ON m.file = n.file"
            " ORDER BY m.meeting_date, n.file, n.line_no"
        )
        return [
            Mention(
                file=r["file"],
                line_no=r["line_no"],
                syntax=r["syntax"],
                raw_line=r["raw_line"],
                owner_raw=r["owner_raw"],
                owner=r["owner"],
                owner_kind=r["owner_kind"],
                collaborators=json.loads(r["collaborators"]),
                task=r["task"],
                task_key=r["task_key"],
                due=_day(r["due"]),
                due_raw=r["due_raw"],
                checked=bool(r["checked"]),
                meeting_date=_day(r["meeting_date"]),
                item_id=r["item_id"],
            )
            for r in rows
        ]

    def list_items(
        self, owner: str | None, status: str | None, due_before: date | None, today: date
    ) -> ListResult:
        """Filter items (all filters AND together). Overdue is computed against `today`."""
        if status is not None and status not in STATUSES:
            raise UsageError(f"invalid status {status!r}: use one of {', '.join(STATUSES)}")
        where: list[str] = []
        params: list[object] = []
        warnings: list[str] = []
        if owner is not None:
            clause, oparams, warnings = self._owner_filter(owner.strip())
            where.append(clause)
            params += oparams
        if status == "open":
            where.append("(i.status = 'open' AND (i.due IS NULL OR i.due >= ?))")
            params.append(today.isoformat())
        elif status == "overdue":
            where.append("(i.status = 'open' AND i.due IS NOT NULL AND i.due < ?)")
            params.append(today.isoformat())
        elif status == "done":
            where.append("i.status = 'done'")
        if due_before is not None:
            where.append("(i.due IS NOT NULL AND i.due < ?)")
            params.append(due_before.isoformat())
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        rows = self._query("SELECT i.* " + _FROM + clause + " " + _SORT, params)
        return ListResult([_item_from_row(r) for r in rows], warnings)

    def get_item(self, item_id: str) -> Item | None:
        rows = self._query("SELECT * FROM items WHERE id = ?", [item_id.strip().lower()])
        return _item_from_row(rows[0]) if rows else None

    def mark_done(self, item_id: str) -> bool:
        """Close an item by hand. False if it is already done or does not exist."""
        try:
            cur = self._conn.execute(
                "UPDATE items SET status = 'done', done_manual = 1"
                " WHERE id = ? AND status = 'open'",
                [item_id.strip().lower()],
            )
        except sqlite3.Error as exc:
            raise StoreError(f"cannot mark {item_id} done: {exc}") from exc
        return cur.rowcount == 1

    def open_items_for(self, owner: str) -> list[Item]:
        """Open (including overdue) items of one resolved person, case-insensitive."""
        rows = self._query(
            "SELECT i.* FROM items i WHERE lower(i.owner) = ? AND i.owner_kind = 'person'"
            " AND i.status = 'open' ORDER BY i.due IS NULL, i.due, i.id",
            [owner.strip().lower()],
        )
        return [_item_from_row(r) for r in rows]

    def ambiguous_count(self, first_name: str) -> int:
        row = self._query(
            "SELECT count(*) AS n FROM items WHERE owner_kind = 'ambiguous' AND lower(owner) = ?",
            [f"ambiguous ({first_name.strip().lower()})"],
        )[0]
        return row["n"]

    def open_owner_counts(self) -> list[tuple[str, str, int]]:
        """`(owner, owner_kind, open item count)` for every owner with an open item, by name."""
        rows = self._query(
            "SELECT owner, owner_kind, count(*) AS n FROM items WHERE status = 'open'"
            " GROUP BY owner, owner_kind ORDER BY owner"
        )
        return [(r["owner"], r["owner_kind"], r["n"]) for r in rows]

    def owners(self) -> list[str]:
        """Every distinct stored owner string (names, `Unassigned`, `Ambiguous (X)`), sorted."""
        return [r["owner"] for r in self._query("SELECT DISTINCT owner FROM items ORDER BY owner")]

    # ------------------------------------------------------------------ write
    def apply_ingest(
        self, notes: list[Note], mentions: list[Mention], items: list[Item]
    ) -> IngestCounts:
        """DATA_MODEL 5 in one transaction.

        `notes` are the files that were (re)read: their meetings row is upserted and their
        mentions replaced. `mentions` is the complete mention set after regrouping, each with
        `item_id` set; mentions of files not in `notes` keep their stored row and only get
        their link refreshed. `items` is the complete regrouped item set.
        """
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                counts = self._apply(notes, mentions, items)
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
        except Exception as exc:  # sqlite3.Error or anything else: roll back, one error type
            raise StoreError(f"ingest failed, database unchanged: {exc}") from exc
        return counts

    def _apply(self, notes: list[Note], mentions: list[Mention], items: list[Item]) -> IngestCounts:
        now = _utc_now()
        for n in notes:
            self._conn.execute(
                "INSERT INTO meetings (file, title, meeting_date, date_source, attendees,"
                " content_hash, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(file) DO UPDATE SET title = excluded.title,"
                " meeting_date = excluded.meeting_date, date_source = excluded.date_source,"
                " attendees = excluded.attendees, content_hash = excluded.content_hash,"
                " ingested_at = excluded.ingested_at",
                (
                    n.file,
                    n.header.title,
                    _iso(n.header.date),
                    n.header.date_source,
                    json.dumps(n.header.attendees),
                    n.content_hash,
                    now,
                ),
            )
            self._conn.execute("DELETE FROM mentions WHERE file = ?", (n.file,))
        counts = self._upsert_items(items)
        self._write_mentions(mentions, {n.file for n in notes})
        self._conn.execute(
            "DELETE FROM items WHERE NOT EXISTS (SELECT 1 FROM mentions WHERE item_id = items.id)"
        )
        return counts

    def _upsert_items(self, items: Iterable[Item]) -> IngestCounts:
        new = updated = unchanged = 0
        for it in items:
            old = self._conn.execute("SELECT * FROM items WHERE id = ?", (it.id,)).fetchone()
            if old is not None and old["done_manual"]:
                # sticky manual done (D16): re-ingest never reopens
                it = replace(it, status="done", done_manual=True)
            values = _item_values(it)
            if old is None:
                new += 1
            elif tuple(old) == values:
                unchanged += 1
                continue
            else:
                updated += 1
            self._conn.execute(
                "INSERT INTO items (id, id_key, owner, owner_kind, collaborators, task, due,"
                " due_raw, status, done_manual, first_file, latest_file, mention_count)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET id_key = excluded.id_key, owner = excluded.owner,"
                " owner_kind = excluded.owner_kind, collaborators = excluded.collaborators,"
                " task = excluded.task, due = excluded.due, due_raw = excluded.due_raw,"
                " status = excluded.status, done_manual = excluded.done_manual,"
                " first_file = excluded.first_file, latest_file = excluded.latest_file,"
                " mention_count = excluded.mention_count",
                values,
            )
        return IngestCounts(new=new, updated=updated, unchanged=unchanged)

    def _write_mentions(self, mentions: Iterable[Mention], reread: set[str]) -> None:
        for m in mentions:
            if m.item_id is None:
                raise StoreError(f"mention {m.file}:{m.line_no} has no item_id")
            if m.file not in reread:
                cur = self._conn.execute(
                    "UPDATE mentions SET item_id = ? WHERE file = ? AND line_no = ?",
                    (m.item_id, m.file, m.line_no),
                )
                if cur.rowcount:
                    continue
            self._conn.execute(
                "INSERT INTO mentions (item_id, file, line_no, syntax, raw_line, owner_raw, owner,"
                " owner_kind, collaborators, task, task_key, due, due_raw, checked)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    m.item_id,
                    m.file,
                    m.line_no,
                    m.syntax,
                    m.raw_line,
                    m.owner_raw,
                    m.owner,
                    m.owner_kind,
                    json.dumps(m.collaborators),
                    m.task,
                    m.task_key,
                    _iso(m.due),
                    m.due_raw,
                    int(m.checked),
                ),
            )

    # ---------------------------------------------------------------- helpers
    def _query(self, sql: str, params: Iterable[object] = ()) -> list[sqlite3.Row]:
        try:
            return self._conn.execute(sql, list(params)).fetchall()
        except sqlite3.Error as exc:
            raise StoreError(f"database error: {exc}") from exc

    def _owner_filter(self, arg: str) -> tuple[str, list[object], list[str]]:
        """SQL clause, params and warnings for an `--owner` value (SPEC 3.2)."""
        low = arg.lower()
        if low == "unassigned":
            return "i.owner_kind = 'unassigned'", [], []
        if " " in arg:
            warnings: list[str] = []
            first = low.split()[0]
            if first != "ambiguous":
                rows = self._query(
                    "SELECT owner, count(*) AS n FROM items WHERE owner_kind = 'ambiguous'"
                    " AND lower(owner) = ? GROUP BY owner",
                    [f"ambiguous ({first})"],
                )
                if rows:
                    warnings.append(
                        f'{rows[0]["n"]} items owned by "{rows[0]["owner"]}" not included'
                    )
            return "lower(i.owner) = ?", [low], warnings
        # Bare first name: every person with that first name, plus its ambiguous items.
        prefix = low + " "
        clause = (
            "((i.owner_kind = 'person' AND lower(substr(i.owner, 1, ?)) = ?)"
            " OR (i.owner_kind = 'ambiguous' AND lower(i.owner) = ?))"
        )
        params: list[object] = [len(prefix), prefix, f"ambiguous ({low})"]
        people = [
            r["owner"]
            for r in self._query(
                "SELECT DISTINCT owner FROM items WHERE owner_kind = 'person'"
                " AND lower(substr(owner, 1, ?)) = ? ORDER BY owner",
                [len(prefix), prefix],
            )
        ]
        amb = self._query(
            "SELECT owner, count(*) AS n FROM items WHERE owner_kind = 'ambiguous'"
            " AND lower(owner) = ? GROUP BY owner",
            [f"ambiguous ({low})"],
        )
        warnings = []
        if amb:
            warnings.append(
                f'"{arg}" is a shared first name: includes {amb[0]["n"]} items owned by'
                f' "{amb[0]["owner"]}"'
            )
        elif len(people) > 1:
            warnings.append(f'"{arg}" is shared by {" and ".join(people)}')
        return clause, params, warnings
