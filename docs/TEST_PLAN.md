# actiontrack: Test plan

Companion to [SPEC.md](SPEC.md), [DATA_MODEL.md](DATA_MODEL.md) and [ARCHITECTURE.md](ARCHITECTURE.md). Facts about the sample notes come from [data-findings.md](data-findings.md). Tests are written before the code (CLAUDE.md).

## 1. Conventions

**Source column**

| Value | Meaning |
|---|---|
| **real** | A file that already exists in `notes/` (named in the case). The test copies it into a temp folder or reads it directly. It is never edited. |
| **fixture** | A small synthetic input made for the test, either an inline string or a file under `tests/fixtures/`. Used where the real notes do not isolate a rule, or where a failure has to be forced. |
| **both** | The case runs on a real file and on a fixture variant. |

**Defaults.** All CLI and overdue tests pass `--today 2026-10-22` unless a case says otherwise. Dates are ISO. "Skip" means a `Skip(file, reason)` value and a line in the ingest summary. Case IDs are stable so failures can be quoted.

**Running.** `pytest` runs everything. One case: `pytest tests/test_x.py::test_name`. Module prefixes map to files:

| Prefix | Module | Test file |
|---|---|---|
| P | parser (and reader) | `test_parser.py`, `test_reader.py` |
| D | dates | `test_dates.py` |
| O | owners | `test_owners.py` |
| DD | dedupe | `test_dedupe.py` |
| S | store | `test_store.py` |
| I | ingest | `test_ingest.py` |
| L | list | `test_cli.py` |
| DN | done | `test_cli.py` |
| F | followup | `test_followup.py`, `test_cli.py` |
| N | nothing is ever sent | `test_no_send.py` |
| E | end-to-end | `test_notes_fixtures.py` |

---

## 2. Parser and reader

### 2.1 Action-line syntaxes (SPEC 3.1)

| ID | Input | Expected result | Source |
|---|---|---|---|
| P01 | `- [ ] Priya to send the revised quote to Acme by Friday` | 1 line, `syntax=checkbox`, `checked=false`, owner text `Priya`, task `send the revised quote to Acme`, due text `by Friday` | real `2026-09-01-quote-portal-kickoff.md` |
| P02 | `- [x] Sam to confirm cloud budget with finance` | `checked=true`, no due text | real `2026-09-22-quote-portal-weekly.md` |
| P03 | `- [X] Karan to approve the Q4 cloud spend` in a CRLF file | `checked=true`. No `\r` in any captured text. | real `2026-10-02-finance-sync.md` |
| P04 | `* [ ] Sam to cut cloud costs by 10% — proposal by 2026-10-09` | parsed as checkbox. Due text is `by 2026-10-09`, not `by 10%`. | real `2026-10-02-finance-sync.md` |
| P05 | `+ [ ] Sam to propose the on-call rotation by mid-October` | parsed, due text `by mid-October` | real `2026-09-30-q4-offsite.md` |
| P06 | Indented `  - [ ] Karan to validate targets against the budget by Oct 5th` | parsed as an action despite the indent | real `2026-09-30-q4-offsite.md` |
| P07 | `ACTION: Karan to circulate the offsite summary tomorrow` | `syntax=action`, `checked=false`, due text `tomorrow` | real `2026-09-30-q4-offsite.md` |
| P08 | Row `\| Anita \| Refresh the brand kit \| 2026-10-09 \|` under header Owner / Action / Due | `syntax=table`, owner `Anita`, task `Refresh the brand kit`, due text `2026-10-09`. The header row and separator row are not items. | real `2026-09-30-q4-offsite.md` |
| P09 | Checkboxes under "Afternoon: people and process", with no `## Action items` heading | items found anywhere in the file | real `2026-09-30-q4-offsite.md` |
| P10 | Same, in a file with no header at all | 2 lines found: `Sam to chase the vendor`, `Priya to send the slides by Friday` | real `untitled.md` |
| P11 | A table with a different column order (Due / Owner / Action) | columns mapped by header name, not position | fixture |
| P12 | An open checkbox and a done checkbox on adjacent lines | each keeps its own `checked` | fixture |

### 2.2 Lines that must be excluded (traps)

| ID | Input | Expected result | Source |
|---|---|---|---|
| P20 | `> - [ ] Karan to refund affected customers by Friday` | not an action. The real line below it (no due) is the only match. | real `2026-09-21-incident-review.md` |
| P21 | `- [ ] Owner to remediate finding by <date>` inside a fenced block | excluded | real `2026-10-09-security-review.md` |
| P22 | `<!-- - [ ] Sam to buy hardware tokens for everyone by Friday ... -->` | excluded | real `2026-10-09-security-review.md` |
| P23 | A multi-line HTML comment containing two checkboxes | both excluded. The checkbox after `-->` is included. | fixture |
| P24 | An indented fenced block (` ```` ` and `~~~`) with a checkbox | excluded. A checkbox after the closing fence is included. | fixture |
| P25 | Prose: `Priya offered to help recruit`, `Karan will send the vendor list` | no rows from prose. Where an action line duplicates the prose, exactly one row exists. | real `2026-09-09-qa-standup.md`, `2026-09-30-q4-offsite.md` |
| P26 | An unclosed fence at end of file | everything after the opening fence is excluded and a warning is recorded. No crash. | fixture |
| P27 | A `- [ ]` with no text after it | not an action, no crash | fixture |

### 2.3 Owner and due text capture

| ID | Input | Expected result | Source |
|---|---|---|---|
| P30 | `- [ ] @anita: audit colour contrast on the dashboard by Mon` | owner text `@anita`, task `audit colour contrast on the dashboard`, due `by Mon` | real `2026-09-18-design-review.md` |
| P31 | `- [ ] Anita & Rahul to agree on the component API by Wednesday` | owner text `Anita & Rahul` | real `2026-09-18-design-review.md` |
| P32 | `- [ ] Lena (with Priya) to collect user feedback on the prototype by 2026-09-25` | owner text `Lena (with Priya)` | real `2026-09-18-design-review.md` |
| P33 | `- [ ] Everyone to review the prototype before the next review` | owner text `Everyone`. `before the next review` is not a date phrase. | real `2026-09-18-design-review.md` |
| P34 | `- [ ] TBD to write the design-system changelog` | owner text `TBD` | real `2026-09-18-design-review.md` |
| P35 | `- [ ] Priya N. to send revised quote to Acme — by Friday` | owner text `Priya N.`, due `by Friday`, the em-dash is not in the task | real `2026-09-08-quote-portal-weekly.md` |
| P36 | `- [ ] Rahul to review Anita's PR by tomorrow` | owner text `Rahul`. Anita appears only in the task. | real `2026-10-07-standup.md` |
| P37 | `- [ ] Book the venue` (no `<Name> to`) | owner text None, task `Book the venue` | fixture |
| P38 | `- [ ] Karan to freeze invoice edits from 9 Oct` | task keeps `from 9 Oct`, due text recorded but flagged non-deadline by the dates module | real `2026-09-29-billing-cutover-planning.md` |
| P39 | Prose only: `Sam will rotate the staging credentials after the weekend` (no action line for Sam) | no item and no due text taken from Discussion | real `2026-09-23-standup.md` |

### 2.4 Header and attendees (SPEC 4.1)

| ID | Input | Expected result | Source |
|---|---|---|---|
| P40 | `Date: 2026-09-01` | date `2026-09-01`, `date_source=header` | real `2026-09-01-quote-portal-kickoff.md` |
| P41 | `Date: 9 September 2026` | `2026-09-09` | real `2026-09-09-qa-standup.md` |
| P42 | `Date: Monday, 14 September 2026` | `2026-09-14` | real `2026-09-14-onboarding-flow-design.md` |
| P43 | YAML front matter, `date: 2026-09-16`, `title:`, `attendees: [A, B, C]` | date and attendee list parsed, title from `title:` | real `2026-09-16-standup.md`, `2026-09-30-standup.md` |
| P44 | `Date: sometime last week` | date from filename `2026-10-03`, `date_source=filename`, warning recorded | real `2026-10-03-sales-pipeline.md` |
| P45 | No `Attendees:` line | attendees `[]`, no failure | real `2026-09-23-standup.md` |
| P46 | Comma-separated `Attendees: A, B, C, D` | 4 full names, whitespace trimmed | real `2026-09-01-quote-portal-kickoff.md` |
| P47 | Nine attendees | all 9 captured | real `2026-09-30-q4-offsite.md` |
| P48 | Title and filename disagree | header used. Title kept as written. No warning needed. | real `2026-10-05-onboarding-retro.md` |
| P49 | Header date and filename date disagree (header `2026-09-02`, file `2026-09-01-x.md`) | header wins, warning recorded (D19) | fixture |
| P50 | No header date and a filename without a date prefix | `date=None`, `date_source=none` | real `untitled.md` |

### 2.5 Reader and malformed notes (SPEC 5.5)

| ID | Input | Expected result | Source |
|---|---|---|---|
| P60 | 0-byte `.md` file | `Skip` reason `empty file (0 bytes)` | real `2026-09-09-notes-final-v2.md` |
| P61 | File starting with NUL and control bytes, PNG signature inside | `Skip` reason `not text (binary content)` | real `scratch.md` |
| P62 | `.txt` file | `Skip` reason `not a .md file`. Its content is never read as items. | real `2026-09-19-offsite-draft.txt` |
| P63 | Valid UTF-8 plus one invalid byte (`\xff`) | `Skip` reason `not text (binary content)` | fixture |
| P64 | UTF-8 BOM before `Date:` | BOM stripped, date parsed | fixture |
| P65 | CRLF line endings | normalised to LF, hash identical to the LF version of the same text | real `2026-10-02-finance-sync.md` |
| P66 | A file whose parsing raises (monkeypatch `find_action_lines` to raise `ValueError("boom")`) | `Skip` reason `parse error: boom`. The other files in the folder are still parsed. | fixture |
| P67 | A file that is unreadable (`chmod 000`) | `Skip` with an OS error reason, no crash (skipped on Windows) | fixture |
| P68 | A directory named `x.md` inside the folder | not treated as a note. Ignored without a crash. | fixture |
| P69 | Folder path does not exist or is a file | `UsageError`, exit 2 | fixture |
| P70 | File name with spaces and unicode | read and reported by its exact name | fixture |
| P71 | Very long single line (1 MB) | parsed or skipped, finishes in under 2 seconds, no crash | fixture |

---

## 3. Dates (SPEC 6, 7.1)

Each row calls `resolve_due(phrase, meeting_date)` and expects `(due, raw)`. Weekday names in the meeting column are for the reader and are not inputs.

### 3.1 Resolution table (every row of SPEC 6.2)

| ID | Phrase | Meeting date | Expected due | Source |
|---|---|---|---|---|
| D01 | `by Friday` | 2026-09-01 (Tue) | 2026-09-04 | both (`2026-09-01-quote-portal-kickoff.md`) |
| D02 | `by Friday` | 2026-09-18 (Fri) | 2026-09-25 (same weekday adds 7) | fixture |
| D03 | `by Monday` | 2026-09-03 (Thu) | 2026-09-07 | real `2026-09-03-billing-migration-sync.md` |
| D04 | `by Mon` | 2026-09-18 (Fri) | 2026-09-21 | real `2026-09-18-design-review.md` |
| D05 | `by Wednesday` | 2026-09-18 (Fri) | 2026-09-23 | real `2026-09-18-design-review.md` |
| D06 | `by tomorrow` | 2026-10-06 (Tue) | 2026-10-07 | real `2026-10-06-quote-portal-weekly.md` |
| D07 | `by EOD` | 2026-10-08 (Thu) | 2026-10-08 | real `2026-10-08-billing-go-no-go.md` |
| D08 | `by EOD tomorrow` | 2026-09-21 (Mon) | 2026-09-22 | real `2026-09-21-incident-review.md` |
| D09 | `by next Tuesday` | 2026-10-05 (Mon) | 2026-10-13 | real `2026-10-05-onboarding-retro.md` |
| D10 | `by next Tuesday` | 2026-09-18 (Fri) | 2026-09-22 | fixture |
| D11 | `by end of next week` | 2026-09-03 (Thu) | 2026-09-11 | real `2026-09-03-billing-migration-sync.md` |
| D12 | `by end of month` | 2026-09-14 (Mon) | 2026-09-30 | real `2026-09-14-onboarding-flow-design.md` |
| D13 | `by mid-October` | 2026-09-30 (Wed) | 2026-10-15 | real `2026-09-30-q4-offsite.md` |
| D14 | `by 2026-10-09` | 2026-10-02 | 2026-10-09 | real `2026-10-02-finance-sync.md` |
| D15 | `by 10 Sep` | 2026-09-03 (Thu) | 2026-09-10 | real `2026-09-03-billing-migration-sync.md` |
| D16 | `by Wed 16 Sep` | 2026-09-14 (Mon) | 2026-09-16 | real `2026-09-14-onboarding-flow-design.md` |
| D17 | `by Oct 3rd` | 2026-09-30 (Wed) | 2026-10-03 (a Saturday, accepted) | real `2026-09-30-q4-offsite.md` |
| D18 | `results due 15 October` | 2026-09-30 (Wed) | 2026-10-15 | real `2026-09-30-q4-offsite.md` |
| D19 | `by 7 Jan` | 2026-12-20 (Sun) | 2027-01-07 (year rolls) | fixture |
| D20 | `circulate the offsite summary tomorrow` (bare trailing word) | 2026-09-30 (Wed) | 2026-10-01 | real `2026-09-30-q4-offsite.md` |

### 3.2 Non-deadlines and unresolvable

| ID | Phrase | Meeting date | Expected result | Source |
|---|---|---|---|---|
| D30 | `before cutover` | 2026-09-03 | due None, raw `before cutover` | real `2026-09-03-billing-migration-sync.md` |
| D31 | `freeze invoice edits from 9 Oct` | 2026-09-29 | due None, raw kept (a start date) | real `2026-09-29-billing-cutover-planning.md` |
| D32 | `schedule cutover for Saturday 10 Oct` | 2026-09-29 | due None | real `2026-09-29-billing-cutover-planning.md` |
| D33 | `demo the portal to Acme on 2026-10-14` | 2026-10-06 | due None | real `2026-10-06-quote-portal-weekly.md` |
| D34 | `by Friday` | None (undated note) | due None, raw `by Friday`. Today's date is never substituted. | real `untitled.md` |
| D35 | `by 2026-10-09` | None | 2026-10-09 (absolute dates still resolve) | fixture |
| D36 | `by 10%` | any | due None | real `2026-10-02-finance-sync.md` |
| D37 | `by sometime soon` | any | due None, no crash | fixture |
| D38 | Phrase with two deadlines: `by Friday ... by 2026-10-09` | 2026-10-02 | the last one wins: 2026-10-09 | fixture |
| D39 | `by Wed 17 Sep` (17 Sep 2026 is a Thursday) | 2026-09-14 | due 2026-09-17, warning for the weekday mismatch (D22) | fixture |
| D40 | `by 31 Feb` | any | due None, no crash | fixture |
| D41 | Empty string and None | any | due None | fixture |
| D42 | Same input with `today` mocked to three different dates | 2026-09-01 | the resolved due is identical each time (proves today is never used) | fixture |

### 3.3 Header dates

| ID | Input | Expected | Source |
|---|---|---|---|
| D50 | `2026-09-01`, `9 September 2026`, `Monday, 14 September 2026` | 2026-09-01, 2026-09-09, 2026-09-14 | real (the three files named in P40 to P42) |
| D51 | `sometime last week`, `` (empty), `13/45/2026` | None | real `2026-10-03-sales-pipeline.md` and fixture |
| D52 | `Monday, 15 September 2026` (15 Sep 2026 is a Tuesday) | 2026-09-15, weekday ignored | fixture |

### 3.4 Overdue definition (SPEC 7.1)

`is_overdue(status, due, today)` with `today = 2026-10-22`.

| ID | Status | Due | Expected | Source |
|---|---|---|---|---|
| D60 | open | 2026-10-21 | overdue | fixture |
| D61 | open | 2026-10-22 (due today) | **not** overdue | fixture |
| D62 | open | 2026-10-23 | not overdue | fixture |
| D63 | open | None | never overdue | fixture |
| D64 | done | 2026-09-01 | not overdue | fixture |
| D65 | open | 2026-10-21, `today` 2026-10-21 | not overdue (proves `--today` is honoured) | fixture |

---

## 4. Owners (SPEC 4.2, 5.2, 5.3)

Roster for these cases is the nine names in `data-findings.md` section 1 unless noted.

| ID | Input (owner text, attendees) | Expected | Source |
|---|---|---|---|
| O01 | `Anita`, attendees without Anita | `Anita Desai`, kind person (a unique first name resolves from the roster) | fixture |
| O02 | `Sam`, `Meera`, `Karan`, `Lena` | each resolves to its full name | real `2026-10-02-finance-sync.md` and others |
| O03 | `Priya`, only Priya Nair attended | `Priya Nair` | real `2026-09-01-quote-portal-kickoff.md` |
| O04 | `Priya`, only Priya Shah attended | `Priya Shah` | real `2026-09-03-billing-migration-sync.md` |
| O05 | `Priya`, both Priyas attended | `Ambiguous (Priya)`, kind ambiguous, warning | real `2026-09-17-billing-migration-sync.md` |
| O06 | `Priya`, both attended, in a note that also has `Priya N.` | `Priya` is `Ambiguous (Priya)` and `Priya N.` is `Priya Nair` | real `2026-10-08-billing-go-no-go.md` |
| O07 | `Priya S.` and `Priya N.` | `Priya Shah` and `Priya Nair` | real `2026-09-29-billing-cutover-planning.md` |
| O08 | `Priya N.`, only one Priya attended and she is Nair | `Priya Nair` | real `2026-09-08-quote-portal-weekly.md` |
| O09 | `Priya N.` but only Priya Shah attended | `Priya Nair` (the initial wins) plus a warning (SPEC 5.3 rule 1) | fixture |
| O10 | `Priya`, attendees `[]` | `Ambiguous (Priya)` | real `2026-09-23-standup.md` |
| O11 | `Rahul`, both Rahuls attended | `Ambiguous (Rahul)` (no inference, D23) | real `2026-10-07-standup.md` |
| O12 | `Rahul`, only Rahul Verma attended | `Rahul Verma` | real `2026-10-09-security-review.md` |
| O13 | `Rahul`, attendees `[]` | `Ambiguous (Rahul)` | real `2026-09-23-standup.md` |
| O14 | `Priya` and `Rahul` with all 9 attending | both ambiguous | real `2026-09-30-q4-offsite.md` |
| O15 | `Priya` in a note whose attendees include Priya Nair and Rahul Mehta but neither Shah nor Verma | `Priya Nair` | real `2026-09-18-design-review.md` |
| O16 | `@anita` | `Anita Desai` | real `2026-09-18-design-review.md` |
| O17 | `Anita & Rahul`, both Rahuls attended | owner `Anita Desai`, collaborators `["Ambiguous (Rahul)"]` | real `2026-09-18-design-review.md` (attendees adjusted in a fixture variant) |
| O18 | `Lena (with Priya)` | owner `Lena Fischer`, collaborators `[Priya ...]` resolved by the same rules | real `2026-09-18-design-review.md` |
| O19 | `Everyone`, `Team`, `Everybody` | `Unassigned`, kind unassigned, original word kept | real `2026-09-18-design-review.md`, `2026-10-01-quote-portal-weekly.md` |
| O20 | `TBD`, `Someone`, `Anyone` | `Unassigned` | real `2026-09-10-acme-renewal-prep.md` |
| O21 | owner text None | `Unassigned` | fixture |
| O22 | Case variants: `priya`, `PRIYA`, `Priya ` | handled exactly as `Priya` | fixture |
| O23 | A name not in the roster (`Zoe`) | `Zoe`, kind person, warning "unknown owner". Not dropped. | fixture |
| O24 | `Rahul to review Anita's PR`: owner and task | owner from the owner text only, Anita not the owner | real `2026-10-07-standup.md` |
| O25 | Roster is built from all notes, regardless of read order | shuffled input gives the same resolutions | fixture |

---

## 5. Dedupe and IDs (DATA_MODEL 3, 4; SPEC 5.1)

| ID | Input | Expected | Source |
|---|---|---|---|
| DD01 | Sam, `confirm cloud budget with finance` in 09-01, 09-15 (by Friday), 09-22 `[x]` | 1 item. Status done, due 2026-09-18, 3 mentions, `first_file` 09-01, `latest_file` 09-22. | real |
| DD02 | Priya Nair, `send revised quote to Acme` in 09-01, 09-08 (`Priya N.`), 09-15 `[x]` | 1 item, owner Priya Nair, status done, due 2026-09-11, 3 mentions | real |
| DD03 | Anita, `share wireframes` in 09-01, 09-15 (updated), 09-22 (updated) | 1 item, still open, due from 09-22, wording from 09-22 | real |
| DD04 | Karan, `freeze invoice edits from 9 Oct` in 09-29 and 10-08 | 1 item, open, due None, 2 mentions | real |
| DD05 | Karan, `refund affected customers`: quoted line plus real line in 09-21 | 1 item, 1 mention (the quoted line was excluded by the parser) | real `2026-09-21-incident-review.md` |
| DD06 | Rahul, `deploy beta to staging` in 10-01, 10-06, 10-13 `[x]` | 1 item, done | real (Rahul resolved or ambiguous by attendance, whichever the note gives) |
| DD07 | Meera, `book renewal call with Acme's CTO` in 09-10, 09-28, 10-14 `[x]` | 1 item, done | real |
| DD08 | Karan, `export last quarter invoices` in 09-03 (by 10 Sep), 09-17 `[x]` | 1 item, done, due 2026-09-10 (latest non-empty) | real |
| DD09 | Priya N., `notify customers re maintenance window` in 09-29 and 10-08 `[x]` | 1 item, done | real |
| DD10 | Lena, `usage report`: 09-10 `pull ... by tomorrow` and 09-28 `share with Meera` | the tokens are different enough to stay as **two** items if Jaccard < 0.6. The test records the actual score and asserts the item count the rule yields. | real |
| DD11 | `Priya` (ambiguous) and `Priya Nair` with the same task text | 2 separate items, never merged (never guess) | fixture |
| DD12 | `Priya Nair` and `Priya Shah`, identical task text | 2 separate items | fixture |
| DD13 | Same task text, owners `Sam Okafor` and `Karan Joshi` | 2 items | fixture |
| DD14 | Two `Unassigned` items with the same text, in two notes | 1 item | fixture |
| DD15 | `{export, last, quarter, invoices}` vs `{review, schema, mapping, doc}` | similarity 0.0, separate items | fixture |
| DD16 | `{share, wireframes}` vs `{share, updated, wireframes}` | similarity 0.667, merged | fixture |
| DD17 | Exactly 0.6 (3 shared of 5 total) vs 0.5999 | merged at 0.6, separate below it | fixture |
| DD18 | Stop-words and punctuation: `Send the revised quote to Acme!` vs `send revised quote Acme` | `task_key` equal, similarity 1.0 | fixture |
| DD19 | `task_key("send the revised quote to Acme")` | `send revised quote acme` | fixture |
| DD20 | A later mention reopens: `[x]` in 09-17 then open in 10-01 for the same task | item is open (latest mention wins) | fixture |
| DD21 | Latest-non-empty due: due set in the middle mention, empty in the last | the middle due is kept | fixture |
| DD22 | A task appearing twice in one note | 1 item, 2 mentions | fixture |
| DD30 | ID of DD01 | `b48cced6`, equal to `sha1("Sam Okafor\|confirm cloud budget finance")[:8]` | real |
| DD31 | ID of DD02 | `cfc90787` | real |
| DD32 | Same mentions in 100 random orders | identical IDs, groups and item fields every time | both |
| DD33 | Wording drift: `share wireframes` renamed `share the updated wireframes` in a later note | same ID before and after | fixture |
| DD34 | Due date and `[x]` changed in the later note | same ID | fixture |
| DD35 | IDs are 8 lowercase hex characters | regex match for every item | real (all of `notes/`) |
| DD36 | No two items share an ID across all of `notes/` | all unique | real |
| DD37 | Forced collision: two keys patched to hash to the same prefix | the later key gets the `#2` suffix, both IDs unique, deterministic across runs | fixture |
| DD38 | Earlier-dated note added later (D9 limit) | the ID changes. The test documents this limit. | fixture |
| DD39 | ID unaffected by row order and time: run ingest with a mocked clock at two times | same IDs | fixture |

---

## 6. Store (DATA_MODEL 2, 5)

All use a temp database unless marked in-memory.

| ID | Input | Expected | Source |
|---|---|---|---|
| S01 | Open a new path | the three tables, indexes and `foreign_keys=ON` exist | fixture |
| S02 | Ingest the notes, then ingest the same folder again | same item count, same ID set, `new 0, unchanged N` in the counts | real (`notes/`) |
| S03 | Row-for-row snapshot of `items` before and after the second ingest | identical, including all columns (no id or field churn) | real |
| S04 | `mentions` count before and after the second ingest | identical (file's mentions are replaced, not appended) | real |
| S05 | Edit one file (change `by Friday` to `by Monday`) and re-ingest | that item's due changes, its ID does not, other items unchanged, `updated 1` | both |
| S06 | Unchanged file (same `content_hash`) | counted as unchanged and its mentions are not rewritten | real |
| S07 | Same text with CRLF vs LF | the same hash, so unchanged | real `2026-10-02-finance-sync.md` |
| S08 | `mark_done` on an open item | `status=done`, `done_manual=1`, returns True | fixture |
| S09 | `mark_done`, then re-ingest, where the note still shows `[ ]` | stays done (sticky, D16) | fixture |
| S10 | `mark_done` on a done item | returns False, no change | fixture |
| S11 | A note says `[x]`, the user has not run `done` | `status=done`, `done_manual=0` | fixture |
| S12 | Remove a file from the folder and re-ingest | its items and mentions stay (D10) | fixture |
| S13 | Edit a file so a task is deleted from it | the item disappears only if no other mention remains. Otherwise `mention_count` drops. | fixture |
| S14 | Force an exception in the middle of `apply_ingest` (monkeypatch) | transaction rolls back, the database is byte-identical to before, `StoreError` | fixture |
| S15 | Insert a mention with a missing `file` | the foreign-key violation raises `StoreError` | fixture |
| S16 | `status='overdue'` insert attempt | CHECK constraint rejects it (overdue is never stored) | fixture |
| S17 | `owner_kind` invalid | CHECK rejects | fixture |
| S18 | `list_items` with each filter on a seeded db of 8 items | each filter returns exactly the expected IDs (see L-cases) | fixture |
| S19 | SQL strings contain only bound parameters. An owner value `x'; DROP TABLE items;--` | no injection, the table survives, no match | fixture |
| S20 | Unwritable database path | `StoreError`, exit 1, no partial file | fixture |
| S21 | Two ingest runs back to back from two processes | the second waits or fails cleanly, never corrupts (SQLite lock) | fixture |
| S22 | `ingested_at` differs on the second run | no ID, no sort order and no item field depends on it | fixture |

---

## 7. Ingest orchestration and summary (SPEC 3.1, 5.5)

| ID | Input | Expected | Source |
|---|---|---|---|
| I01 | Ingest `notes/` | exit 0. Skipped files are **exactly** `2026-09-09-notes-final-v2.md` (empty), `scratch.md` (binary), `2026-09-19-offsite-draft.txt` (not .md). | real |
| I02 | The same run | the summary prints each skipped file on its own line with its reason text from SPEC 5.5 | real |
| I03 | The same run | `untitled.md` is ingested with a warning: no date, no attendees, 2 items, `by Friday` unresolved | real |
| I04 | The same run | `2026-10-03-sales-pipeline.md` is ingested with a warning, date `2026-10-03` from the filename | real |
| I05 | The same run | `2026-09-23-standup.md` is ingested. Its Rahul item is `Ambiguous (Rahul)` and the warning names it. | real |
| I06 | The same run | `2026-09-30-q4-offsite.md` warns about ambiguous Priya and Rahul | real |
| I07 | The same run | `2026-10-02-finance-sync.md` (CRLF, `[X]`, `*`, `+`) is ingested without warnings about its format | real |
| I08 | The same run | counts line up: items found = unique + duplicates merged, and scanned = ingested + skipped | real |
| I09 | Folder with only malformed files (empty, binary, `.txt`) | exit 0, all three listed, 0 items, no crash | fixture |
| I10 | Empty folder | exit 0, `Scanned 0 files`, nothing else | fixture |
| I11 | Folder with one good note and four malformed ones | the good note's items are stored. Skips are listed. | fixture |
| I12 | A malformed file sorted first alphabetically | later files are still processed (the run keeps going) | fixture |
| I13 | Folder does not exist | exit 2, message on stderr, no database file created | fixture |
| I14 | Non-recursive: a `.md` file inside `sub/` | not ingested and not listed (D11) | fixture |
| I15 | Two notes with the same date (09-09 qa-standup and the empty file) | the empty file is skipped, the standup is ingested | real |
| I16 | Notes dated on a Saturday (`2026-10-03`, `2026-10-10`) | accepted, no warning (D17) | real |
| I17 | Warnings go to stderr, the summary to stdout | stream split verified with `CliRunner(mix_stderr=False)` | real |
| I18 | Run ingest with `--db` in a different directory | database created there, nothing in the cwd | fixture |
| I19 | `ACTIONTRACK_DB` set and `--db` also given | `--db` wins | fixture |
| I20 | Ingest never prints a traceback for any file in `notes/` | stderr has no `Traceback` | real |
| I21 | Hostile content: an action line of 10,000 characters, emoji, RTL text | stored intact, no crash | fixture |

---

## 8. `list` (SPEC 3.2)

The seeded database for L-cases (all with `--today 2026-10-22`), built by a fixture, not from the notes:

| ID | Owner | Task | Due | Status |
|---|---|---|---|---|
| a1 | Sam Okafor | cut cloud costs | 2026-10-09 | open |
| a2 | Sam Okafor | propose on-call rotation | 2026-10-15 | open |
| a3 | Sam Okafor | confirm cloud budget | 2026-09-18 | done |
| a4 | Anita Desai | refresh brand kit | 2026-10-22 | open |
| a5 | Anita Desai | audit colour contrast | 2026-10-30 | open |
| a6 | Priya Nair | send revised quote | none | open |
| a7 | Ambiguous (Priya) | own the hiring plan | none | open |
| a8 | Unassigned | write the changelog | none | open |

| ID | Command | Expected | Source |
|---|---|---|---|
| L01 | `list` | all 8 rows, exit 0. Sorted by due ascending, no-due last. | fixture |
| L02 | `list --status overdue` | a1, a2 (not a4, due today, and not a3, done) | fixture |
| L03 | `list --status open` | a4, a5, a6, a7, a8 (not overdue and not done) | fixture |
| L04 | `list --status done` | a3 only | fixture |
| L05 | `list --due-before 2026-10-22` | a1, a2, a3 (strict `<`, a4 excluded, no-due items excluded) | fixture |
| L06 | `list --due-before 2026-10-23` | a1, a2, a3, a4 | fixture |
| L07 | `list --owner "Sam Okafor"` | a1, a2, a3 | fixture |
| L08 | `list --owner "sam okafor"` | the same (case-insensitive) | fixture |
| L09 | `list --owner Sam` | a1, a2, a3 (a unique first name) | fixture |
| L10 | `list --owner "Priya Nair"` | a6 only. Stderr warns that 1 item belongs to `Ambiguous (Priya)`. | fixture |
| L11 | `list --owner Priya` | a6 and a7, with a warning that the first name is shared | fixture |
| L12 | `list --owner Unassigned` | a8 | fixture |
| L13 | `list --owner "Sam Okafor" --status overdue` | a1, a2 (AND of filters) | fixture |
| L14 | `list --status overdue --due-before 2026-10-10` | a1 | fixture |
| L15 | `list --owner "Nobody"` | `No items found.`, exit 0 | fixture |
| L16 | `list --status late` | exit 2, message names the valid values | fixture |
| L17 | `list --due-before 10/10/2026` | exit 2 | fixture |
| L18 | `list --today 2026-13-01` | exit 2 | fixture |
| L19 | Same db, `--today 2026-10-09` | a1 is open, not overdue (due == today). Output is reproducible. | fixture |
| L20 | Same db, `--today 2026-10-16` | a1 and a2 overdue | fixture |
| L21 | Output columns | `ID STATUS OWNER DUE TASK SOURCE`. A merged item shows `<file> (+N)`. No-due prints `-`. | fixture |
| L22 | `list` on an empty database | `No items found.`, exit 0 | fixture |
| L23 | `list` on a missing database file | exit 0 with `No items found.` and no crash (or exit 2 with a hint to run `ingest`), whichever SPEC settles on. Test fixes the choice. | fixture |
| L24 | `list` after ingesting `notes/` | every row has an 8-hex ID. Overdue items carry `overdue` and done items `done`. No row says `Priya` alone. | real |
| L25 | Run `list --today 2026-10-22` twice | byte-identical output | real |

---

## 9. `done` (SPEC 3.3)

| ID | Command | Expected | Source |
|---|---|---|---|
| DN01 | `done a1` on an open item | exit 0, `Marked done: ...`, `list --status done` now includes it | fixture |
| DN02 | `done a1` again | exit 0, `Already done: a1`, state unchanged | fixture |
| DN03 | `done ffffffff` | exit 2, `no item with id ffffffff` | fixture |
| DN04 | `done A1B2C3D4` (upper case of a real ID) | matches the lower-case ID | fixture |
| DN05 | `done b48c` (a prefix) | exit 2 (prefixes are not supported, D15) | fixture |
| DN06 | `done` with no argument | exit 2 and a usage message | fixture |
| DN07 | `done <id>` on an ambiguous or unassigned item | allowed, exit 0 (closing is not owner-dependent) | fixture |
| DN08 | `done` then re-ingest of `notes/` | still done, the ID is unchanged, `done_manual=1` | real |
| DN09 | `done` then `followup` for the owner | the closed item is absent from the email | fixture |
| DN10 | `done` on an item that is overdue | no longer in `--status overdue` | fixture |
| DN11 | `done` with an ID that has leading or trailing spaces | trimmed and matched, or exit 2 with a clear message. Test fixes the choice. | fixture |
| DN12 | Two `done` calls racing | both exit 0 and the item is done once | fixture |

---

## 10. `followup` (SPEC 3.4, 7)

The seeded database from section 8, plus two more rows for Anita: a9 `share wireframes`, due 2026-09-24, open, and a10 `agree on component API`, no due, open, with collaborator `Rahul`. `--today 2026-10-22`. All use `InMemorySink` unless noted.

| ID | Command | Expected | Source |
|---|---|---|---|
| F01 | `followup "Anita Desai"` | exactly **1** draft, subject as in F02 | fixture |
| F02 | Same | counts: overdue = a9 (due 2026-09-24, 28 days overdue). Open = a4 (due today), a5, a10. Subject therefore reads `(1 overdue, 3 open)`. | fixture |
| F03 | Same | greeting `Hi Anita,`, sections `Overdue` then `Open`. Open sorted by due ascending, no-due last. | fixture |
| F04 | Same | each item line follows `- <task> (due YYYY-MM-DD[, N days overdue] \| no due date) [id] - from <file>`. a10 shows `(with Rahul)`. | fixture |
| F05 | Same | the item due today is listed under Open, not Overdue | fixture |
| F06 | Same | done items never appear. Ambiguous and unassigned items never appear. | fixture |
| F07 | `followup "Anita Desai"` where only overdue items exist | subject `(1 overdue)`, no `Open` section | fixture |
| F08 | Same, only open items | subject `(3 open)`, no `Overdue` section | fixture |
| F09 | `followup "Priya Nair"` | 1 draft with a6 only. Stderr warns that 1 ambiguous Priya item is not included. | fixture |
| F10 | `followup Priya` | exit 2, `ambiguous owner "Priya": use "Priya Nair" or "Priya Shah"`. **0** drafts. | fixture |
| F11 | `followup Unassigned` | exit 2, 0 drafts | fixture |
| F12 | `followup "Zoe Unknown"` | exit 2, `unknown owner`, 0 drafts | fixture |
| F13 | `followup "Karan Joshi"` where all his items are done | `No open or overdue items for Karan Joshi.`, exit 0, 0 drafts | fixture |
| F14 | `followup` with no `--email-map` | `To` is blank | fixture |
| F15 | `--email-map owners.csv` with `owner,email` rows | `To` is the mapped address. An owner not in the map keeps `To` blank. | fixture |
| F16 | `--email-map` with a missing file or a bad header | exit 2, 0 drafts | fixture |
| F17 | `--today 2026-10-09` vs `2026-10-22` | counts and the "N days overdue" text change accordingly. The same inputs give identical output. | fixture |
| F18 | `--dry-run` | the full email is printed to stdout, `DryRunSink` is used, 0 calls to any real sink | fixture |
| F19 | Run `followup` twice | 2 drafts are created (no dedupe, D14). The second does not fail. | fixture |
| F20 | Connector unavailable (sink raises `SinkUnavailable`) | exit 1, stderr says how to authorize, no retry, no partial output | fixture |
| F21 | Sink raises `DraftError` | exit 1, no retry | fixture |
| F22 | Validation order: an unknown owner with an unavailable sink | exit 2 (validation fails first), the sink is never called | fixture |
| F23 | Task text containing `&`, quotes, emoji, and a 500-character task | the body is intact plain text and the draft is created | fixture |
| F24 | Real data: ingest `notes/`, then `followup "Anita Desai" --today 2026-10-22` | 1 draft. Every listed ID exists in `list`. No done item is listed. No item has an ambiguous owner. | real |
| F25 | Real data: `followup "Sam Okafor"` | cloud-spend items already `[x]` are absent. Items with due before 2026-10-22 are under Overdue. | real |
| F26 | Real data, all nine owners in turn | at most one draft per owner, none for owners with nothing outstanding, **0** for `Ambiguous` or `Unassigned` | real |
| F27 | Subject line | contains no ID, no file name | fixture |
| F28 | Sign-off | body ends with `Thanks,` and no name (D13) | fixture |

---

## 11. Nothing is ever sent

The hard rule, tested at five levels. These run in CI and must never be skipped or marked xfail.

| ID | Check | Expected | Source |
|---|---|---|---|
| N01 | **Static scan.** Search every file under `src/` for Gmail send calls: `send_message`, `send_draft`, `messages.send`, `drafts.send`, `users().messages().send`, `smtplib`, `sendmail`, `SMTP(`. | no matches. The word "send" is allowed in task text, comments and docs. | fixture (source tree) |
| N02 | **Interface shape.** Inspect the `DraftSink` protocol. | its public members are exactly `["create_draft"]`. | fixture |
| N03 | **No send on any implementation.** For `GmailMcpSink`, `DryRunSink`, `InMemorySink`, check for attributes named `send*`, `reply*`, `schedule*`. | none exist | fixture |
| N04 | **Tool allow-list.** `GmailMcpSink` is given a fake `call_tool` that records `(name, args)`. Run `create_draft`. | exactly 1 call, whose name is the draft-creation tool name and no other | fixture |
| N05 | **Allow-list rejects others.** Call the adapter's private invoker with `send_message`, `send_draft`, `delete_draft`. | each raises before reaching `call_tool`. The fake records 0 calls. | fixture |
| N06 | **Strict sink mock.** A sink whose `__getattr__` raises on any name except `create_draft`. Run `followup` for each of the nine owners. | no `AttributeError`, only `create_draft` was used | fixture |
| N07 | **Recording MCP client, full run.** Ingest the real `notes/`, run `followup` for every owner through `GmailMcpSink` with a recording fake client. | the set of tool names seen is exactly `{draft-creation tool}`. The number of calls equals the number of drafts. | real |
| N08 | **Dry run and failures make no calls.** `--dry-run`, an unknown owner, an ambiguous first name, an owner with nothing outstanding, and `SinkUnavailable`. | the recording client sees 0 calls in every case | fixture |
| N09 | **No network.** Run the whole followup suite with `socket.socket` patched to raise. | all tests pass, because the sink is injected and nothing else opens a connection | fixture |
| N10 | **CLI surface.** `actiontrack --help` and `actiontrack followup --help`. | no command, flag or text offering `send`, `--send`, `--yes-send`, `--now` or `--deliver` | fixture |
| N11 | **No dependency on mail libraries.** Parse `pyproject.toml` and the imports of every module. | no `smtplib`, `yagmail`, `sendgrid`, `mailgun`, `google-api-python-client` send scope | fixture |
| N12 | **Draft payload shape.** Inspect what `GmailMcpSink` passes to the client. | contains `to`, `subject`, `body`. It contains no `send`, `send_at` or `schedule` key, and no `draft_id` to be sent. | fixture |
| N13 | **Result contract.** `DraftResult` is returned with a `draft_id` and the CLI prints `nothing was sent`. | the output text contains it | fixture |
| N14 | **Scope guard.** If a Gmail OAuth scope is configured anywhere in the repo, it is not a send or full-access scope. | passes (or is vacuous when none is configured) | fixture |

---

## 12. End-to-end on the real notes

Each case starts from an empty temp database and the real `notes/` folder, runs through the CLI (`CliRunner`) and passes `--today 2026-10-22`.

| ID | Scenario | Expected | Source |
|---|---|---|---|
| E01 | `ingest notes/` | exit 0. Skipped = exactly the 3 files from I01. Warnings include the files in I03 to I06. | real |
| E02 | `ingest` twice | the second run: `new 0, updated 0, unchanged N`. The item set is byte-identical (S02, S03). | real |
| E03 | Golden snapshot | the sorted `list` output equals `tests/golden/list_2026-10-22.txt`. Any behavior change shows up as a diff. The golden file is regenerated deliberately. | real |
| E04 | Duplicates | the items of DD01 to DD09 each appear once in `list`, with the expected status and due | real |
| E05 | No guessing | `list --owner Priya` shows `Ambiguous (Priya)` rows for 09-17, 10-08 (the un-initialled line), 09-30 and 09-23-style cases. None of those rows is attributed to a full name. | real |
| E06 | Traps excluded | `list` contains no item from the quoted, fenced, commented or `.txt` lines: no `buy hardware tokens`, no `remediate finding`, no `Book the venue`, and exactly one `refund affected customers` | real |
| E07 | Non-deadlines | `Freeze invoice edits` has due `-`. `before cutover` has due `-`. | real |
| E08 | Relative dates use the meeting date | an item from a 2026-09-01 note saying `by Friday` shows 2026-09-04 whatever `--today` is. Run with three different `--today` values: the due column is identical, only the status changes. | real |
| E09 | Overdue | with `--today 2026-10-22`, `list --status overdue` is non-empty and every row has due < 2026-10-22 and status open | real |
| E10 | `done` then `list` | pick one overdue item, mark it done, it leaves `--status overdue` and appears in `--status done` | real |
| E11 | `done` survives re-ingest | after E10, `ingest` again: the item is still done and no ID changed | real |
| E12 | `followup` for one owner | 1 draft, subject counts match `list` for that owner, nothing sent (N07 recorder) | real |
| E13 | Full loop | ingest, list, done, followup, ingest again. Final state is consistent and every exit code is 0. | real |
| E14 | Robustness | add three extra malformed files (truncated YAML front matter, a note of only `---`, a note with a 5 MB line) to a copy of `notes/` and ingest | exit 0, 3 more skipped or warned files, the original items unchanged | both |
| E15 | Performance | ingest of `notes/` takes under 5 seconds and `list` under 1 second on a normal laptop | real |
| E16 | `python -m actiontrack` behaves the same as the `actiontrack` script | identical output for E03 | real |
| E17 | Code quality gates | `ruff check .` and `ruff format --check .` pass | real |

---

## 13. Coverage matrix

Where each hard rule or spec edge case is covered. A rule with no row here is not tested.

| Rule or edge case | Cases |
|---|---|
| Never send email | N01 to N14, F18, F20, E12 |
| Never crash on a malformed note | P60 to P71, I01, I09 to I12, I20, E01, E14 |
| Every skipped file listed with a reason | I01, I02, I09, I11 |
| Relative dates use the meeting date, not today | D01 to D20, D34, D42, E08 |
| Only overdue compares to today | D60 to D65, L19, L20, E09 |
| IDs stable on re-ingest | DD30 to DD39, S02 to S05, E02, E11 |
| Same-first-name owners never guessed | O05 to O15, DD11, DD12, I05, I06, F09, F10, E05 |
| Duplicates collapse | DD01 to DD22, E04 |
| No owner | O19 to O21, P33, P34, P37, F11, L12 |
| No date | D34, D35, D41, P10, P50, I03 |
| Malformed notes | P60 to P71, I01 to I12 |
| Non-actions excluded | P20 to P27, E06 |
| Overdue never stored | S16, D60 to D65 |
| Manual done is sticky | S09, DN08, E11 |
