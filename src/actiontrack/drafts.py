"""The DraftSink boundary (ARCHITECTURE 5): everything that can reach Gmail goes through here.

The interface has ONE method, ``create_draft``. There is deliberately no way to deliver a
message from any sink, so code holding a ``DraftSink`` cannot do it even by mistake.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TextIO

from actiontrack.errors import ActiontrackError, DraftError, SinkUnavailable
from actiontrack.models import Draft, DraftResult

__all__ = [
    "ALLOWED_TOOLS",
    "DRAFT_TOOL",
    "Draft",
    "DraftResult",
    "DraftSink",
    "DryRunSink",
    "FileSink",
    "GmailMcpSink",
    "InMemorySink",
    "LazySink",
]

# The single Gmail MCP tool this program may call. Adjust this ONE constant when the real
# connector's draft-creation tool name is confirmed. Nothing else is ever allow-listed.
DRAFT_TOOL = "create_draft"
ALLOWED_TOOLS: frozenset[str] = frozenset({DRAFT_TOOL})


class DraftSink(Protocol):
    def create_draft(self, draft: Draft) -> DraftResult:
        """Create ONE draft. Raises DraftError on failure, SinkUnavailable if the
        connector is missing or unauthorized."""
        ...


class InMemorySink:
    """Records drafts for tests."""

    def __init__(self) -> None:
        self.drafts: list[Draft] = []

    def create_draft(self, draft: Draft) -> DraftResult:
        self.drafts.append(draft)
        return DraftResult(draft_id=f"mem-{len(self.drafts)}", to=draft.to)


class DryRunSink:
    """Prints the full email to stdout and creates nothing."""

    def __init__(self, out: TextIO | None = None) -> None:
        self._out = out

    def create_draft(self, draft: Draft) -> DraftResult:
        out = self._out or sys.stdout
        print(f"To: {draft.to or ''}".rstrip(), file=out)
        print(f"Subject: {draft.subject}", file=out)
        print("", file=out)
        print(draft.body, file=out)
        return DraftResult(draft_id="dry-run", to=draft.to)


class FileSink:
    """Writes the email to ``<folder>/<slug>.txt`` and creates no Gmail draft (SPEC D25).

    One file per owner: re-running for an owner overwrites that owner's file only.
    """

    def __init__(self, folder: Path) -> None:
        self._folder = folder

    def create_draft(self, draft: Draft) -> DraftResult:
        slug = re.sub(r"[^a-z0-9]+", "-", draft.owner.lower()).strip("-")
        if not slug:
            raise DraftError(f"cannot name a file for owner {draft.owner!r}")
        path = self._folder / f"{slug}.txt"
        text = f"To: {draft.to or ''}".rstrip() + f"\nSubject: {draft.subject}\n\n{draft.body}\n"
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise DraftError(f"cannot write {path}: {exc}") from exc
        return DraftResult(draft_id=str(path), to=draft.to)


class LazySink:
    """Builds the real sink on first use, so validation errors surface before any connector
    problem (ARCHITECTURE 6: validation happens before any sink call)."""

    def __init__(self, factory: Callable[[], DraftSink]) -> None:
        self._factory = factory
        self._sink: DraftSink | None = None

    def create_draft(self, draft: Draft) -> DraftResult:
        if self._sink is None:
            self._sink = self._factory()
        return self._sink.create_draft(draft)


class GmailMcpSink:
    """Adapter over the Gmail MCP connector, via an injected ``call_tool(name, args) -> dict``.

    Only ``DRAFT_TOOL`` can ever be invoked. The payload has exactly three keys. No retries.
    """

    def __init__(self, call_tool: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        self._call_tool = call_tool

    def create_draft(self, draft: Draft) -> DraftResult:
        args = {"to": draft.to or "", "subject": draft.subject, "body": draft.body}
        try:
            result = self._invoke(DRAFT_TOOL, args)
        except ActiontrackError:
            raise
        except (ConnectionError, PermissionError, TimeoutError) as exc:
            raise SinkUnavailable(
                f"Gmail connector unavailable or not authorized: {exc}. "
                "Authorize the Gmail connector and run the command again."
            ) from exc
        except Exception as exc:
            raise DraftError(f"Gmail did not create the draft: {exc}") from exc
        draft_id = _extract_id(result)
        if not draft_id:
            raise DraftError("Gmail connector returned no draft id; the draft may not exist")
        return DraftResult(draft_id=draft_id, to=draft.to)

    def _invoke(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name not in ALLOWED_TOOLS:
            raise DraftError(f"tool {name!r} is not allowed: only {sorted(ALLOWED_TOOLS)}")
        return self._call_tool(name, args)


def _extract_id(result: object) -> str | None:
    if not isinstance(result, dict):
        return None
    for key in ("draft_id", "id", "draftId"):
        value = result.get(key)
        if isinstance(value, str) and value:
            return value
    return None
