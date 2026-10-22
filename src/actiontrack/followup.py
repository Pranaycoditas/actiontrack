"""Stage 6: build the follow-up email and hand it to a sink (SPEC 3.4 and 7.2).

Knows nothing about Gmail or SQLite beyond the Store query API. The clock is never read here:
``today`` is always passed in.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from actiontrack.dates import is_overdue
from actiontrack.drafts import DraftSink
from actiontrack.errors import UsageError
from actiontrack.models import Draft, Item
from actiontrack.store import Store

__all__ = ["FollowupResult", "build_draft", "load_email_map", "outstanding_owners", "run_followup"]

_UNASSIGNED = "unassigned"
_AMBIGUOUS_PREFIX = "ambiguous ("
_CLOSING = "If any of these are done or need a new date, reply and I will update the tracker."


@dataclass(frozen=True)
class FollowupResult:
    owner: str
    draft_id: str | None = None
    to: str | None = None
    overdue: int = 0
    open: int = 0
    warnings: list[str] = field(default_factory=list)
    message: str | None = None  # set when there was nothing to follow up


def _sort_key(it: Item) -> tuple[bool, date, str]:
    return (it.due is None, it.due or date.max, it.id)


def _line(it: Item, today: date) -> str:
    task = it.task
    if it.collaborators:
        task += f" (with {', '.join(it.collaborators)})"
    if it.due is None:
        due = "no due date"
    elif is_overdue(it.status, it.due, today):
        days = (today - it.due).days
        due = f"due {it.due.isoformat()}, {days} {'day' if days == 1 else 'days'} overdue"
    else:
        due = f"due {it.due.isoformat()}"
    return f"- {task} ({due}) [{it.id}] - from {it.latest_file}"


def build_draft(owner: str, items: list[Item], today: date, to: str | None) -> Draft | None:
    """Format the email for ``owner``. None when nothing is outstanding."""
    mine = [i for i in items if i.status != "done" and i.owner_kind == "person"]
    overdue = sorted((i for i in mine if is_overdue(i.status, i.due, today)), key=_sort_key)
    open_ = sorted((i for i in mine if not is_overdue(i.status, i.due, today)), key=_sort_key)
    if not overdue and not open_:
        return None

    counts = []
    if overdue:
        counts.append(f"{len(overdue)} overdue")
    if open_:
        counts.append(f"{len(open_)} open")
    subject = f"Action items follow-up: {owner} ({', '.join(counts)})"

    first = owner.split()[0] if owner.split() else owner
    parts = [
        f"Hi {first},",
        f"Here are your outstanding action items as of {today.isoformat()}.",
    ]
    if overdue:
        parts.append("\n".join(["Overdue", *(_line(i, today) for i in overdue)]))
    if open_:
        parts.append("\n".join(["Open", *(_line(i, today) for i in open_)]))
    parts += [_CLOSING, "Thanks,"]
    return Draft(owner=owner, to=to, subject=subject, body="\n\n".join(parts))


def _resolve_owner(owner: str, store: Store) -> str:
    """Validate and canonicalise ``owner`` before any sink call. Raises UsageError."""
    name = " ".join(owner.split())
    if not name:
        raise UsageError("owner is required")
    low = name.lower()
    if low == _UNASSIGNED or low.startswith(_AMBIGUOUS_PREFIX):
        raise UsageError(
            f'cannot follow up "{name}": items without a resolved owner have no one to email'
        )
    stored = store.owners()
    people = [
        o
        for o in stored
        if o.lower() != _UNASSIGNED and not o.lower().startswith(_AMBIGUOUS_PREFIX)
    ]
    for p in people:
        if p.lower() == low:
            return p
    if len(name.split()) == 1:
        matches = [p for p in people if p.split()[0].lower() == low]
        shared_ambiguous = f"{_AMBIGUOUS_PREFIX}{low})" in {o.lower() for o in stored}
        if len(matches) >= 2:
            quoted = " or ".join(f'"{m}"' for m in matches)
            raise UsageError(f'ambiguous owner "{name}": use {quoted}')
        if len(matches) == 1 and not shared_ambiguous:
            return matches[0]
        if len(matches) == 1:
            raise UsageError(
                f'ambiguous owner "{name}": use "{matches[0]}" or the full name of the other {name}'
            )
        if shared_ambiguous:
            raise UsageError(f'ambiguous owner "{name}": use a full name')
    raise UsageError(f'unknown owner "{name}"')


def run_followup(
    owner: str,
    store: Store,
    sink: DraftSink,
    today: date,
    email_map: dict[str, str] | None,
) -> FollowupResult:
    name = _resolve_owner(owner, store)
    items = store.open_items_for(name)
    lookup = {" ".join(k.split()).lower(): v for k, v in (email_map or {}).items()}
    to = lookup.get(name.lower()) or None
    draft = build_draft(name, items, today, to)
    if draft is None:
        return FollowupResult(owner=name, message=f"No open or overdue items for {name}.")

    result = sink.create_draft(draft)

    mine = [i for i in items if i.status != "done"]
    n_over = sum(1 for i in mine if is_overdue(i.status, i.due, today))
    warnings: list[str] = []
    first = name.split()[0]
    ambiguous = store.ambiguous_count(first)
    if ambiguous:
        warnings.append(f'{ambiguous} items for "{first}" are ambiguous and not included')
    return FollowupResult(
        owner=name,
        draft_id=result.draft_id,
        to=result.to,
        overdue=n_over,
        open=len(mine) - n_over,
        warnings=warnings,
    )


def outstanding_owners(store: Store) -> tuple[list[str], list[tuple[str, int]]]:
    """For `--all`: people with open items, and `(owner, count)` skipped for having no resolved
    owner (ambiguous or unassigned). Both sorted by name."""
    people: list[str] = []
    skipped: list[tuple[str, int]] = []
    for owner, kind, n in store.open_owner_counts():
        if kind == "person":
            people.append(owner)
        else:
            skipped.append((owner, n))
    return people, skipped


def load_email_map(path: Path) -> dict[str, str]:
    """Read a CSV with header ``owner,email``. Missing file or bad header -> UsageError."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            fields = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
            fields = ["owner" if f == "name" else f for f in fields]  # `name` means `owner`
            if "owner" not in fields or "email" not in fields:
                raise UsageError(f"bad --email-map {path}: header must be owner,email")
            reader.fieldnames = fields
            out: dict[str, str] = {}
            for row in reader:
                who = (row.get("owner") or "").strip()
                mail = (row.get("email") or "").strip()
                if who and mail:
                    out[who] = mail
            return out
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise UsageError(f"cannot read --email-map {path}: {exc}") from exc
