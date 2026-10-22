# actiontrack: Data model

Companion to [SPEC.md](SPEC.md). Section numbers and decision IDs (D1..D23) refer to that file. SQLite via stdlib `sqlite3`, no ORM.

## 1. Overview

Three tables:

| Table | One row per | Role |
|---|---|---|
| `meetings` | ingested note file | Facts about the note: date, attendees, hash |
| `mentions` | action line found in a note | Raw evidence. Every appearance of a task in a note |
| `items` | unique task (after duplicate merging) | What `list`, `done` and `followup` work with |

**Key idea:** `mentions` is the source of truth and `items` is derived from it. On every ingest the mentions of each re-read file are rebuilt, and the items are recomputed from all mentions. The only state stored on an item that cannot be recomputed is a manual `done`.

```
meetings 1 ---- * mentions * ---- 1 items
 (file)          (file, line)       (id)
```

Pragmas: `PRAGMA foreign_keys = ON`. All dates are ISO `YYYY-MM-DD` text. All JSON columns are text produced by `json.dumps`.

## 2. Tables

### 2.1 `meetings`

```sql
CREATE TABLE meetings (
  file          TEXT PRIMARY KEY,
  title         TEXT,
  meeting_date  TEXT,
  date_source   TEXT NOT NULL CHECK (date_source IN ('header','filename','none')),
  attendees     TEXT NOT NULL DEFAULT '[]',
  content_hash  TEXT NOT NULL,
  ingested_at   TEXT NOT NULL
);
```

| Column | Type | Meaning |
|---|---|---|
| `file` | TEXT, PK | Base filename in the ingested folder (for example `2026-09-15-quote-portal-weekly.md`). The folder is not recursive, so it is unique. |
| `title` | TEXT, null | From `# Meeting: <title>` or YAML `title:`. Informational only. |
| `meeting_date` | TEXT, null | Resolved meeting date `M`. Null for undated notes (`untitled.md`). All relative due dates resolve against this (SPEC 6). |
| `date_source` | TEXT | `header` (parsed from the note), `filename` (header missing or unparseable, `YYYY-MM-DD` prefix used), or `none`. |
| `attendees` | TEXT (JSON array) | Full names as listed. `[]` means unknown (for example `2026-09-23-standup.md`), which makes same-first-name owners ambiguous (SPEC 5.3). |
| `content_hash` | TEXT | sha256 of the normalised file text (BOM stripped, CRLF to LF). An unchanged hash lets ingest report the file as `unchanged`. |
| `ingested_at` | TEXT | UTC timestamp of the last ingest. Informational only, never used in an ID or sort. |

Skipped files (empty, binary, not `.md`) get **no row**. They appear only in the ingest summary.

### 2.2 `mentions`

```sql
CREATE TABLE mentions (
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
CREATE INDEX mentions_item ON mentions(item_id);
```

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER, PK | Surrogate row key. Never exposed and never used in an item ID. |
| `item_id` | TEXT, FK | The item this line was merged into. Briefly NULL inside the ingest transaction, never NULL once committed. |
| `file` | TEXT, FK | The note it came from. |
| `line_no` | INTEGER | 1-based line number in the normalised file. Together with `file` it locates the line. |
| `syntax` | TEXT | `checkbox` (`- [ ]`, `* [x]`, `+ [X]`, nested), `action` (`ACTION:` prefix), `table` (Owner / Action / Due row). |
| `raw_line` | TEXT | The line as written, trimmed. Kept for debugging and to show the raw due phrase. |
| `owner_raw` | TEXT, null | Owner text as written (`Priya N.`, `@anita`, `Everyone`). Null if there was no `<Name> to` form. |
| `owner` | TEXT | Resolved owner: full name (`Priya Nair`), `Unassigned`, or `Ambiguous (Priya)` (SPEC 5.2, 5.3). |
| `owner_kind` | TEXT | `person`, `unassigned` or `ambiguous`. Used so `followup` skips the latter two. |
| `collaborators` | TEXT (JSON array) | Others on a joint line (`Anita & Rahul`, `Lena (with Priya)`). Each entry is a full name or an `Ambiguous (...)` string. |
| `task` | TEXT | Task text with the owner prefix and recognised due phrase removed. |
| `task_key` | TEXT | Normalised task for matching and hashing (section 4.1). |
| `due` | TEXT, null | Resolved deadline. Null if none, not a deadline, or unresolvable (SPEC 6). |
| `due_raw` | TEXT, null | The due phrase as written (`by Friday`, `before cutover`, `from 9 Oct`). Kept even when `due` is null. |
| `checked` | INTEGER | 1 for `[x]` or `[X]`, else 0. `ACTION:` lines and table rows are 0. |

The UNIQUE constraint is safe because a file's mentions are deleted and re-inserted in one transaction when the file is re-read (section 5).

### 2.3 `items`

```sql
CREATE TABLE items (
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
CREATE INDEX items_owner ON items(owner);
```

| Column | Type | Meaning |
|---|---|---|
| `id` | TEXT, PK | 8 hex chars, `sha1(id_key)[:8]` (section 3). This is what `done <id>` takes. |
| `id_key` | TEXT | The string that was hashed: `owner + "\|" + task_key` of the earliest mention. Stored so a re-ingest can verify the ID. |
| `owner` | TEXT | Full name, `Unassigned` or `Ambiguous (Priya)`. Same value for all mentions of the item (the match rule requires it). |
| `owner_kind` | TEXT | As on mentions. |
| `collaborators` | TEXT (JSON) | From the latest mention that has any. |
| `task` | TEXT | Wording of the **latest** mention (SPEC 5.1). |
| `due` | TEXT, null | **Latest non-empty** due across mentions. Null if none ever had one. |
| `due_raw` | TEXT, null | Raw due phrase of the mention that supplied `due`, else of the latest mention that has one. |
| `status` | TEXT | Stored status is only `open` or `done`. **Overdue is never stored.** It is computed on read as `status='open' AND due < today` (SPEC 7.1). |
| `done_manual` | INTEGER | 1 if closed by `actiontrack done`. Sticky: re-ingest never reopens such an item (D16). |
| `first_file` | TEXT | Source file of the earliest mention. |
| `latest_file` | TEXT | Source file of the latest mention. `list` shows it as `<file> (+N)`. |
| `mention_count` | INTEGER | Number of mentions, so `N = mention_count - 1`. |

`status` is derived as: `done` if `done_manual = 1`, else `done` if the **latest** mention is `checked`, else `open`.

"Earliest" and "latest" order mentions by `(meeting_date, file, line_no)`, with undated notes sorting first.

## 3. ID scheme

```
canonical_owner = items.owner            # "Priya Nair" | "Unassigned" | "Ambiguous (Priya)"
canonical_task  = task_key of the EARLIEST mention in the group
id_key          = canonical_owner + "|" + canonical_task
id              = sha1(id_key.encode("utf-8")).hexdigest()[:8]
```

### 3.1 Why it is stable on re-ingest

- **Pure content.** The ID depends only on the owner and the normalised words of one mention. It never uses a row number, rowid, insert time or file mtime (CLAUDE.md hard rule).
- **Deterministic anchor.** The group is anchored on the earliest mention by `(meeting_date, file, line_no)`. Those are properties of the notes, not of the order they were read or inserted. Reading the files in any order gives the same anchor.
- **Insensitive to drift.** Later wording changes, due-date changes and `[x]` toggles alter `task`, `due` and `status` but never the anchor mention, so the ID is unchanged. Example: "Share wireframes" becoming "Share updated wireframes" keeps its ID.
- **Idempotent writes.** `items` is upserted by `id`. Re-ingesting the same folder recomputes identical IDs, so the row count and every ID are unchanged. Nothing is duplicated.
- **Collisions.** If two different `id_key` values hash to the same 8 characters, the later key is re-hashed as `id_key + "#2"` (then `#3`, and so on). That is deterministic too, because groups are processed in the earliest-mention order.

### 3.2 Known limit (D9)

IDs are stable for re-ingest of the same folder. If an earlier-dated note for an existing task is added later, the anchor moves and the ID changes. Likewise, if an owner's resolution changes (for example the attendee list is edited), the `owner` part of the key changes.

## 4. Duplicate-matching rule

The rule is from SPEC 5.1, restated precisely.

### 4.1 `task_key` normalisation

1. Take the `task` text (owner prefix and due phrase already removed).
2. Lowercase, and replace every non-alphanumeric character with a space.
3. Split into tokens and drop stop-words: `a an the to for of with and on in by at our up`.
4. Join the remaining tokens with single spaces, in original order.

There is no stemming. Example: `send the revised quote to Acme` becomes `send revised quote acme`.

### 4.2 Match test

Mention `m` joins an existing group `g` when both hold:

1. **Same owner key.** `m.owner == g.owner`. That means the same resolved full name, both `Unassigned`, or both `Ambiguous (X)` with the same first name. An ambiguous item **never** merges into a resolved one, and `Priya Nair` never merges with `Priya Shah`.
2. **Similar task.** `jaccard(tokens(m.task_key), tokens(x.task_key)) >= 0.6` for some member `x` of `g`, where `jaccard(A,B) = |A ∩ B| / |A ∪ B|` over token sets.

### 4.3 Procedure (deterministic)

1. Sort all mentions by `(meeting_date, file, line_no)`, undated first.
2. For each mention in that order, find groups passing 4.2. Pick the one with the **highest** score (ties go to the group created first). If none passes, start a new group.
3. Compute each group's `id`, `task`, `due`, `status`, and so on as in 2.3.

Examples: `{share, wireframes}` vs `{share, updated, wireframes}` = 2/3 = 0.67, so they merge. `{send, revised, quote, acme}` vs `{send, revised, quote, acme}` = 1.0, so they merge. `{export, last, quarter, invoices}` vs `{review, schema, mapping, doc}` = 0, so they stay apart.

## 5. Ingest write procedure

Per `actiontrack ingest`, in one SQLite transaction:

1. Pass 1: read all files and build the roster (every attendee full name).
2. Per file: skip or parse (SPEC 5.5). If the file's `content_hash` equals the stored one, keep its rows and mark it `unchanged`.
3. For each parsed or changed file: upsert its `meetings` row, `DELETE FROM mentions WHERE file = ?`, and insert the new mentions with `item_id` NULL.
4. Regroup **all** mentions in the table (including ones from files no longer in the folder, which are kept per D10) using section 4.3.
5. Upsert `items`. Carry over `done_manual` from the existing row with the same `id`. Delete item rows that no longer have any mention.
6. Update `mentions.item_id` to the final IDs, then commit.

A failure in step 2 for one file only skips that file. A failure in the transaction itself rolls everything back and exits 1.

## 6. Example rows

Based on the real fixtures. Today for the overdue column is `2026-10-22`. Item IDs are computed with the scheme above.

### 6.1 `meetings`

| file | title | meeting_date | date_source | attendees | content_hash | ingested_at |
|---|---|---|---|---|---|---|
| 2026-09-01-quote-portal-kickoff.md | Quote portal kickoff | 2026-09-01 | header | `["Priya Nair","Rahul Mehta","Anita Desai","Sam Okafor"]` | `9e1f...` | 2026-10-22T09:00:00Z |
| 2026-09-15-quote-portal-weekly.md | Quote portal weekly | 2026-09-15 | header | `["Priya Nair","Rahul Mehta","Anita Desai","Sam Okafor","Meera Iyer"]` | `4b7c...` | 2026-10-22T09:00:00Z |
| 2026-10-03-sales-pipeline.md | Sales pipeline | 2026-10-03 | filename | `[...]` | `c0a2...` | 2026-10-22T09:00:00Z |
| untitled.md | NULL | NULL | none | `[]` | `77d3...` | 2026-10-22T09:00:00Z |

The titles are illustrative. Dates and attendees come from the files.

### 6.2 `mentions` and the merged `items` row: Sam, "confirm cloud budget with finance"

Three notes carry this task. Only 09-15 has a due phrase, and "by Friday" from Tuesday 2026-09-15 resolves to 2026-09-18.

`mentions` (columns abbreviated):

| id | item_id | file | line_no | syntax | owner_raw | owner | owner_kind | task | task_key | due | due_raw | checked |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | b48cced6 | 2026-09-01-quote-portal-kickoff.md | 12 | checkbox | Sam | Sam Okafor | person | confirm cloud budget with finance | confirm cloud budget finance | NULL | NULL | 0 |
| 2 | b48cced6 | 2026-09-15-quote-portal-weekly.md | 11 | checkbox | Sam | Sam Okafor | person | confirm cloud budget with finance | confirm cloud budget finance | 2026-09-18 | by Friday | 0 |
| 3 | b48cced6 | 2026-09-22-quote-portal-weekly.md | 10 | checkbox | Sam | Sam Okafor | person | confirm cloud budget with finance | confirm cloud budget finance | NULL | NULL | 1 |

`items`:

| id | id_key | owner | owner_kind | task | due | due_raw | status | done_manual | first_file | latest_file | mention_count |
|---|---|---|---|---|---|---|---|---|---|---|---|
| b48cced6 | Sam Okafor\|confirm cloud budget finance | Sam Okafor | person | confirm cloud budget with finance | 2026-09-18 | by Friday | done | 0 | 2026-09-01-quote-portal-kickoff.md | 2026-09-22-quote-portal-weekly.md | 3 |

The item is `done` because the latest mention (09-22) is `[x]`. It keeps the latest non-empty due (2026-09-18). Because it is done it is never overdue, even though 2026-09-18 is before today.

### 6.3 Priya Nair, "send revised quote to Acme": merging across explicit and implicit owners

| id | item_id | file | line_no | owner_raw | owner | task_key | due | due_raw | checked |
|---|---|---|---|---|---|---|---|---|---|
| 4 | cfc90787 | 2026-09-01-quote-portal-kickoff.md | 9 | Priya | Priya Nair | send revised quote acme | 2026-09-04 | by Friday | 0 |
| 5 | cfc90787 | 2026-09-08-quote-portal-weekly.md | 9 | Priya N. | Priya Nair | send revised quote acme | 2026-09-11 | by Friday | 0 |
| 6 | cfc90787 | 2026-09-15-quote-portal-weekly.md | 9 | Priya | Priya Nair | send revised quote acme | NULL | NULL | 1 |

On 09-01 and 09-15 only Priya Nair attended among the Priyas, so a bare `Priya` resolves to her. 09-08 resolves from the explicit initial `N.`. All three have owner `Priya Nair` and identical `task_key`, so they merge into item `cfc90787` with status `done`, due `2026-09-11`, `mention_count` 3.

### 6.4 Ambiguous, unassigned and non-deadline rows

| item id | owner | owner_kind | task | due | due_raw | status | Why |
|---|---|---|---|---|---|---|---|
| (hash) | Ambiguous (Priya) | ambiguous | own the hiring plan for the two QA roles | NULL | NULL | open | 2026-09-30 offsite, all nine attended, no initial. Never merged into a Priya Nair or Priya Shah item. Never in a follow-up email. |
| (hash) | Unassigned | unassigned | write the design-system changelog | NULL | NULL | open | `TBD to write ...` on 2026-09-18. `owner_raw` is `TBD` on the mention. |
| (hash) | Karan Joshi | person | freeze invoice edits from 9 Oct | NULL | from 9 Oct | open | Start date, not a deadline: `due` is NULL, the phrase is kept in `due_raw`. Two mentions (09-29, 10-08) merge into one item. |

The `(hash)` placeholders stand for IDs computed at ingest time. Prose-only commitments (for example `Priya offered to help recruit`) never produce rows.

## 7. Queries the commands rely on

```sql
-- list --status overdue --today :today
SELECT * FROM items
WHERE status = 'open' AND due IS NOT NULL AND due < :today
ORDER BY due IS NULL, due, latest_file, id;

-- list --status open
SELECT * FROM items
WHERE status = 'open' AND (due IS NULL OR due >= :today);

-- list --due-before :d
SELECT * FROM items WHERE due IS NOT NULL AND due < :d;

-- done <id>
UPDATE items SET status = 'done', done_manual = 1 WHERE id = :id;

-- followup "<Full Name>"
SELECT * FROM items
WHERE owner = :name AND owner_kind = 'person' AND status = 'open';
-- then split in code into overdue (due < today) and open
```

ISO date strings compare correctly as text, so no date functions are needed.
