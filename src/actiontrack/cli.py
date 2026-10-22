import functools
import os
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated, Any, ParamSpec, TypeVar

import typer

from actiontrack.dates import is_overdue
from actiontrack.drafts import DraftSink, DryRunSink, FileSink, GmailMcpSink, LazySink
from actiontrack.errors import ActiontrackError, DraftError, SinkUnavailable, UsageError
from actiontrack.followup import (
    FollowupResult,
    load_email_map,
    outstanding_owners,
    run_followup,
)
from actiontrack.ingest import run_ingest
from actiontrack.models import IngestResult, Item
from actiontrack.store import STATUSES, Store

app = typer.Typer(help="Track action items from meeting notes.", no_args_is_help=True)

P = ParamSpec("P")
R = TypeVar("R")


def resolve_db(db: Path | None) -> Path:
    """--db, then ACTIONTRACK_DB, then ./actiontrack.db (D3)."""
    if db is not None:
        return db
    env = os.environ.get("ACTIONTRACK_DB")
    return Path(env) if env else Path("actiontrack.db")


def parse_iso_date(value: str, flag: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise UsageError(f"invalid {flag} {value!r}: expected YYYY-MM-DD") from None


def resolve_today(today: str | None) -> date:
    """The only place the system clock is read (ARCHITECTURE principle 3)."""
    return parse_iso_date(today, "--today") if today else date.today()


def handle_errors(fn: Callable[P, R]) -> Callable[P, R]:
    """Print 'error: <message>' to stderr and exit 2 (usage) or 1 (anything else expected)."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except ActiontrackError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(2 if isinstance(exc, UsageError) else 1) from exc

    return wrapper


def render_ingest_summary(
    result: IngestResult, folder: str | Path | None = None, *, warnings: bool = False
) -> str:
    """SPEC 3.1 summary. The Warnings block is appended only when `warnings=True`.

    The CLI prints the summary on stdout and the warnings block on stderr (SPEC 2).
    """
    where = f" in {folder}" if folder is not None else ""
    width = len(str(max(result.scanned, result.items_found, 1)))
    c = result.counts
    merged = result.items_found - result.items_unique
    lines = [
        f"Scanned {result.scanned} files{where}",
        f"  Ingested:  {result.ingested:>{width}} notes",
        f"  Skipped:   {len(result.skipped):>{width}} files",
        f"  Items:     {result.items_found:>{width}} found -> {result.items_unique} unique"
        f" ({merged} duplicates merged)",
        f"             new {c.new}, updated {c.updated}, unchanged {c.unchanged}",
    ]
    if result.skipped:
        pad = max(len(s.file) for s in result.skipped)
        lines += ["", "Skipped files:"]
        lines += [f"  {s.file.ljust(pad)}   {s.reason}" for s in result.skipped]
    if warnings and result.warnings:
        lines += ["", *_render_warnings(result.warnings)]
    return "\n".join(lines)


def _render_warnings(warnings: list[str]) -> list[str]:
    return ["Warnings:", *(f"  {w}" for w in warnings)]


@app.command()
@handle_errors
def ingest(
    folder: Annotated[Path, typer.Argument(help="Folder of .md meeting notes (not recursive).")],
    db: Annotated[Path | None, typer.Option(help="SQLite file.")] = None,
) -> None:
    """Parse every .md note in FOLDER and store its action items."""
    # Validate before Store() so a bad folder never creates a database file (I13).
    if not folder.exists():
        raise UsageError(f"folder not found: {folder}")
    if not folder.is_dir():
        raise UsageError(f"not a directory: {folder}")
    with Store(resolve_db(db)) as store:
        result = run_ingest(folder, store)
    typer.echo(render_ingest_summary(result, folder))
    if result.warnings:
        typer.echo("\n".join(_render_warnings(result.warnings)), err=True)


_TABLE_HEADERS = ("ID", "STATUS", "OWNER", "DUE", "TASK", "SOURCE")
_ITEM_ID_RE = re.compile(r"[0-9a-f]{8}")


def _display_status(item: Item, today: date) -> str:
    return "overdue" if is_overdue(item.status, item.due, today) else item.status


def render_table(items: list[Item], today: date) -> str:
    """Fixed-width table plus an 'N items' footer. Pure: same input, same bytes."""
    if not items:
        return "No items found."
    rows = [
        (
            it.id,
            _display_status(it, today),
            it.owner,
            it.due.isoformat() if it.due else "-",
            it.task,
            it.latest_file + (f" (+{it.mention_count - 1})" if it.mention_count > 1 else ""),
        )
        for it in items
    ]
    widths = [max(len(r[c]) for r in [_TABLE_HEADERS, *rows]) for c in range(5)]
    lines = [
        "  ".join(cell.ljust(widths[c]) for c, cell in enumerate(r[:5])) + "  " + r[5]
        for r in [_TABLE_HEADERS, *rows]
    ]
    lines.append(f"{len(items)} item" + ("" if len(items) == 1 else "s"))
    return "\n".join(lines)


@app.command("list")
@handle_errors
def list_(
    owner: Annotated[str | None, typer.Option(help="Full name, first name or Unassigned.")] = None,
    status: Annotated[str | None, typer.Option(help="open, done or overdue.")] = None,
    due_before: Annotated[str | None, typer.Option(help="YYYY-MM-DD, strictly before.")] = None,
    today: Annotated[str | None, typer.Option(help="YYYY-MM-DD, for the overdue check.")] = None,
    db: Annotated[Path | None, typer.Option(help="SQLite file.")] = None,
) -> None:
    """List action items."""
    if status is not None and status not in STATUSES:
        raise UsageError(f"invalid --status {status!r}: use one of {', '.join(STATUSES)}")
    before = parse_iso_date(due_before, "--due-before") if due_before else None
    today_date = resolve_today(today)
    path = resolve_db(db)
    if not path.exists():
        # L23: a missing database is an empty one; `list` must not create the file.
        typer.echo("No items found.")
        return
    with Store(path) as store:
        result = store.list_items(owner, status, before, today_date)
    for warning in result.warnings:
        typer.echo(f"warning: {warning}", err=True)
    typer.echo(render_table(result.items, today_date))


@app.command()
@handle_errors
def done(
    item_id: str,
    db: Annotated[Path | None, typer.Option(help="SQLite file.")] = None,
) -> None:
    """Mark an action item done."""
    key = item_id.strip().lower()
    if not _ITEM_ID_RE.fullmatch(key):
        raise UsageError(f"invalid item id {item_id.strip()!r}: expected 8 hex characters")
    path = resolve_db(db)
    item = None
    if path.exists():  # never create a database just to say "not found"
        with Store(path) as store:
            item = store.get_item(key)
            if item is not None:
                # False means someone else closed it between get and update: still success.
                if item.status == "done" or not store.mark_done(key):
                    typer.echo(f"Already done: {key}")
                    return
    if item is None:
        raise UsageError(f"no item with id {key}")
    typer.echo(f"Marked done: {key}  {item.owner}  {item.task}")


def get_mcp_client() -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """The ONE place the Gmail MCP client is obtained: `call_tool(name, args) -> dict`.

    No MCP client exists in this environment, so this raises SinkUnavailable. To wire the real
    connector, return a callable here that forwards to the authorized Gmail MCP server, and
    confirm the draft tool name in `actiontrack.drafts.DRAFT_TOOL`. Tests monkeypatch this.
    """
    raise SinkUnavailable(
        "Gmail connector not available: no MCP client is configured. Authorize the Gmail "
        "connector (claude.ai connector settings, or `claude mcp` / /mcp) and run again. "
        "Use --dry-run to preview the email without creating a draft."
    )


def _count_text(result: FollowupResult) -> str:
    return ", ".join(
        part
        for part in (
            f"{result.overdue} overdue" if result.overdue else "",
            f"{result.open} open" if result.open else "",
        )
        if part
    )


def _echo_result(result: FollowupResult, *, out: Path | None, dry_run: bool) -> None:
    counts = _count_text(result)
    if out is not None:
        typer.echo(f"Wrote follow-up for {result.owner} (To: {result.to or '<blank>'}): {counts}")
        typer.echo(f"File: {result.draft_id} (no Gmail draft was created; nothing was sent)")
    elif dry_run:
        typer.echo(f"Dry run for {result.owner}: {counts}. No draft was created; nothing was sent.")
    else:
        typer.echo(f"Draft created for {result.owner} (To: {result.to or '<blank>'}): {counts}")
        typer.echo(f"Draft id: {result.draft_id} (review it in Gmail Drafts; nothing was sent)")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _run_all(
    store: Store,
    sink: DraftSink,
    today: date,
    emails: dict[str, str] | None,
    *,
    out: Path | None,
    dry_run: bool,
) -> None:
    """SPEC 3.4 `--all`: one follow-up per person with open items, then a summary."""
    people, skipped = outstanding_owners(store)
    done: list[FollowupResult] = []
    for name in people:
        try:
            result = run_followup(name, store, sink, today, emails)
        except DraftError as exc:  # stop at once, no retry: a retry could duplicate a draft
            raise type(exc)(f"{name}: {exc}") from exc
        if result.draft_id is None:
            continue
        done.append(result)
        _echo_result(result, out=out, dry_run=dry_run)
    if not done:
        typer.echo("No open or overdue items for any owner.")
    else:
        typer.echo("")
        if out is not None:
            typer.echo(f"{_plural(len(done), 'file')} written to {out}")
        elif dry_run:
            typer.echo(
                f"{_plural(len(done), 'email')} previewed; no drafts were created; nothing was sent"
            )
        else:
            typer.echo(
                f"{_plural(len(done), 'draft')} created (review in Gmail Drafts; nothing was sent)"
            )
        no_address = [r.owner for r in done if not r.to]
        if no_address:
            typer.echo(
                f"No email address for {_plural(len(no_address), 'owner')}: {', '.join(no_address)}"
            )
    if skipped:
        pad = max(len(o) for o, _ in skipped)
        typer.echo("Skipped (no resolved owner):")
        for owner, n in skipped:
            typer.echo(f"  {owner.ljust(pad)}  {_plural(n, 'item')}")


@app.command()
@handle_errors
def followup(
    owner: Annotated[
        str | None, typer.Argument(help='Full name, e.g. "Priya Nair". Omit with --all.')
    ] = None,
    all_owners: Annotated[
        bool, typer.Option("--all", help="Follow up every owner with open items.")
    ] = False,
    today: Annotated[str | None, typer.Option(help="YYYY-MM-DD, for the overdue check.")] = None,
    email_map: Annotated[Path | None, typer.Option(help="CSV with owner,email columns.")] = None,
    dry_run: Annotated[bool, typer.Option(help="Print the email; create no draft.")] = False,
    out: Annotated[
        Path | None, typer.Option(help="Write the email to a file in this folder, not Gmail.")
    ] = None,
    db: Annotated[Path | None, typer.Option(help="SQLite file.")] = None,
) -> None:
    """Create a Gmail draft (never sent) for OWNER's open items, or for everyone with --all."""
    if out is not None and dry_run:
        raise UsageError("--out and --dry-run cannot be used together")
    if all_owners and owner is not None:
        raise UsageError("--all takes no owner: use either an owner name or --all")
    if not all_owners and owner is None:
        raise UsageError("give an owner name, or --all for every owner")
    if out is not None and out.exists() and not out.is_dir():
        raise UsageError(f"--out {out} exists and is not a folder")
    today_date = resolve_today(today)
    emails = load_email_map(email_map) if email_map is not None else None
    path = resolve_db(db)
    if not path.exists():  # never create a database just to say "unknown owner"
        who = "no items" if all_owners else f'unknown owner "{owner}"'
        raise UsageError(f"{who}: no database at {path}; run ingest first")
    sink: DraftSink
    if out is not None:
        sink = FileSink(out)
    elif dry_run:
        sink = DryRunSink()
    else:
        sink = LazySink(lambda: GmailMcpSink(get_mcp_client()))
    with Store(path) as store:
        if all_owners:
            _run_all(store, sink, today_date, emails, out=out, dry_run=dry_run)
            return
        assert owner is not None
        result = run_followup(owner, store, sink, today_date, emails)
    if result.draft_id is None:
        typer.echo(result.message or f"No open or overdue items for {result.owner}.")
        return
    _echo_result(result, out=out, dry_run=dry_run)
    for warning in result.warnings:
        typer.echo(f"warning: {warning}", err=True)


def main() -> None:
    app()
