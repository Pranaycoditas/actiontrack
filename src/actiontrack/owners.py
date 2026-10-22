"""Owner resolution for actiontrack (SPEC 4.2, 5.2, 5.3).

Turns the owner text of an action line into a resolved owner. It never guesses: a first name
shared by several roster people is resolved only from an explicit initial or from attendance,
otherwise it becomes ``Ambiguous (First)``. There is no project-cluster inference.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "OwnerResult",
    "Roster",
    "build_roster",
    "parse_collaborators",
    "resolve_owner",
]

UNASSIGNED = "Unassigned"
_GROUP_WORDS = frozenset({"everyone", "team", "everybody", "tbd", "someone", "anyone"})

Kind = Literal["person", "unassigned", "ambiguous"]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _key(name: str) -> str:
    return _clean(name).casefold()


@dataclass(frozen=True)
class Roster:
    """Maps a lower-cased first name to the set of full names seen in any attendee list."""

    by_first: dict[str, frozenset[str]] = field(default_factory=dict)

    def full_names(self, first: str) -> frozenset[str]:
        return self.by_first.get(_key(first), frozenset())

    def find_full(self, name: str) -> str | None:
        """Exact (case/space-insensitive) full-name match, or None."""
        target = _key(name)
        for names in self.by_first.values():
            for full in names:
                if _key(full) == target:
                    return full
        return None


@dataclass(frozen=True)
class OwnerResult:
    """A resolved owner. ``raw`` keeps the original owner text (for example ``Everyone``)."""

    owner: str
    kind: Kind
    collaborators: list[str] = field(default_factory=list)
    warning: str | None = None
    raw: str | None = None


def build_roster(attendee_lists: Iterable[list[str]]) -> Roster:
    """Collect every full name from every attendee list. Order of the input never matters."""
    seen: dict[str, str] = {}  # casefolded full name -> canonical spelling
    for attendees in attendee_lists:
        for name in attendees:
            full = _clean(name)
            if not full:
                continue
            k = full.casefold()
            seen[k] = min(seen[k], full) if k in seen else full
    grouped: dict[str, set[str]] = {}
    for full in seen.values():
        grouped.setdefault(full.split(" ")[0].casefold(), set()).add(full)
    return Roster({first: frozenset(names) for first, names in grouped.items()})


# --- parsing the owner text ----------------------------------------------------------------

_WITH_CLAUSE = re.compile(r"\(\s*with\s+([^)]*)\)", re.IGNORECASE)
_SEPARATOR = re.compile(r"\s*(?:&|\+|/|,|;|\band\b)\s*", re.IGNORECASE)
_INITIAL = re.compile(r"^(\S+) ([A-Za-z])\.?$")


def _tokens(owner_text: str) -> list[str]:
    """Split owner text into name tokens: primary first, then collaborators."""
    text = _clean(owner_text)
    withs = [m[1] for m in _WITH_CLAUSE.finditer(text)]
    text = _WITH_CLAUSE.sub(" ", text)
    out: list[str] = []
    for part in [text, *withs]:
        for tok in _SEPARATOR.split(part):
            tok = _clean(tok).lstrip("@").rstrip(":").strip()
            if tok:
                out.append(tok)
    return out


def _is_group(token: str) -> bool:
    return token.casefold() in _GROUP_WORDS


def _resolve_token(
    token: str, attendees: list[str], roster: Roster
) -> tuple[str, Kind, str | None]:
    """Resolve one name token to (owner, kind, warning)."""
    full = roster.find_full(token)
    if full is not None:
        return full, "person", None

    attending = {_key(a) for a in attendees}
    initial: str | None = None
    first = token
    m = _INITIAL.match(token)
    if m:
        first, initial = m[1], m[2].casefold()

    candidates = sorted(roster.full_names(first))
    if not candidates:
        shown = _clean(token).title() if " " not in token else _clean(token)
        return shown, "person", f"unknown owner: {shown}"
    if len(candidates) == 1:
        return candidates[0], "person", None

    here = [c for c in candidates if _key(c) in attending]

    if initial is not None:
        matching = [c for c in candidates if c.split(" ")[-1][:1].casefold() == initial]
        if len(matching) == 1:
            chosen = matching[0]
            warning = None
            if here and chosen not in here:
                warning = (
                    f'"{token}" resolved to {chosen} by initial, but only '
                    f"{', '.join(here)} attended"
                )
            return chosen, "person", warning

    if len(here) == 1:
        return here[0], "person", None

    first_name = candidates[0].split(" ")[0]
    reason = "no attendee list" if not attendees else "cannot tell from attendees or initial"
    return (
        f"Ambiguous ({first_name})",
        "ambiguous",
        f'ambiguous owner "{first_name}": {reason}; could be {" or ".join(candidates)}',
    )


def resolve_owner(owner_text: str | None, attendees: list[str], roster: Roster) -> OwnerResult:
    """Resolve owner text (including collaborators) per SPEC 5.3. Never guesses."""
    raw = _clean(owner_text) if owner_text and owner_text.strip() else None
    if raw is None:
        return OwnerResult(UNASSIGNED, "unassigned", [], None, None)
    tokens = _tokens(raw)
    if not tokens or _is_group(tokens[0]):
        return OwnerResult(UNASSIGNED, "unassigned", [], None, raw)

    warnings: list[str] = []
    owner, kind, warning = _resolve_token(tokens[0], attendees, roster)
    if warning:
        warnings.append(warning)
    collaborators: list[str] = []
    for token in tokens[1:]:
        if _is_group(token):
            continue
        name, _, warning = _resolve_token(token, attendees, roster)
        collaborators.append(name)
        if warning:
            warnings.append(warning)
    return OwnerResult(owner, kind, collaborators, "; ".join(warnings) or None, raw)


def parse_collaborators(owner_text: str, attendees: list[str], roster: Roster) -> list[str]:
    """Resolved collaborators of ``owner_text`` (everyone after the first listed name)."""
    return resolve_owner(owner_text, attendees, roster).collaborators
