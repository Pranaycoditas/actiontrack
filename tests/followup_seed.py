"""Seeded database for the followup tests (TEST_PLAN 8 plus the two extra Anita rows of 10).

Built with Store.apply_ingest from directly constructed Item/Mention objects.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from actiontrack.models import Header, Item, Mention, Note
from actiontrack.store import Store

TODAY = date(2026, 10, 22)

# label, owner, task, due, status, collaborators
ROWS: list[tuple[str, str, str, date | None, str, list[str]]] = [
    ("a1", "Sam Okafor", "cut cloud costs", date(2026, 10, 9), "open", []),
    ("a2", "Sam Okafor", "propose on-call rotation", date(2026, 10, 15), "open", []),
    ("a3", "Sam Okafor", "confirm cloud budget", date(2026, 9, 18), "done", []),
    ("a4", "Anita Desai", "refresh brand kit", date(2026, 10, 22), "open", []),
    ("a5", "Anita Desai", "audit colour contrast", date(2026, 10, 30), "open", []),
    ("a6", "Priya Nair", "send revised quote", None, "open", []),
    ("a7", "Ambiguous (Priya)", "own the hiring plan", None, "open", []),
    ("a8", "Unassigned", "write the changelog", None, "open", []),
    ("a9", "Anita Desai", "share wireframes", date(2026, 9, 24), "open", []),
    ("a10", "Anita Desai", "agree on component API", None, "open", ["Rahul"]),
    ("b1", "Priya Shah", "review pricing sheet", date(2026, 10, 1), "open", []),
    ("b2", "Karan Joshi", "freeze invoice edits", date(2026, 10, 1), "done", []),
]


def seed(path: Path, rows=None) -> dict[str, str]:
    """Create the db at ``path``. Returns label -> 8-char id."""
    rows = ROWS if rows is None else rows
    st = Store(path)
    notes, ms, items = [], [], []
    ids: dict[str, str] = {}
    for n, (label, owner, task, due, status, collabs) in enumerate(rows, start=1):
        iid = f"{n:02d}{label}".ljust(8, "0")[:8]
        ids[label] = iid
        f = f"2026-10-{n:02d}-seed-{label}.md"
        kind = (
            "unassigned"
            if owner == "Unassigned"
            else "ambiguous"
            if owner.startswith("Ambiguous")
            else "person"
        )
        notes.append(
            Note(
                file=f,
                header=Header(None, None, date(2026, 9, 1), "header", []),
                content_hash=f"h-{label}",
            )
        )
        ms.append(
            Mention(
                file=f,
                line_no=3,
                syntax="checkbox",
                raw_line=f"- [ ] {owner} to {task}",
                owner_raw=owner.split()[0],
                owner=owner,
                owner_kind=kind,
                collaborators=collabs,
                task=task,
                task_key=task,
                due=due,
                due_raw=None,
                checked=status == "done",
                item_id=iid,
            )
        )
        items.append(
            Item(
                id=iid,
                id_key=f"{owner}|{task}",
                owner=owner,
                owner_kind=kind,
                collaborators=collabs,
                task=task,
                due=due,
                due_raw=None,
                status=status,
                done_manual=False,
                first_file=f,
                latest_file=f,
                mention_count=1,
            )
        )
    st.apply_ingest(notes, ms, items)
    st.close()
    return ids
