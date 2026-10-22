# actiontrack

CLI that reads a folder of markdown meeting notes, tracks the action items in
SQLite, and drafts follow-up emails for review. Notes are messy: mixed date
formats, five action-item syntaxes, duplicates carried across meetings, owners
by first name only, and a few deliberately malformed files.

Commands:
- `actiontrack ingest <folder>`: parse every .md note, store items (owner, task, due, source file, status)
- `actiontrack list`: filters `--owner`, `--status open|done|overdue`, `--due-before <date>`
- `actiontrack done <id>`: mark an item done
- `actiontrack followup <owner>`: one Gmail draft per owner covering open and overdue items.
  `--all` does every owner, `--out <folder>` writes files, `--email-map` adds addresses

## Stack
Python 3.11+, Typer (CLI), SQLite via stdlib `sqlite3` (no ORM), pytest, ruff.

## Commands
- Install: `pip install -e ".[dev]"`
- Tests: `pytest` (single test: `pytest tests/test_x.py::test_name`)
- Lint and format: `ruff check .` and `ruff format .`
- Run the CLI: `actiontrack ingest notes/`, or `python -m actiontrack ...`
- Reproducible overdue output: pass `--today YYYY-MM-DD`

## Hard rules
- **Drafts only, never send.** NEVER send email. `followup` creates Gmail drafts
  only, via the Gmail MCP connector (or writes files with `--out`). No send calls
  anywhere in the code. The exact flow is in `docs/GMAIL_FLOW.md`.
- NEVER crash on a malformed note. Skip it, keep going, and list every skipped
  file and the reason in the ingest summary.
- Resolve relative due dates ("by Friday", "next Tuesday") against the MEETING
  date, never today's date. Only the overdue check compares against today.
- Item IDs must stay stable across re-ingest. Re-running ingest on the same
  folder must not change or duplicate IDs. Derive IDs from content, not from
  row order or insert time.
- Same-first-name owners (Priya Nair/Shah, Rahul Mehta/Verma): never guess.
  Resolve from attendees or an explicit initial, otherwise mark ambiguous.

## Workflow
- Read `docs/SPEC.md` before changing behavior.
- Write tests before code. Fixtures for the tricky notes live in `notes/`.
- Edge cases and the reasoning behind them: `docs/data-findings.md`.
