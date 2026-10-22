# Data findings: notes folder

**Important:** `docs/SCENARIO.md` is **0 bytes**. There is no scenario text to compare against, so everything below is derived from the data alone. See Question 1.

Scope: 36 files in `notes/` (31 regular meeting notes, 2 YAML front-matter notes, plus 5 oddballs listed in section 4). Each file was read in full, and hidden bytes (CRLF, encoding) were checked.

## 1. Date formats and attendee lists

**Dates** (all 2026, Sep 1 to Oct 14):

| Form | Example | Where |
|---|---|---|
| `Date: YYYY-MM-DD` (the norm) | `Date: 2026-09-01` | most files |
| Day Month Year | `Date: 9 September 2026` | 2026-09-09-qa-standup |
| Weekday, Day Month Year | `Date: Monday, 14 September 2026` | 2026-09-14-onboarding-flow-design |
| YAML front matter, lowercase key | `date: 2026-09-16` | 2026-09-16-standup, 2026-09-30-standup |
| Unparseable prose | `Date: sometime last week` | 2026-10-03-sales-pipeline (filename says 10-03) |
| No date at all | n/a | untitled.md, 2026-09-19-offsite-draft.txt, scratch.md, notes-final-v2.md |

Filenames carry `YYYY-MM-DD-` and agree with the header date in every file that has a parseable one. Two notes fall on a Saturday (2026-10-03, 2026-10-10). Two filenames share a date: 09-09 (qa-standup and the empty notes-final-v2) and 09-30 (offsite and standup).

**Headers:** most files use `# Meeting: <title>`. The two YAML files use `title:` instead. `2026-10-05-onboarding-retro.md` is titled "Onboarding flow checkpoint", so title and filename disagree.

**Attendees:**
- Plain line, comma-separated full names: `Attendees: Priya Nair, Rahul Mehta, Anita Desai, Sam Okafor`.
- YAML flow list: `attendees: [Anita Desai, Lena Fischer, Meera Iyer]`.
- Missing entirely: 2026-09-23-standup (has a date but no `Attendees:` line), plus the non-meeting files.
- Always full names. Action items use first names only (see section 3).
- Roster of 9: Priya Nair, Rahul Mehta, Anita Desai, Sam Okafor, Meera Iyer, Karan Joshi, Lena Fischer, **Priya Shah**, **Rahul Verma**. The offsite (09-30) lists all nine.

## 2. Action-item line variations (one example each)

Real, checkbox-style:
1. Open, dash: `- [ ] Priya to send the revised quote to Acme by Friday` (09-01)
2. Done, lowercase x: `- [x] Sam to confirm cloud budget with finance` (09-22)
3. Done, uppercase X: `- [X] Karan to approve the Q4 cloud spend` (10-02, CRLF file)
4. Star bullet: `* [ ] Sam to cut cloud costs by 10% — proposal by 2026-10-09` (10-02)
5. Plus bullet: `+ [ ] Sam to propose the on-call rotation by mid-October` (09-30 offsite)
6. Nested/indented sub-item: `  - [ ] Karan to validate targets against the budget by Oct 5th` (09-30 offsite)
7. @handle owner with colon: `- [ ] @anita: audit colour contrast on the dashboard by Mon` (09-18)
8. Joint owners: `- [ ] Anita & Rahul to agree on the component API by Wednesday` (09-18)
9. Owner plus helper: `- [ ] Lena (with Priya) to collect user feedback on the prototype by 2026-09-25` (09-18)
10. Group owner: `- [ ] Everyone to review the prototype before the next review` (09-18); also `Team to decide on the launch date` (10-01)
11. Unassigned owner: `- [ ] TBD to write the design-system changelog` (09-18); `- [ ] Someone to update the CRM notes` (09-10)
12. Initial-disambiguated owner: `- [ ] Priya S. to run the invoice rounding tests by Thursday` (09-29)
13. Em-dash inside the line: `- [ ] Priya N. to send revised quote to Acme — by Friday` (09-08)
14. Checkbox with no `## Action items` section: `- [ ] Priya to own the hiring plan for the two QA roles` under "Afternoon: people and process" (09-30 offsite); `- [ ] Sam to chase the vendor` (untitled.md)

Real, not checkbox-style (offsite 09-30 only):
15. `ACTION:` prefix: `ACTION: Karan to circulate the offsite summary tomorrow`
16. Markdown table row: `| Anita | Refresh the brand kit | 2026-10-09 |` (columns Owner / Action / Due)

Look like actions but are **not** (traps):
17. Block-quoted checkbox (a customer success lead's wish, quoted from a forwarded note): `> - [ ] Karan to refund affected customers by Friday` (09-21). The real action is below it with no due date.
18. Fenced code block template: `- [ ] Owner to remediate finding by <date>` (10-09)
19. HTML comment, explicitly "cut from the agenda": `<!-- - [ ] Sam to buy hardware tokens for everyone by Friday ... -->` (10-09)
20. Non-meeting draft: `- [ ] Book the venue` (2026-09-19-offsite-draft.txt, "Not a meeting note")

Commitments in Discussion prose with no checkbox (some duplicate a checkbox, some are orphans):
- `Sam to propose a 10% cost cut` (10-02, also an action line)
- `Karan will send the vendor list` (09-09, also an action line)
- `Priya offered to help recruit`, `Everybody should look at the prototype`, `someone has to own the plan` (hiring), `Rahul and Anita ... will settle it between them` (no action line)

## 3. Owners and due dates, including odd cases

**Owners.** Always first name only, in the form `<Name> to <verb> ...`.
- Same-name pairs: see section 5.
- Initial suffix: `Priya S.`, `Priya N.` (09-29, 10-08). `Priya N.` is also used in 09-08, where only one Priya attended.
- Handle: `@anita:` (09-18).
- Multiple: `Anita & Rahul`, `Lena (with Priya)`.
- No individual: `Everyone`, `Team`, `TBD`, `Someone`.
- Owner named inside the task: `Rahul to review Anita's PR` (10-07). Anita is not the owner.
- Table form: bare `Anita` in an Owner column.

**Due dates.** Written after `by` (sometimes `due`, `from`, `before`, `on`, `for`), usually at the end, sometimes mid-line before an em-dash.
- ISO: `by 2026-09-08`
- Weekday only: `by Friday`, `by Mon`, `by Wed`, `by Wednesday`. These need the meeting date to resolve (no meeting falls on its own due weekday).
- Weekday plus date: `by Wed 16 Sep` (09-14)
- Day-month, no year: `by 10 Sep`, `by 25 Sep`, `by 7 Oct`, `by 23 Oct`
- Month-day with ordinal: `by Oct 3rd`, `by Oct 5th` (offsite)
- Relative: `by tomorrow`, `by EOD`, `by EOD tomorrow`, `by next Tuesday`, `by end of next week`, `by end of month`, `by mid-October`
- Phrased differently: `results due 15 October` (offsite)
- Event-relative: `before cutover` (09-03)
- **Not deadlines (start or event dates):** `freeze invoice edits from 9 Oct`, `schedule cutover for Saturday 10 Oct`, `demo the portal to Acme on 2026-10-14`
- None given: many items, including nearly every `[x]` item.

Due dates that need a judgment call:
- `end of next week` (09-03, a Thursday) could mean Sep 11 or Sep 18.
- `by Oct 3rd` is a Saturday.
- `by mid-October` has no exact day.
- Due-date wording is sometimes in the Discussion, not the item (`Sam will rotate the staging credentials after the weekend`, 09-23).

## 4. Files that look malformed, and why

| File | Problem |
|---|---|
| `2026-09-09-notes-final-v2.md` | 0 bytes. Name suggests a duplicate or revision of the 09-09 qa-standup note. |
| `scratch.md` | Not text. 249 bytes of binary: starts with NUL/control bytes and fragments of "# Meeting" and "Date:", then a PNG signature and byte-ramp filler. Unparseable. |
| `untitled.md` | No header, date or attendees (it says so itself). Two items: `Sam to chase the vendor`, `Priya to send the slides by Friday`. Cannot be dated. |
| `2026-09-19-offsite-draft.txt` | `.txt` extension and self-described "Not a meeting note". One checkbox with no owner. |
| `2026-10-02-finance-sync.md` | CRLF line endings, plus `[X]`, `*`, `+` bullets and an em-dash. Parseable but needs normalising. |
| `2026-10-03-sales-pipeline.md` | Date is `sometime last week`. No Discussion section. |
| `2026-09-23-standup.md` | No Attendees line, so first-name owners cannot be matched to anyone. |
| `2026-09-16-standup.md`, `2026-09-30-standup.md` | Valid, but YAML front matter instead of `# Meeting:` header. |
| `2026-09-30-q4-offsite.md` | No `## Action items` section. Actions are scattered across a morning and afternoon section in 5 different syntaxes (checkbox with 3 bullet types, nested, `ACTION:`, table). 9 attendees. |
| `2026-09-18-design-review.md` | Free-form brain dump with joint, group, unassigned and @handle owners. |
| `2026-09-21-incident-review.md`, `2026-10-09-security-review.md` | Contain quoted, fenced and commented-out "actions" that must be excluded. |
| `2026-09-09-qa-standup.md`, `2026-09-14-onboarding-flow-design.md` | Non-ISO header dates (valid, just different format). |

## 5. Duplicates and same-first-name ambiguity

**Same first name, two people:** Priya Nair vs Priya Shah, and Rahul Mehta vs Rahul Verma. They tend to cluster by project:
- Nair / Mehta: quote portal, kickoff, design review, Acme renewal (Nair only).
- Shah / Verma: billing, QA, onboarding, incident and security reviews.
- Resolvable by attendance when only one with that first name attended (e.g. 09-03 billing, 10-09 security, 09-18 design review).
- Ambiguous when both attended or attendance is missing:

| File | Line | Why ambiguous |
|---|---|---|
| 2026-09-17-billing-migration-sync | `Priya to sign off the cutover checklist by Monday` | both Priyas present (Rahul resolves to Verma) |
| 2026-10-08-billing-go-no-go | `Priya to circulate the go/no-go summary by EOD` | both Priyas present (same note has explicit `Priya N.`) |
| 2026-09-30-q4-offsite | `Priya to own the hiring plan...`, `Rahul to prepare the architecture overview by Friday` | all 9 present; prose even says "it is unclear which Rahul meant" |
| 2026-10-07-standup | `Rahul to review Anita's PR by tomorrow` | both Rahuls present |
| 2026-09-23-standup | `Rahul to rebase the feature branch by Thursday` | no attendees listed |
| 2026-09-29-billing-cutover-planning | `Priya S.`, `Priya N.` | explicitly disambiguated (the model case) |

**Duplicate / carried-over items.** The same task reappears across meetings with changed wording, due date or checkbox state:

| Task | Appearances |
|---|---|
| Send revised quote to Acme (Priya) | 09-01 (by Friday), 09-08 (`Priya N.`, by Friday), 09-15 `[x]` |
| Confirm cloud budget with finance (Sam) | 09-01, 09-15 (by Friday), 09-22 `[x]` |
| Share wireframes (Anita) | 09-01 (first), 09-15 (updated, by Thursday), 09-22 (updated, by Thursday, still open) |
| Set up staging environment (Rahul) | 09-01 (by 2026-09-08), 09-08 `[x]` |
| Deploy beta to staging (Rahul) | 10-01 (by Friday), 10-06 (by tomorrow), 10-13 `[x]` |
| Book renewal call with Acme's CTO (Meera) | 09-10, 09-28 (by Wednesday), 10-14 `[x]` |
| Export last quarter invoices (Karan) | 09-03 (by 10 Sep), 09-17 `[x]` (no due) |
| Review schema mapping doc (Rahul) | 09-03 (by Monday), 09-17 (no due), never closed |
| Notify customers re maintenance window (Priya N.) | 09-29 (by 2026-10-05), 10-08 `[x]` |
| Freeze invoice edits from 9 Oct (Karan) | 09-29 and 10-08, identical, open both times |
| Welcome-email copy (Anita) | 09-14 (by Wed 16 Sep), 09-24 (by Friday), 10-05 `[x]` |
| SSO estimate / spike (Rahul) | 09-14 (estimate), 09-24 (by Monday), 10-05 (`start SSO spike by next Tuesday`) |
| Customer quotes for landing page (Lena) | 09-14 (end of month), 09-24 (by 2 Oct), 10-05 (`publish ... by 9 Oct`) |
| Usage report (Lena) | 09-10 (`pull`, by tomorrow), 09-28 (`share with Meera`) |
| Approve Q4 cloud spend (Karan) | 09-30 standup (by 2026-10-02), 10-02 `[X]` |
| Acme renewal one-pager (Priya) | 09-28 (by Friday), 10-14 (no due, still open) |
| Refund affected customers (Karan) | twice in 09-21: the quoted line (`by Friday`) and the real line (no due) |

Other duplication traps: two files per date on 09-09 and 09-30; the 09-09 empty file may have been a copy of the standup.

## 6. Questions for you

1. **SCENARIO.md is empty (0 bytes).** Was it saved before you asked? Please re-save or paste it. Several answers below depend on what the scenario actually requires.
2. **What counts as an action item?** I'd exclude quoted, fenced and commented-out lines and non-meeting files, and include `ACTION:` lines and table rows. Should prose commitments in Discussion (`Priya offered to help recruit`) count?
3. **Same-first-name cases:** when both people attended or attendance is missing, should I (a) leave the owner as ambiguous and flag it, (b) infer by project cluster, or (c) pick one?
4. **Group or unassigned owners** (`Everyone`, `Team`, `TBD`, `Someone`): keep as "unowned", or fan out to every attendee?
5. **Joint owners** (`Anita & Rahul`, `Lena (with Priya)`): one item with several owners, one per person, or only the lead?
6. **Due-date rules:** resolve weekdays and day-month dates relative to the meeting date, assuming 2026? What about `end of next week`, `mid-October`, `before cutover`? Should `from 9 Oct`, `for Saturday 10 Oct` and `on 2026-10-14` be treated as non-deadlines?
7. **Duplicates:** should the same task across meetings collapse into one item (latest status wins, e.g. `[x]` closes the earlier open ones), or stay as separate records? When the wording or due date drifts, which wins?
8. **Status:** `[x]`/`[X]` mean done as of that meeting date. What status should `ACTION:` lines, table rows and checkbox lines in non-meeting files get?
9. **Malformed files:** skip `scratch.md` and the empty file, report `untitled.md` and the `.txt` as unparseable, and use the filename date for `sometime last week`? Or do you want something different?
10. **Odd dates:** is it expected that two notes (2026-10-03, 2026-10-10) fall on a Saturday, and that `sometime last week` is dated by filename?
11. **Open vs stale:** some items are never closed after repeated carry-over (wireframes, one-pager, schema review, freeze invoice edits). Should these be flagged as stale/overdue?
12. **Output conventions:** one date format (ISO?), and are completed items included in the final output?

## 7. Working decisions (simplest defaults, change any you disagree with)

1. **SCENARIO.md:** still empty. Proceed on the data alone and revisit if the scenario is supplied.
2. **What counts:** checkbox lines (`-`, `*`, `+`, any case of x, nested), `ACTION:` lines and table rows, found anywhere in the file. Exclude block-quoted, fenced and HTML-commented lines, and non-meeting files. Ignore prose commitments in Discussion.
3. **Same first name:** resolve from the attendee list when only one person with that first name attended, or from an explicit initial (`Priya N.`). Otherwise set the owner to `Ambiguous (Priya)` and flag it. Never guess.
4. **Group or unassigned owners** (`Everyone`, `Team`, `TBD`, `Someone`): one item with owner `Unassigned`, keeping the original text in a note field.
5. **Joint owners:** one item, primary owner is the first name listed, others recorded as collaborators.
6. **Due dates:** resolve against the meeting date, assuming 2026. A weekday means the next such day after the meeting. Use `end of next week` = Friday of the following week, `end of month` = last day of that month, `mid-October` = 2026-10-15, and `EOD` = same day. `from`, `for` and `on` dates and `before cutover` are not deadlines, so leave due empty and keep the text. If nothing parses, leave due empty.
7. **Duplicates:** collapse repeats into one item, matched by owner plus similar task text. The latest due date and status win (a later `[x]` closes it), and all source files are recorded. (Revised after reading SCENARIO.md.)
8. **Status:** `[x]`/`[X]` = done. Everything else, including `ACTION:` lines and table rows, = open.
9. **Malformed files:** skip `scratch.md` and the empty file with a warning. Parse `untitled.md` with no date and flag it. Skip the `.txt`. For `sometime last week`, use the filename date and flag it. Strip CRLF.
10. **Saturday dates:** accept as written, no correction.
11. **Overdue:** an open item whose due date is before today. Use the system date, with a `--today` override for reproducible runs. (Revised after reading SCENARIO.md.)
12. **Output:** ISO dates (`YYYY-MM-DD`), completed items included with their status.
13. **Owner filters:** `--owner` and `followup` take a full name. A bare ambiguous first name (`Priya`) matches both people and prints a warning.
14. **Follow-up drafts:** the notes contain no email addresses, so leave "To" blank or use an owner-to-email mapping file. Drafts only, never sent. The Gmail connector must be authorized first.
15. **SCENARIO.md is truncated** (lines 14, 17, 19, 22 and 24 cut off mid-sentence). Re-save it and recheck these decisions against the full text.
