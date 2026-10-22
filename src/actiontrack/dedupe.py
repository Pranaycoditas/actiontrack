"""Stage 4: merge mentions into items and assign stable IDs (DATA_MODEL 3 and 4).

Pure: no database, no clock. Output depends only on the set of mentions, never on their order.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date

from actiontrack.models import Item, Mention

__all__ = ["Group", "group_mentions", "item_id", "make_item", "match_key", "similarity", "task_key"]

THRESHOLD = 0.6
STOP_WORDS = frozenset("a an the to for of with and on in by at our up".split())
# Wording that drifts between meetings without changing the task (D24). Matching only: IDs
# hash `task_key`, never `match_key`.
QUALIFIERS = frozenset("first initial updated new latest start begin".split())
SYNONYMS = {"spike": "estimate"}


@dataclass
class Group:
    """Mentions of one task, in `(meeting_date, file, line_no)` order (undated first)."""

    owner: str
    owner_kind: str
    mentions: list[Mention] = field(default_factory=list)


def task_key(task: str) -> str:
    """Lowercase, punctuation to spaces, stop-words dropped, original order kept."""
    tokens = re.sub(r"[^0-9a-z]+", " ", task.lower()).split()
    return " ".join(t for t in tokens if t not in STOP_WORDS)


def match_key(key: str) -> str:
    """Looser key for duplicate matching: drop drift words, fold synonyms (never to empty)."""
    tokens = [SYNONYMS.get(t, t) for t in key.split()]
    kept = [t for t in tokens if t not in QUALIFIERS]
    return " ".join(kept or tokens)


def similarity(a: str, b: str) -> float:
    """Token Jaccard of two task keys. Two empty keys are identical (1.0)."""
    sa, sb = set(a.split()), set(b.split())
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def _order(m: Mention) -> tuple:
    # Undated first. The last two fields only break exact ties so the order is total.
    return (
        m.meeting_date is not None,
        m.meeting_date or date.min,
        m.file,
        m.line_no,
        m.task_key,
        m.raw_line,
    )


def group_mentions(mentions: list[Mention]) -> list[Group]:
    """Group mentions of the same task. Groups come back in creation (earliest-mention) order."""
    groups: list[Group] = []
    for m in sorted(mentions, key=_order):
        best: Group | None = None
        best_score = -1.0
        for g in groups:
            if g.owner != m.owner or g.owner_kind != m.owner_kind:
                continue
            mk_ = match_key(m.task_key)
            score = max(similarity(mk_, match_key(x.task_key)) for x in g.mentions)
            if score >= THRESHOLD and score > best_score:  # strict: ties keep the first group
                best, best_score = g, score
        if best is None:
            groups.append(Group(m.owner, m.owner_kind, [m]))
        else:
            best.mentions.append(m)
    return groups


def _hash8(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def item_id(owner: str, key: str, taken: set[str]) -> tuple[str, str]:
    """Return `(id, id_key)`. On a collision with `taken`, re-hash `id_key#2`, `#3`, ..."""
    base = f"{owner}|{key}"
    id_key = base
    n = 1
    while (digest := _hash8(id_key)) in taken:
        n += 1
        id_key = f"{base}#{n}"
    return digest, id_key


def make_item(group: Group, taken: set[str] | None = None) -> Item:
    """Merged item for a group. `done_manual` is always False; the store carries it over."""
    ms = group.mentions
    first, latest = ms[0], ms[-1]
    item_id_, id_key = item_id(group.owner, first.task_key, taken if taken is not None else set())

    with_due = next((m for m in reversed(ms) if m.due is not None), None)
    if with_due is not None:
        due, due_raw = with_due.due, with_due.due_raw
        if due_raw is None:
            due_raw = next((m.due_raw for m in reversed(ms) if m.due_raw), None)
    else:
        due = None
        due_raw = next((m.due_raw for m in reversed(ms) if m.due_raw), None)

    collaborators = next((list(m.collaborators) for m in reversed(ms) if m.collaborators), [])
    return Item(
        id=item_id_,
        id_key=id_key,
        owner=group.owner,
        owner_kind=group.owner_kind,  # type: ignore[arg-type]
        collaborators=collaborators,
        task=latest.task,
        due=due,
        due_raw=due_raw,
        status="done" if latest.checked else "open",
        done_manual=False,
        first_file=first.file,
        latest_file=latest.file,
        mention_count=len(ms),
    )
