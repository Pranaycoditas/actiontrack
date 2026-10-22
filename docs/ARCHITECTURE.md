# actiontrack: Architecture

Companion to [SPEC.md](SPEC.md) (behavior) and [DATA_MODEL.md](DATA_MODEL.md) (tables and IDs). This file says how the code is split up. It does not restate behavior.

## 1. Design principles

1. **Pure core, thin edges.** Parsing, date resolution, owner resolution and dedupe are pure functions on plain data. File access, SQLite, the clock and Gmail sit at the edges and are passed in. This makes the tricky notes testable without a database, a clock or a network.
2. **One direction.** Each stage takes the previous stage's output. No stage imports a later one.
3. **The clock is an argument.** `today` is passed in and never read inside the core. Meeting-date resolution never sees it (hard rule).
4. **Drafts only, by construction.** The only way to reach Gmail is the `DraftSink` interface, which has no send method (section 5).
5. **Failure is per file.** A bad note becomes a `Skip` value. It is never an exception that escapes the reader or parser stage.

## 2. Pipeline

```
 folder
   |
   v
 [1 READ]        reader.py     files -> NoteFile | Skip(file, reason)
   |
   v
 [2 PARSE]       parser.py     NoteFile -> Note(header, attendees, [RawLine])
   |                                      (RawLine = action line + syntax + line_no)
   v
 [3 NORMALIZE]   dates.py      RawLine.due text  + meeting date -> due, due_raw
                 owners.py     RawLine.owner text + attendees + roster -> owner, kind, collaborators
                               => Mention
   |
   v
 [4 DEDUPE]      dedupe.py     [Mention] -> [Group]  (item id, merged fields)
   |
   v
 [5 STORE]       store.py      one transaction: meetings, mentions, items (upsert)
   |
   v
 IngestResult -> cli.py prints the summary


 --- later, separate commands ---

 cli list / done ----> store.py (queries) --------------------> cli.py renders table
 cli followup -------> store.py (open items for owner)
                         |
                         v
                  [6 FOLLOWUP]  followup.py   items + today -> Draft (subject, body)
                         |
                         v
                  drafts.DraftSink.create_draft(Draft) -> DraftResult
                         |
              +----------+-----------+
              |          |           |
        GmailMcpSink  DryRunSink  InMemorySink
        (real drafts) (prints)    (tests)
```

Stage 1 and 2 run on each file independently. Stages 3 and 4 need the **roster** (all attendees from all notes), so ingest is two passes: pass 1 reads and parses every file and collects attendees, pass 2 normalizes and dedupes (SPEC 3.1).

## 3. Package layout

```
src/actiontrack/
  __init__.py
  __main__.py     python -m actiontrack
  models.py       dataclasses shared by all stages
  errors.py       exception types
  reader.py       stage 1
  parser.py       stage 2
  dates.py        stage 3a
  owners.py       stage 3b
  dedupe.py       stage 4
  store.py        stage 5 and all queries
  ingest.py       orchestrates stages 1 to 5
  followup.py     stage 6 (builds the email, calls the sink)
  drafts.py       DraftSink and its implementations
  cli.py          Typer app, rendering, exit codes
tests/            one test module per source module, plus test_cli.py and test_notes_fixtures.py
```

## 4. Modules

Signatures are the intended public API. Underscore-prefixed names are private. All functions are typed.

### 4.1 `models.py`

Frozen dataclasses only, no logic.

| Type | Fields (summary) |
|---|---|
| `NoteFile` | `file`, `text` (normalised: BOM stripped, CRLF to LF), `content_hash` |
| `Skip` | `file`, `reason` (the exact text in SPEC 5.5) |
| `Header` | `title`, `date_text`, `date` (resolved or None), `date_source` (`header`/`filename`/`none`), `attendees` |
| `RawLine` | `line_no`, `syntax` (`checkbox`/`action`/`table`), `raw_line`, `checked`, `owner_text`, `task_text`, `due_text` |
| `Note` | `file`, `header`, `lines: list[RawLine]`, `warnings: list[str]` |
| `Mention` | the `mentions` table row (DATA_MODEL 2.2) minus `id` and `item_id` |
| `Item` | the `items` table row (DATA_MODEL 2.3) |
| `Draft` | `owner`, `to`, `subject`, `body` |
| `DraftResult` | `draft_id`, `to` |
| `IngestResult` | counts, `skipped: list[Skip]`, `warnings: list[str]` |

### 4.2 `errors.py`

```python
class ActiontrackError(Exception): ...      # base
class UsageError(ActiontrackError): ...     # maps to exit 2
class StoreError(ActiontrackError): ...     # exit 1
class DraftError(ActiontrackError): ...     # exit 1
class SinkUnavailable(DraftError): ...      # connector missing or unauthorized, exit 1
```

### 4.3 `reader.py` (stage 1)

**Responsibility:** turn a folder into decoded text or a reason to skip. Does no parsing.

```python
def read_folder(folder: Path) -> list[NoteFile | Skip]
def read_file(path: Path) -> NoteFile | Skip
```

- `read_folder` lists the folder non-recursively, sorted by filename (stable order), and calls `read_file` for each.
- `read_file` returns `Skip` for: not `.md`, zero bytes, NUL bytes or invalid UTF-8, or any `OSError`. Otherwise it strips the BOM, normalises CRLF, and hashes.
- Raises `UsageError` only if `folder` does not exist or is not a directory.

### 4.4 `parser.py` (stage 2)

**Responsibility:** structure only. Find the header, the attendees and the candidate action lines. It captures the owner and due **as text** and does not interpret them.

```python
def parse_note(note: NoteFile) -> Note | Skip
def parse_header(text: str, filename: str) -> Header
def find_action_lines(text: str) -> list[RawLine]
def split_owner_task_due(body: str) -> tuple[str | None, str, str | None]
```

- `parse_header` handles `# Meeting:` and YAML front matter, `Date:`/`date:`, and `Attendees:`/`attendees: [..]`. It calls `dates.parse_header_date` for the date and falls back to the filename prefix, setting `date_source` (SPEC 4.1).
- `find_action_lines` is a line scanner with a small state machine for fenced code blocks, HTML comments (including multi-line) and block quotes, so those lines are excluded. It then matches checkbox, `ACTION:` and table-row syntaxes (SPEC 3.1).
- `split_owner_task_due` handles `@handle:`, `<Name> to ...`, `Name (with X) to`, `A & B to`, and the due phrase split. It returns raw text for the owner and the due phrase.
- `parse_note` wraps everything in try/except. Any exception becomes `Skip(file, "parse error: <message>")`.

### 4.5 `dates.py` (stage 3a)

**Responsibility:** all date logic, as pure functions. No `datetime.today()` anywhere in this module.

```python
def parse_header_date(text: str) -> date | None
def resolve_due(phrase: str | None, meeting_date: date | None) -> DueResult
def is_overdue(status: str, due: date | None, today: date) -> bool
```

- `DueResult(due: date | None, raw: str | None, warning: str | None)`.
- `parse_header_date` accepts ISO, `9 September 2026` and `Monday, 14 September 2026`. Anything else returns None.
- `resolve_due` implements SPEC 6.1, rule by rule. Deadline keywords decide whether a phrase is a deadline at all. Phrases that are not deadlines return `due=None` with `raw` kept. With `meeting_date=None` only absolute dates resolve.
- `is_overdue` is the single definition of overdue (SPEC 7.1: not done, due not empty, `due < today`). `store` and `followup` both call it, so the rule lives in one place.

### 4.6 `owners.py` (stage 3b)

**Responsibility:** turn owner text into a resolved owner. Never guesses.

```python
def build_roster(attendee_lists: Iterable[list[str]]) -> Roster
def resolve_owner(owner_text: str | None, attendees: list[str], roster: Roster) -> OwnerResult
def parse_collaborators(owner_text: str, attendees: list[str], roster: Roster) -> list[str]
```

- `Roster` maps first name to the set of full names (`"priya" -> {"Priya Nair", "Priya Shah"}`).
- `OwnerResult(owner: str, kind: Literal["person","unassigned","ambiguous"], collaborators: list[str], warning: str | None)`.
- `resolve_owner` applies SPEC 5.3 in order: group words and no owner give `Unassigned`. A first name that maps to one roster person resolves to that person. Otherwise an explicit initial resolves it. Otherwise exactly one attendee with that first name resolves it. Otherwise `Ambiguous (First)` with a warning.
- No project-cluster inference or heuristics of any kind.

### 4.7 `dedupe.py` (stage 4)

**Responsibility:** merge mentions into items and assign IDs (DATA_MODEL 3 and 4). Pure.

```python
def task_key(task: str) -> str
def similarity(a: str, b: str) -> float                       # token Jaccard
def group_mentions(mentions: list[Mention]) -> list[Group]
def make_item(group: Group) -> Item
def item_id(owner: str, task_key: str, taken: set[str]) -> tuple[str, str]   # (id, id_key)
```

- `group_mentions` sorts by `(meeting_date, file, line_no)` (undated first), then applies the owner-equality and Jaccard >= 0.6 rule, picking the best-scoring group.
- `make_item` computes the merged fields: latest wording, latest non-empty due, status from the latest mention. It sets `first_file`, `latest_file` and `mention_count`.
- `item_id` hashes the earliest mention's key and resolves collisions with the `#2`, `#3` suffix.
- It never touches the database and ignores `done_manual`. The store layer carries that over.

### 4.8 `store.py` (stage 5 and queries)

**Responsibility:** the only module that imports `sqlite3`. Owns the schema, transactions and every SQL string.

```python
class Store:
    def __init__(self, path: Path) -> None            # opens, enables foreign keys, creates schema
    def close(self) -> None
    def known_hashes(self) -> dict[str, str]          # file -> content_hash
    def all_mentions(self) -> list[Mention]
    def apply_ingest(self, notes: list[Note], mentions: list[Mention], items: list[Item]) -> IngestCounts
    def list_items(self, owner: str | None, status: str | None,
                   due_before: date | None, today: date) -> list[Item]
    def get_item(self, item_id: str) -> Item | None
    def mark_done(self, item_id: str) -> bool         # False if it was already done
    def open_items_for(self, owner: str) -> list[Item]
    def ambiguous_count(self, first_name: str) -> int
    def owners(self) -> list[str]
```

- `apply_ingest` runs the DATA_MODEL section 5 write procedure in one transaction. It replaces the mentions of re-read files, upserts items by ID, carries `done_manual` over, and deletes items with no mentions. On any error it rolls back and raises `StoreError`.
- Queries use parameters only (no string-built SQL). Status filters are the ones in DATA_MODEL section 7.
- `list_items` does owner matching (full name, bare first name, `Unassigned`) and returns a warning-carrying result for bare first names shared by two people.

### 4.9 `ingest.py` (orchestration)

**Responsibility:** run stages 1 to 5 in order and return an `IngestResult`. Contains no parsing or SQL of its own.

```python
def run_ingest(folder: Path, store: Store) -> IngestResult
```

Steps:

1. `reader.read_folder`.
2. `parser.parse_note` for each `NoteFile`.
3. `owners.build_roster` from all notes' attendees.
4. For each action line: `dates.resolve_due` and `owners.resolve_owner` build a `Mention`.
5. Combine with mentions already in the store for files that are not in this folder (D10).
6. `dedupe.group_mentions` and `make_item`.
7. `store.apply_ingest`.

A `Skip` at any stage is collected, never raised.

### 4.10 `followup.py` (stage 6)

**Responsibility:** build the email and hand it to a sink. Knows nothing about Gmail or SQLite.

```python
def build_draft(owner: str, items: list[Item], today: date, to: str | None) -> Draft | None
def run_followup(owner: str, store: Store, sink: DraftSink, today: date,
                 email_map: dict[str, str] | None) -> FollowupResult
def load_email_map(path: Path) -> dict[str, str]
```

- `build_draft` splits items with `dates.is_overdue`, sorts them, and formats subject and body (SPEC 7.2). It returns None when there is nothing to send.
- `run_followup` validates the owner (bare ambiguous first name or `Unassigned` raises `UsageError`), fetches items from the store, builds the draft, and calls `sink.create_draft`. It never constructs a sink itself.
- `FollowupResult` carries the draft ID or None, counts, and a warning for ambiguous items left out.

### 4.11 `drafts.py` (the DraftSink boundary)

See section 5.

### 4.12 `cli.py`

**Responsibility:** parse arguments, wire the modules together, print, and map exceptions to exit codes. Holds no business logic.

```python
app = typer.Typer()

@app.command() def ingest(folder: Path, db: Path | None = None) -> None
@app.command("list") def list_(owner: str | None = None, status: StatusOpt | None = None,
                               due_before: str | None = None, today: str | None = None,
                               db: Path | None = None) -> None
@app.command() def done(item_id: str, db: Path | None = None) -> None
@app.command() def followup(owner: str, today: str | None = None, email_map: Path | None = None,
                            dry_run: bool = False, db: Path | None = None) -> None
def render_table(items: list[Item], today: date) -> str
def render_ingest_summary(result: IngestResult) -> str
def main() -> None            # entry point and catches ActiontrackError
```

- `db` resolves in this order: `--db`, `ACTIONTRACK_DB`, `./actiontrack.db` (D3).
- `today` resolves from `--today` or `date.today()` here and nowhere else.
- The sink is chosen here: `DryRunSink` when `--dry-run`, otherwise `GmailMcpSink`.
- Invalid enum or date values raise `UsageError`, which `main` turns into exit 2.

## 5. DraftSink (Gmail boundary)

Everything that can talk to Gmail goes through this interface, defined in `drafts.py`.

```python
from typing import Protocol

@dataclass(frozen=True)
class Draft:
    owner: str
    to: str | None          # blank allowed: notes contain no addresses
    subject: str
    body: str               # plain text

@dataclass(frozen=True)
class DraftResult:
    draft_id: str
    to: str | None

class DraftSink(Protocol):
    def create_draft(self, draft: Draft) -> DraftResult:
        """Create ONE draft. Never sends. Raises DraftError on failure,
        SinkUnavailable if the connector is missing or unauthorized."""
```

**There is deliberately no `send`, `send_draft`, `reply` or `schedule` method.** Code that holds a `DraftSink` cannot send even by mistake.

| Implementation | Used by | Behavior |
|---|---|---|
| `GmailMcpSink` | `followup` by default | Adapter over the Gmail MCP connector. Calls the connector's create-draft tool and nothing else. Maps connection and authorization failures to `SinkUnavailable`, other failures to `DraftError`. |
| `DryRunSink` | `followup --dry-run` | Writes the rendered email to stdout, returns a draft ID of `dry-run`. Creates nothing. |
| `InMemorySink` | tests | Appends to a list. Tests assert on subject, body, one draft per owner, and that the interface exposes nothing else. |

`GmailMcpSink` takes an injected client callable (`call_tool(name: str, args: dict) -> dict`) in its constructor. This keeps the MCP transport (D12) out of the logic. The adapter allow-lists exactly one tool name, the draft-creation tool, and raises on any other name.

**Guardrails that enforce the hard rule**

1. `tests/test_no_send.py` greps `src/` for `send` as a Gmail call name (`send_message`, `send_draft`, `messages.send`, `drafts.send` and similar) and fails if any appears. The word "send" is allowed in prose and in task text.
2. The `GmailMcpSink` tool allow-list test: any name other than the draft-creation tool raises.
3. `DraftSink` is a `Protocol` with one method, and a test asserts its member list equals `["create_draft"]`.

## 6. Error-handling policy

Principle: **an item or a file can fail. The run cannot, unless the database does.**

| Layer | Failure | Policy | Visible as |
|---|---|---|---|
| reader | empty, binary, non-`.md`, unreadable file | Return `Skip(file, reason)`. Never raise. | Listed under "Skipped files", exit 0 |
| reader | folder missing or not a directory | `UsageError` | exit 2 |
| parser | any exception while parsing one note | Catch in `parse_note`, return `Skip("parse error: ...")` | Skipped files, exit 0 |
| parser, dates, owners | unparseable header date, unparseable due, no attendees, weekday/date mismatch | Do not fail. Fall back (filename date, empty due, ambiguous owner) and record a warning | Warnings section, exit 0 |
| dedupe | hash collision | Deterministic re-hash with a `#n` suffix | invisible |
| store | SQLite error | Roll back the transaction, raise `StoreError`. The database is unchanged. | stderr message, exit 1 |
| cli | bad argument, unknown ID or owner, ambiguous bare first name | `UsageError` | stderr message, exit 2 |
| drafts | connector missing or unauthorized | `SinkUnavailable`. No draft is created. Nothing is retried. | stderr message with how to authorize, exit 1 |
| drafts | Gmail rejects the draft | `DraftError`, no retry that could create a duplicate | stderr, exit 1 |
| any | unexpected exception outside the above | `main` catches `ActiontrackError` only for clean messages. Anything else shows a traceback and exits 1. This is a bug, never part of a normal run. | exit 1 |

Rules that follow from this:

1. **No bare `except:` and no silent swallowing.** Every caught error either becomes a `Skip` or a warning that reaches the summary, or it is re-raised as an `ActiontrackError`.
2. **Skips and warnings are data, not logs.** They are returned in `IngestResult` and printed by the CLI, so tests can assert on them and the summary can list every skipped file with its reason (hard rule).
3. **Ingest is atomic.** A store failure leaves the previous database state intact. A skipped file never aborts the transaction.
4. **`followup` is all-or-nothing per owner.** Validation happens before any sink call, so a usage error never creates a partial draft.
5. **Messages are for people.** They name the file, ID or owner involved, say what to do, and never contain a traceback.

## 7. Testing map

Tests are written before the code (CLAUDE.md). Each module is testable alone because of principle 1.

| Test module | Covers | Needs |
|---|---|---|
| `test_dates.py` | every row of SPEC 6.2, overdue boundary (`due == today`) | nothing |
| `test_owners.py` | SPEC 5.3 table, initials, handles, joint and group owners | nothing |
| `test_parser.py` | the five action syntaxes, fenced, quoted and commented exclusions, header formats | strings |
| `test_reader.py` | empty, binary, `.txt`, CRLF, BOM | `tmp_path` |
| `test_dedupe.py` | Jaccard cases, ambiguous never merging, ID stability under wording drift | nothing |
| `test_store.py` | idempotent re-ingest (same IDs and row count), sticky manual done, rollback | in-memory SQLite |
| `test_followup.py` | email layout, ordering, exclusion of ambiguous and unassigned items | `InMemorySink` |
| `test_no_send.py` | section 5 guardrails | source tree |
| `test_notes_fixtures.py` | end-to-end ingest of `notes/`: skipped list is exactly the three files, ingest twice gives identical IDs | `notes/`, temp DB |
| `test_cli.py` | exit codes and output via Typer's `CliRunner`, `--today` | temp DB |
