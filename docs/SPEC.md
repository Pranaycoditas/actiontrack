# actiontrack: Specification

Status: draft v1.

**Sources and caveats.** This spec is derived from `docs/SCENARIO.md`, `docs/data-findings.md` (especially its section 7, "Working decisions") and the files in `notes/`.

- `docs/SCENARIO.md` is **truncated**: lines 14, 17, 19, 22 and 24 are cut off mid-sentence.
- `docs/DECISIONS.md` **does not exist**. Its role is filled by section 7 of `docs/data-findings.md`.
- Gaps were filled with the simplest sensible choice. Each is marked **(decision Dn)** and collected in section 9. Reverse any of them if the full scenario says otherwise.

Where this spec and `CLAUDE.md` disagree, `CLAUDE.md` wins. Its hard rules are repeated in section 1.

---

## 1. Goals and non-goals

### Goals

1. Ingest a folder of messy markdown meeting notes and store every real action item (owner, task, due date, source file(s), status) in SQLite.
2. Resolve due dates to real calendar dates, relative to the **meeting date**.
3. Collapse the same task repeated across meetings into one item with a stable ID.
4. Never guess a person: same-first-name owners are resolved from evidence or marked ambiguous.
5. Let the user list, filter, and close items.
6. Draft (never send) one follow-up email per owner in Gmail, covering their open and overdue items.

### Hard rules (from CLAUDE.md, binding on the implementation)

- **Drafts only, never send.** No code path sends email. `followup` only creates drafts via the Gmail MCP connector (or writes files with `--out`). The exact flow is in `docs/GMAIL_FLOW.md`.
- A malformed note never crashes `ingest`. It is skipped and listed with a reason in the summary.
- Relative due dates resolve against the meeting date. Only the overdue check uses today's date.
- Item IDs are derived from content and are stable across re-ingest (no duplicates, no changes).
- Same-first-name owners (Priya Nair/Shah, Rahul Mehta/Verma) are never guessed.

### Non-goals

- Sending email, scheduling sends, reading replies, or looking up email addresses.
- Extracting commitments from prose (for example `Priya offered to help recruit`). Only structured action lines count.
- Flagging "stale" items that were carried across many meetings without closing.
- Editing or writing back to the note files.
- Reopening a done item (there is no `undone` command).
- Recursive folder scanning (decision D11).
- Multi-user access, a web UI, or a sync service.

---

## 2. Global behavior

- **Storage:** one SQLite file via stdlib `sqlite3`. Default path `./actiontrack.db`, overridable with `--db PATH` or the env var `ACTIONTRACK_DB` (decision D3).
- **Date format:** all dates in input flags and output are ISO `YYYY-MM-DD`.
- **`--today YYYY-MM-DD`:** accepted by `list` and `followup`. It overrides the system date for the overdue check and nothing else.
- **Exit codes (all commands):**

| Code | Meaning |
|---|---|
| 0 | Success, including "nothing to do" and ingest runs that skipped files |
| 1 | Runtime failure: database error, Gmail connector unavailable or unauthorized, output file not writable |
| 2 | Usage error: bad or missing argument, unknown ID, unknown owner, invalid date or status |

- Warnings go to stderr. Tables and summaries go to stdout.

---

## 3. Commands

### 3.1 `actiontrack ingest <folder>`

| | |
|---|---|
| Argument | `folder`: directory containing notes. Must exist (else exit 2). Not scanned recursively. |
| Flags | `--db PATH` |
| Exit codes | 0 on completion (even if files were skipped), 1 on database failure, 2 if `folder` is missing or not a directory |

**Behavior**

1. Two passes. Pass 1 reads every file and builds the **roster**: every full name seen in any `Attendees` list. Pass 2 parses items.
2. Each file is processed inside a try/except. Any failure becomes a skip with a reason. It never aborts the run (section 5.5).
3. Items from all files are grouped into duplicates (section 5.1), assigned IDs, and upserted.
4. Ingest is **additive and idempotent**. Running it twice on the same folder changes nothing: same IDs, same row count.
5. A manual `done` is sticky. Re-ingest never reopens an item (decision D16).
6. Items whose source files disappear from the folder are kept (decision D10).

**What counts as an action item**

Included:
- Checkbox lines with `-`, `*` or `+` bullets, `[ ]`, `[x]` or `[X]`, at any indent, anywhere in the file (not only under `## Action items`).
- `ACTION:` lines.
- Rows of a markdown table whose header has Owner / Action / Due columns.

Excluded:
- Block-quoted lines (`> - [ ] ...`).
- Fenced code blocks.
- HTML comments, including multi-line ones.
- Prose commitments in Discussion text.
- Non-`.md` files.

**Example output** (counts and IDs are illustrative)

```
$ actiontrack ingest notes/
Scanned 37 files in notes/
  Ingested:  34 notes
  Skipped:    3 files
  Items:     96 found -> 71 unique (25 duplicates merged)
             new 71, updated 0, unchanged 0

Skipped files:
  2026-09-09-notes-final-v2.md   empty file (0 bytes)
  scratch.md                     not text (binary content)
  2026-09-19-offsite-draft.txt   not a .md file

Warnings:
  untitled.md                    no date, no attendees; 2 items ingested, relative due dates unresolved
  2026-10-03-sales-pipeline.md   date "sometime last week" unparseable; using filename date 2026-10-03
  2026-09-23-standup.md          no attendees; 1 owner left ambiguous (Rahul)
  2026-09-30-q4-offsite.md       3 owners ambiguous (Priya, Rahul)
  ...
```

On a second run the line reads `new 0, updated 0, unchanged 71`.

### 3.2 `actiontrack list`

| | |
|---|---|
| Arguments | none |
| Flags | `--owner TEXT`, `--status open\|done\|overdue`, `--due-before YYYY-MM-DD`, `--today YYYY-MM-DD`, `--db PATH` |
| Exit codes | 0 (including zero matches), 2 on invalid `--status`, `--due-before` or `--today` |

**Filter semantics** (all filters combine with AND)

- No `--status` shows all items, including done ones.
- `--status open`: not done, and not overdue (due date empty, today, or later).
- `--status overdue`: not done, with a due date strictly before today.
- `--status done`: marked done.
- `--due-before D`: due date strictly earlier than D. Items with no due date are excluded.
- `--owner`:
  - Matching is case-insensitive.
  - A full name (`"Priya Nair"`) matches that person only. If ambiguous `Priya` items exist, a warning says `N items owned by "Ambiguous (Priya)" not included`.
  - A bare first name matches every person with that first name, plus ambiguous items for it, and prints a warning if it is shared.
  - `--owner Unassigned` matches unowned items.

**Sort:** due date ascending (no-due last), then source date, then ID.

**Example output** (`--today 2026-10-22`)

```
$ actiontrack list --owner "Sam Okafor" --status overdue --today 2026-10-22
ID        STATUS   OWNER        DUE         TASK                                   SOURCE
3f9a1c7e  overdue  Sam Okafor   2026-10-09  cut cloud costs by 10% - proposal      2026-10-02-finance-sync.md
b04d52aa  overdue  Sam Okafor   2026-10-15  propose the on-call rotation           2026-09-30-q4-offsite.md
2 items
```

- Items merged from several notes show the latest source file plus `(+N)`, for example `2026-09-15-quote-portal-weekly.md (+2)`.
- Items with no owner show `Unassigned`, and ambiguous ones show `Ambiguous (Priya)`.
- An empty due prints `-`.
- Zero matches prints `No items found.` and exits 0.

### 3.3 `actiontrack done <id>`

| | |
|---|---|
| Argument | `id`: 8-hex-character item ID, case-insensitive |
| Flags | `--db PATH` |
| Exit codes | 0 on success or if the item is already done, 2 if no item has that ID |

```
$ actiontrack done 3f9a1c7e
Marked done: 3f9a1c7e  Sam Okafor  cut cloud costs by 10% - proposal
$ actiontrack done 3f9a1c7e
Already done: 3f9a1c7e
$ actiontrack done ffffffff
error: no item with id ffffffff
```

The command exits 2 for the last case. Unique-prefix matching is not supported (decision D15).

### 3.4 `actiontrack followup <owner>` or `actiontrack followup --all`

| | |
|---|---|
| Argument | `owner`: full name (`"Priya Nair"`). Required unless `--all` is given |
| Flags | `--today YYYY-MM-DD`, `--db PATH`, `--email-map FILE`, `--dry-run` (decision D12), `--out FOLDER` (decision D25), `--all` (decision D26) |
| Exit codes | 0 draft or file created, or nothing to follow up. 1 Gmail connector unavailable or unauthorized (no draft created), or the `--out` file cannot be written. 2 unknown owner, bare ambiguous first name, `Unassigned`, `--out` combined with `--dry-run`, `--out` naming an existing file, `--all` together with an owner, or neither an owner nor `--all` |

**Behavior**

- Creates exactly one Gmail **draft** for the owner, listing their overdue items and then their open items (section 7). It never sends and never calls a send API.
- An owner with no open or overdue items gets no draft: `No open or overdue items for Priya Nair.`, exit 0.
- A bare first name shared by two people (`Priya`, `Rahul`) exits 2 with `ambiguous owner "Priya": use "Priya Nair" or "Priya Shah"`. No drafts are created.
- Items owned by `Ambiguous (Priya)` are in no draft. After a successful draft, a warning says `N items for "Priya" are ambiguous and not included`.
- The notes contain no email addresses, so `To` is blank unless `--email-map` supplies one (decision D27):
  - **Format:** a CSV file with a header row `owner,email`, UTF-8 (a BOM is fine), one person per row. `name` is accepted in place of `owner`. Example:
    ```
    owner,email
    Anita Desai,anita@example.com
    Priya Nair,priya.nair@example.com
    ```
  - **Key:** the full name as stored, matched case-insensitively and ignoring extra spaces. First names alone never match, so `Priya Nair` and `Priya Shah` need separate rows.
  - **Missing address is never an error.** An owner with no row, or a row with a blank email, gets a blank `To`. The draft or file is still created and the run continues. Unused rows, duplicate rows (the last wins) and blank lines are ignored. Addresses are not validated.
  - **Bad file is an error:** a map that cannot be read, or whose header has neither `owner`/`name` nor `email`, exits 2 before anything is created.
  - **Reporting:** `--all` lists every owner with no address in its summary (see below). A single-owner run shows `(To: <blank>)` on its result line.
- `--dry-run` prints the full email to stdout and creates no draft.
- Running `followup` twice creates two drafts (decision D14).

**`--out FOLDER`** (decision D25)

- Writes the email to a text file in `FOLDER` instead of creating a Gmail draft. The Gmail connector is not contacted, so no authorization is needed.
- `FOLDER` is created, with parents, if it does not exist. If the path exists and is not a directory, exit 2 before anything is written.
- One file per owner, named `<slug>.txt`. The slug is the full name lowercased, with each run of characters outside `a-z0-9` replaced by `-` (`Priya Nair` -> `priya-nair.txt`). Same-first-name owners therefore never share a file.
- The file holds the email in the section 7.2 layout, UTF-8, LF line endings, ending with a newline:
  - the `To:` line (blank unless `--email-map` supplies an address),
  - the `Subject:` line,
  - a blank line,
  - the body.
  It is the same text `--dry-run` prints.
- `followup` still takes one owner per call (decision D21). Run it once per owner to fill the folder.
- Re-running for the same owner overwrites that owner's file. Unlike drafts (D14), it does not accumulate copies. Files for other owners are never touched.
- An owner with no open or overdue items gets no file and `No open or overdue items for ...`, exit 0. An existing file for that owner is left as it was.
- `--out` and `--dry-run` are mutually exclusive: exit 2, nothing written.
- The ambiguous-items warning applies as for drafts.
- Nothing is sent. The command prints the path and says that no Gmail draft was created.

**`--all`** (decision D26)

- Runs the follow-up for every owner who has at least one open or overdue item, in name order. Each owner gets exactly what a single-owner run would give: one Gmail draft, or one file with `--out`, or a printed email with `--dry-run`.
- `--all` takes no owner. `followup --all "Priya Nair"` exits 2, as does `followup` with neither, and nothing is created.
- **Skipped owners.** `Ambiguous (Priya)` and `Unassigned` items are never followed up (sections 5.2, 5.3). They are skipped and listed in the summary with their open-item counts. Skipping them is not an error.
- **Summary** (stdout), after the per-owner result lines:
  - the number of drafts or files created, and the folder with `--out`;
  - `No email address for N owners:` and the names, when any owner has none (decision D27);
  - `Skipped (no resolved owner):` and each skipped owner with its item count.
- Owners with nothing outstanding are not mentioned. If no owner has anything outstanding, the output is `No open or overdue items for any owner.` and the exit code is 0.
- The per-owner warning about ambiguous items is replaced by the skipped list.
- **Failure.** Owners are processed one at a time and each result line is printed as it completes. A connector failure (exit 1) stops the run at once, with no retry, so no duplicate draft is risked. Owners already done keep their draft or file, and the error names the owner that failed.
- The one-owner-per-call rule of D21 no longer applies: `--all` is the many-owner form.

**Example output**

```
$ actiontrack followup "Anita Desai" --today 2026-10-22
Draft created for Anita Desai (To: <blank>): 2 overdue, 2 open
Draft id: r-8812345 (review it in Gmail Drafts; nothing was sent)

$ actiontrack followup --all --out drafts/ --email-map people.csv --today 2026-10-22
Wrote follow-up for Anita Desai (To: anita@example.com): 2 overdue, 2 open
File: drafts/anita-desai.txt (no Gmail draft was created; nothing was sent)
Wrote follow-up for Priya Nair (To: <blank>): 1 open
File: drafts/priya-nair.txt (no Gmail draft was created; nothing was sent)

2 files written to drafts/
No email address for 1 owner: Priya Nair
Skipped (no resolved owner):
  Ambiguous (Priya)  1 item
  Unassigned         1 item

$ actiontrack followup "Anita Desai" --today 2026-10-22 --out drafts/
Wrote follow-up for Anita Desai (To: <blank>): 2 overdue, 2 open
File: drafts/anita-desai.txt (no Gmail draft was created; nothing was sent)
```

---

## 4. Note parsing

### 4.1 Meeting date and attendees

| Source | Handling |
|---|---|
| `Date: 2026-09-01` | ISO |
| `Date: 9 September 2026` | Day Month Year |
| `Date: Monday, 14 September 2026` | Weekday, Day Month Year (the weekday is ignored) |
| YAML front matter `date: 2026-09-16` | Same parsers, lowercase key |
| `Date: sometime last week` or no header date | Use the `YYYY-MM-DD` prefix of the filename and warn. If there is no filename date either, the note is undated (section 5.4) |
| Header date and filename date disagree | Header wins, and a warning is printed (decision D19) |

Attendees come from `Attendees: A, B, C` or YAML `attendees: [A, B, C]`, and are always full names. A missing attendee list means attendees are unknown. Files are decoded as UTF-8, a BOM is stripped, and CRLF is normalised to LF.

### 4.2 Owner and task extraction

| Raw text | Owner (primary) | Collaborators | Notes |
|---|---|---|---|
| `Priya to send ...` | first name, resolved per 5.3 | none | |
| `Priya S. to run ...` | initial resolves it (Priya Shah) | none | |
| `@anita: audit ...` | Anita | none | handle stripped, colon form |
| `Anita & Rahul to agree ...` | Anita | Rahul (resolved or ambiguous) | primary is the first name listed |
| `Lena (with Priya) to collect ...` | Lena | Priya (resolved or ambiguous) | |
| `Everyone`, `Team`, `Everybody`, `TBD`, `Someone` | `Unassigned` | none | original word kept in a note field |
| Table row `\| Anita \| Refresh the brand kit \| 2026-10-09 \|` | Anita | none | columns Owner / Action / Due |
| `ACTION: Karan to circulate ...` | Karan | none | open |
| No `<Name> to` form (`Book the venue`) | `Unassigned` | none | whole text is the task |
| `Rahul to review Anita's PR` | Rahul | none | Anita is not the owner |

The task text is the action line with the owner prefix and the recognised due phrase removed. The original line is kept so a due phrase can be shown in raw form.

**Status:** `[x]` and `[X]` mean done. Everything else (`[ ]`, `ACTION:`, table rows) means open.

---

## 5. Edge cases and chosen behavior

### 5.1 Duplicates

The same task often reappears across meetings with changed wording, due date or checkbox state.

- **Match rule.** Two items are the same task if their owners match and their normalised task text is similar. "Owners match" means identical resolved owner, or both `Unassigned`, or both ambiguous with the same first name. Normalisation lowercases, strips punctuation, bullet markers, due phrases and stop-words, and compares content-word tokens. Similarity is token Jaccard >= 0.6 (decision D8), computed on a **match key** derived from the normalised text (decision D24):
  - Drift words are dropped: `first`, `initial`, `updated`, `new`, `latest`, `start`, `begin`.
  - `spike` is folded to `estimate`.
  - If dropping would empty the key, the unfiltered tokens are used.
  - The match key is for grouping only. IDs still hash the plain normalised text of the earliest mention.
  - Different steps on the same subject (`chase Orbit Labs` vs `send the proposal to Orbit Labs`, `pull` vs `share` the usage report, `collect` vs `publish` customer quotes, `draft the test plan` vs `run the tests`, `ask for` vs `send` the procurement form) are different tasks and stay separate. The owner rule is unchanged, so the same task for different owners is never merged.
- **No guessing.** An ambiguous item never merges with a resolved one, for example `Priya` (ambiguous) never merges into Priya Nair's item.
- **Merge result.** One item with:
  - the **status** of the latest meeting in the group (a later `[x]` closes earlier open ones);
  - the **latest non-empty due date**;
  - the **task wording** of the latest meeting;
  - **every source file** recorded.
- **Ordering.** "Latest" is by meeting date, then filename. Undated notes sort first.
- **ID.** `id = first 8 hex chars of sha1(canonical_owner + "|" + canonical_task)`. These come from the **earliest** member of the group, not the latest, so later wording drift never changes the ID. IDs depend only on content, never on row order or insert time (decision D9).
- **Examples from the data:**
  - *Confirm cloud budget with finance (Sam):* 09-01, 09-15 (by Friday), 09-22 `[x]` become one done item with due 2026-09-18 (Friday after the 09-15 meeting).
  - *Freeze invoice edits from 9 Oct (Karan):* identical in 09-29 and 10-08 and open in both, so one open item. "From 9 Oct" is not a deadline, so there is no due date.
  - *Share wireframes (Anita):* "share first wireframes" (09-01) and "share updated wireframes" (09-15, 09-22) are one open item with three sources. The ID comes from the 09-01 wording, and the task text and due date from 09-22.
  - *SSO estimate / spike (Rahul Verma):* "estimate SSO work" (09-14, 09-24) and "start SSO spike" (10-05) are one open item due 2026-10-13.
  - *Refund affected customers (Karan), 09-21:* the quoted line is excluded and only the real line counts.

### 5.2 No owner

Group or unassigned wording, or no `<Name> to` form, gives owner `Unassigned` (section 4.2).

- The item is stored, listed, and counted.
- It is never included in a follow-up draft, because there is no owner to email.
- It is not fanned out to attendees.

### 5.3 Same first name (Priya Nair/Shah, Rahul Mehta/Verma)

For a first name that maps to more than one person in the roster, apply in order:

1. **Explicit initial** (`Priya S.`, `Priya N.`). It resolves if it matches exactly one candidate's surname initial. If the initial contradicts the attendee list, the initial wins and a warning is printed.
2. **Attendees.** If exactly one candidate attended that meeting, it resolves to them.
3. Otherwise the owner is stored as **`Ambiguous (Priya)`** and a warning is printed. There is no project-cluster inference.

First names that map to one roster person (Anita, Sam, Meera, Karan, Lena) resolve to that person's full name, even if attendance is missing.

| Case | Result |
|---|---|
| 09-29 `Priya S.` and `Priya N.` | Priya Shah, Priya Nair |
| 09-03 billing sync, only one Priya present | that Priya |
| 09-17 `Priya to sign off ...`, both Priyas present | `Ambiguous (Priya)` |
| 09-17 `Rahul ...`, both Rahuls present | `Ambiguous (Rahul)` (decision D23) |
| 09-23 `Rahul to rebase ...`, no attendees listed | `Ambiguous (Rahul)` |
| 09-30 offsite, all 9 present | `Ambiguous (Priya)`, `Ambiguous (Rahul)` |
| 10-07 `Rahul to review Anita's PR` | `Ambiguous (Rahul)` |

### 5.4 No date

- **Item with no due date:** stored with an empty due. It is never overdue. It appears in `list` and in follow-up emails ("no due date").
- **Due phrase that is not a deadline** (`before cutover`, `from 9 Oct`): due is empty. The raw phrase is kept in a note field.
- **Note with no meeting date** (`untitled.md`): the note is ingested with a warning, and its items get no meeting date.
  - Absolute due dates still parse (`by 2026-10-09`).
  - Relative ones (`by Friday`) stay unresolved with an empty due. Nothing is guessed from today's date (decision D18).

### 5.5 Malformed notes

Skip rules produce a line in the ingest summary's "Skipped files" with the reason. Each skipped file is listed individually.

| Condition | Result | Reason text |
|---|---|---|
| 0 bytes (`2026-09-09-notes-final-v2.md`) | skipped | `empty file (0 bytes)` |
| Binary or invalid UTF-8 (`scratch.md`) | skipped | `not text (binary content)` |
| Not `.md` (`2026-09-19-offsite-draft.txt`) | skipped | `not a .md file` |
| Any exception while parsing a file | skipped | `parse error: <message>` |
| No date or attendees (`untitled.md`) | **ingested** with warning | see 5.4 |
| Unparseable header date (`2026-10-03-sales-pipeline.md`) | **ingested**, filename date | warning |
| No attendees (`2026-09-23-standup.md`) | **ingested** | warning, same-name owners ambiguous |
| CRLF, `[X]`, `*` and `+` bullets (`2026-10-02-finance-sync.md`) | **ingested** | normalised |

A skipped file contributes no items and does not affect the exit code.

---

## 6. Date resolution

### 6.1 Rules

All resolution uses the **meeting date** `M`. The year is `M`'s year unless stated. Today's date is never used here.

1. **Deadline phrase.** Only dates introduced by `by`, `due`, or `before <date>` count as deadlines. A trailing bare `tomorrow`, `today` or `EOD` is also a deadline (`ACTION: ... summary tomorrow`). Dates introduced by `from`, `for`, or `on` are **not** deadlines. If a line has several deadline phrases, the last one wins.
2. **ISO** (`2026-10-09`): taken as written.
3. **Bare weekday** (`Friday`, `Mon`, `Wed`): the first such weekday **strictly after** `M`. If `M` is itself that weekday, add 7 days.
4. **`next <weekday>`**: that weekday in the **following Monday-to-Sunday calendar week** (decision D5).
5. **`tomorrow`:** `M` + 1 day. **`EOD`/`today`:** `M`. **`EOD tomorrow`:** `M` + 1 day.
6. **`end of next week`:** the Friday of the following calendar week (decision D6).
7. **`end of month`:** last day of `M`'s month.
8. **`mid-<Month>`:** the 15th of that month. If the month name is earlier than `M`'s month, the year is `M`'s year + 1.
9. **Day-month without year** (`10 Sep`, `Oct 3rd`, `7 Oct`, `15 October`): `M`'s year. If that date is before `M`, use the next year (decision D7). Ordinals (`3rd`) are accepted.
10. **Weekday plus date** (`Wed 16 Sep`): the date wins. If the weekday does not match, the date is still used and a warning is printed (decision D22).
11. **Weekend results** are accepted as written (`Oct 3rd` is a Saturday).
12. **Event-relative** (`before cutover`) and anything unparseable: empty due. The raw phrase is kept.
13. Dates in the Discussion prose (`after the weekend`) are ignored. Only the action line is parsed.

### 6.2 Examples

| Phrase | Meeting date (weekday) | Resolved due |
|---|---|---|
| `by Friday` | 2026-09-01 (Tue) | 2026-09-04 |
| `by Friday` | 2026-09-18 (Fri) | 2026-09-25 (same weekday, +7) |
| `by Monday` | 2026-09-03 (Thu) | 2026-09-07 |
| `by Mon` | 2026-09-18 (Fri) | 2026-09-21 |
| `by Wednesday` | 2026-09-18 (Fri) | 2026-09-23 |
| `by tomorrow` | 2026-10-06 (Tue) | 2026-10-07 |
| `by EOD` | 2026-10-08 (Thu) | 2026-10-08 |
| `by EOD tomorrow` | 2026-10-07 (Wed) | 2026-10-08 |
| `by next Tuesday` | 2026-10-05 (Mon) | 2026-10-13 |
| `by next Tuesday` | 2026-09-18 (Fri) | 2026-09-22 |
| `by end of next week` | 2026-09-03 (Thu) | 2026-09-11 |
| `by end of month` | 2026-09-14 (Mon) | 2026-09-30 |
| `by mid-October` | 2026-09-30 (Wed) | 2026-10-15 |
| `by 2026-10-09` | any | 2026-10-09 |
| `by 10 Sep` | 2026-09-03 (Thu) | 2026-09-10 |
| `by Wed 16 Sep` | 2026-09-14 (Mon) | 2026-09-16 |
| `by Oct 3rd` | 2026-09-30 (Wed) | 2026-10-03 (Saturday, accepted) |
| `results due 15 October` | 2026-09-30 (Wed) | 2026-10-15 |
| `by 7 Jan` | 2026-12-20 (Sun) | 2027-01-07 (year rolls over) |
| `ACTION: ... offsite summary tomorrow` | 2026-09-30 (Wed) | 2026-10-01 |
| `before cutover` | 2026-09-03 | empty (raw phrase kept) |
| `freeze invoice edits from 9 Oct` | 2026-09-29 | empty (start date, not a deadline) |
| `demo the portal to Acme on 2026-10-14` | any | empty (event date, not a deadline) |
| `by Friday` | undated note | empty (cannot resolve) |

---

## 7. Overdue definition and email format

### 7.1 Overdue

An item is **overdue** when all of these hold:

1. its status is not done;
2. its due date is not empty;
3. its due date is **strictly before** today (`due < today`).

- An item due today is open, not overdue.
- Items with no due date are never overdue.
- Today is the system date, or the `--today` value if given.
- Overdue is computed when the command runs and is **never stored**. Stored status is only `open` or `done`.
- In `list --status`, `open` and `overdue` are mutually exclusive (decision D4).

### 7.2 Follow-up email

Format is plain text, in a single Gmail draft per owner (or a single file per owner with `--out`, section 3.4). Drafts only, never send: the step-by-step flow is in `docs/GMAIL_FLOW.md`.

- **To:** blank, or the address from `--email-map`.
- **Subject:** `Action items follow-up: <Full Name> (<n> overdue, <m> open)`. A zero count is omitted, for example `(3 open)`.
- **Greeting:** first name only.
- **Sections:** `Overdue` (due date ascending), then `Open`. Open items are sorted by due date ascending, with no-due items last. An empty section is omitted.
- **Each item line:** `- <task> (due YYYY-MM-DD[, N days overdue] | no due date) [id] - from <source file>`. Collaborators are shown as `(with Rahul)`. A merged item shows its latest source file.
- **Not included:** done items and ambiguous or unassigned items.
- **Sign-off:** `Thanks,` with no name (decision D13).

```
To:
Subject: Action items follow-up: Anita Desai (2 overdue, 2 open)

Hi Anita,

Here are your outstanding action items as of 2026-10-22.

Overdue
- Share wireframes (due 2026-09-24, 28 days overdue) [8c1e07b2] - from 2026-09-22-quote-portal-weekly.md
- Refresh the brand kit (due 2026-10-09, 13 days overdue) [d27a90f4] - from 2026-09-30-q4-offsite.md

Open
- Audit colour contrast on the dashboard (due 2026-10-23) [51be3a08] - from 2026-09-18-design-review.md
- Agree on the component API (with Rahul) (no due date) [e6f04c19] - from 2026-09-18-design-review.md

If any of these are done or need a new date, reply and I will update the tracker.

Thanks,
```

The email is illustrative of layout only. Example IDs and item statuses are made up.

---

## 8. Test fixtures

Tricky notes live in `notes/`. Tests are written before the code (CLAUDE.md). Each case in section 5 and each row in the table in 6.2 should have a test, using the file named in the row where one exists. Overdue tests pass `--today`.

---

## 9. Resolved decisions (formerly open questions)

| # | Question | Decision |
|---|---|---|
| D1 | `SCENARIO.md` is truncated mid-sentence on five lines. What do the cut sections say (notably the overdue definition and followup details)? | Followed `CLAUDE.md` and `data-findings.md` section 7 |
| D2 | `docs/DECISIONS.md` does not exist. Is there a decisions doc, or is `data-findings.md` section 7 the decision record? | Section 7 treated as decisions |
| D3 | Where does the SQLite DB live? | `./actiontrack.db`, `--db` flag and `ACTIONTRACK_DB` |
| D4 | Does `--status open` include overdue items? | No, they are mutually exclusive |
| D5 | Does `next Tuesday` mean the Tuesday of the following calendar week, or the next Tuesday to occur? | Following Monday-Sunday week |
| D6 | `end of next week`: Friday of next week (Sep 11 from Thu Sep 3), or the week after? | Friday of the following calendar week |
| D7 | Day-month with no year that falls before the meeting date: roll to next year? | Yes |
| D8 | Duplicate matching: is token Jaccard >= 0.6 on normalised text the right rule? Should it be tuned on the fixtures? | Jaccard >= 0.6 with the owner constraint |
| D9 | Item ID is from the earliest occurrence. If a new, earlier note is later added to the folder, the ID could change. Is that acceptable? | Accepted. Re-ingest of the same folder is stable |
| D10 | Should items whose source files vanish from the folder be kept? | Kept |
| D11 | Should `ingest` recurse into subfolders? | No |
| D12 | How does the CLI call the Gmail MCP connector? The `--email-map` and `--dry-run` flags are my additions. | Added both flags |
| D13 | Email sign-off name and sender identity? | `Thanks,` with no name |
| D14 | Should `followup` avoid creating a second draft if one already exists for the owner? | No dedupe |
| D15 | Should `done` accept a unique ID prefix? | Exact 8-character ID only |
| D16 | Should a later open appearance of a manually done item reopen it? | No, manual done is sticky |
| D17 | Are collaborators (`Lena (with Priya)`) included in the collaborator's own follow-up? | No, they only appear on the primary owner's line |
| D18 | For an undated note, should relative due dates fall back to the filename or to today? | Left empty. Neither is used |
| D19 | When the header date and filename date disagree, which wins? | Header, with a warning |
| D20 | Are `Everyone`/`Team` items fanned out to attendees? | No, they stay `Unassigned` |
| D21 | Should `followup` support all owners in one call (for example `--all`)? | Originally one owner per call. Superseded by D26 |
| D22 | Weekday and date that disagree (`Wed 16 Sep` when 16 Sep is not Wednesday): which wins? | The date, with a warning |
| D23 | `data-findings.md` says that on 09-17 "Rahul resolves to Verma", but both Rahuls attended. What evidence resolves it? | Ambiguous. Never guess, even if findings hint at Verma |
| D24 | Plain Jaccard 0.6 keeps reworded repeats apart (wireframes 0.5, SSO 0.2). Lowering the threshold would also merge distinct steps (Orbit chase/proposal 0.4). | Match on a key that drops drift words and folds `spike` to `estimate`, keeping 0.6 and the owner rule. Distinct steps stay separate. Merging a previously split pair moves its ID to the earliest mention's, as in D9 |
| D25 | Can `followup` write the email to disk instead of Gmail? How are files named, and is it one owner per call? | Added `--out FOLDER`: one `<slug>.txt` per owner holding To, Subject and body in the `--dry-run` layout. Still one owner per call (D21). Re-runs overwrite that owner's file. Mutually exclusive with `--dry-run` |
| D26 | How does `followup` cover every owner at once, and what happens to owners it cannot email? | `--all` works with the Gmail, `--out` and `--dry-run` sinks. Ambiguous and unassigned owners are skipped and listed. `--all` with an owner, or neither, exits 2. A connector failure stops the run and is not retried |
| D27 | What is the `--email-map` format, and what if an address is missing? | CSV `owner,email` (`name` accepted for `owner`). A missing or blank address gives a blank `To` and never fails the run. `--all` lists owners without one. An unreadable or wrongly headed file exits 2 |
