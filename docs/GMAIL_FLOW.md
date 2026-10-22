# Gmail flow: creating follow-up drafts

## The rule: drafts only, never send

actiontrack **creates Gmail drafts. It never sends email.** This rule is binding and is stated in `CLAUDE.md`, `docs/SPEC.md` and here.

- The only Gmail action the code can take is creating a draft. `DraftSink` has one method, `create_draft`, and `GmailMcpSink` allow-lists exactly one connector tool (`DRAFT_TOOL` in `src/actiontrack/drafts.py`).
- The payload has exactly three keys: `to`, `subject`, `body`. There is no send, schedule or reply key.
- `tests/test_no_send.py` fails the build if any send call name appears in `src/`.
- A human reviews each draft in Gmail and sends it, or deletes it, by hand. Nothing in this repository does that step.

If a change would add a send call, stop. That is out of scope and against the rules.

## Steps

### 1. Ingest the notes

```
actiontrack ingest notes/
```

Items are stored in SQLite (`./actiontrack.db`, or `--db PATH`, or `ACTIONTRACK_DB`). `followup` never creates a database. Without one it exits 2 and asks you to run ingest.

### 2. Preview without touching Gmail

Preview one owner, or everyone, before creating anything:

```
actiontrack followup "Anita Desai" --dry-run --today 2026-10-22
actiontrack followup --all --out drafts/ --today 2026-10-22
```

- `--dry-run` prints the email and creates nothing.
- `--out FOLDER` writes one file per owner (`anita-desai.txt`) and creates no Gmail draft.
- `--today YYYY-MM-DD` fixes the date used for the overdue check, so output is reproducible.

### 3. Add email addresses (optional)

The notes contain no addresses, so `To` is blank unless you supply a map. Create a CSV with this header:

```
owner,email
Anita Desai,anita@example.com
Priya Nair,priya.nair@example.com
Priya Shah,priya.shah@example.com
```

Pass it with `--email-map people.csv`.

- Use full names. `Priya` alone matches nobody, because there are two Priyas.
- `name` is accepted instead of `owner` in the header.
- A missing or blank address is never an error. The draft is still created, with `To` blank, and the run continues.
- With `--all`, owners without an address are listed in the summary (`No email address for N owners: ...`).
- A file that cannot be read, or whose header lacks `owner` and `email`, exits 2 before anything is created.

### 4. Authorize the Gmail connector

Drafts go through the Gmail MCP connector, which must be authorized first:

- Claude Code (interactive): run `/mcp`, or `claude mcp` in a terminal, and authorize the Gmail server.
- claude.ai: authorize Gmail in the connector settings.

Until it is authorized, a run that needs Gmail exits 1 with `SinkUnavailable` and creates nothing.

### 5. Wire the connector into the CLI (one-time developer step)

**Status: not done in this repository.** `get_mcp_client()` in `src/actiontrack/cli.py` currently raises `SinkUnavailable`, so a real Gmail run always stops there with exit 1. `--dry-run` and `--out` do not need it.

To finish the wiring:

1. Make `get_mcp_client()` return a callable `call_tool(name: str, args: dict) -> dict` that forwards to the authorized Gmail MCP server.
2. Confirm the connector's draft-creation tool name and set `DRAFT_TOOL` in `src/actiontrack/drafts.py` to it. The current value, `create_draft`, is a placeholder that has **not** been checked against the real connector. `ALLOWED_TOOLS` is derived from it, so it stays the only callable tool.
3. The reply must carry the draft id under `draft_id`, `id` or `draftId`. Without one, the run fails with `DraftError`, because the draft may not exist.
4. Re-run `pytest`. The no-send tests must still pass.

### 6. Create the drafts

```
actiontrack followup "Anita Desai" --email-map people.csv
actiontrack followup --all --email-map people.csv
```

- One draft per owner, with overdue items first and then open ones.
- `--all` covers every owner with open or overdue items. Ambiguous owners (`Ambiguous (Priya)`) and `Unassigned` items are skipped and listed in the summary. They have no one to email.
- Each result line prints as it completes, ending with `Draft id: ... (review it in Gmail Drafts; nothing was sent)`.
- Running again creates **another** draft. There is no de-duplication (SPEC D14). Delete extras in Gmail.

### 7. Review in Gmail

Open **Gmail Drafts**, check each draft and the recipient, then send or delete it by hand in Gmail.

## Failures

| What happens | Exit | Notes |
|---|---|---|
| Connector missing or not authorized (`SinkUnavailable`) | 1 | No draft is created. Authorize it (step 4), then run again. |
| Gmail rejects a draft (`DraftError`) | 1 | No retry, because a retry could create a duplicate. With `--all` the run stops there. Owners already done keep their drafts, and the error names the owner that failed. |
| Connector reply has no draft id | 1 | Check in Gmail Drafts whether the draft exists before running again. |
| Unknown owner, bare `Priya` or `Rahul`, `Unassigned`, `--all` plus an owner, neither an owner nor `--all`, `--out` plus `--dry-run` | 2 | Nothing is created. |
| Bad `--email-map` | 2 | Nothing is created. |
| Owner has no address | 0 | `To` is blank. Fill it in Gmail, or add the owner to the map and run again. |

## Payload

Exactly one connector call per draft:

```
tool: DRAFT_TOOL            # "create_draft" until confirmed (step 5)
args: {"to": "<address or empty>", "subject": "...", "body": "..."}
```

The subject and body layout is in SPEC section 7.2.
