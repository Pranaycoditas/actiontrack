Scenario


Your team's meeting notes pile up as markdown files. Action items get lost, and follow-up emails are written late or not at all. You will build a small CLI tool, actiontrack, that reads meeting notes, tracks the action items, and drafts follow-up emails for review.


What you build


A CLI with four commands:


1. actiontrack ingest <folder> parses every .md meeting note in the folder. Each note has
   a date, attendees and free- appear as lines like - [ ]Priya to send the revised quote by Friday. The tool stores them with owner, task, due
   date (resolved to a real daurce file and status.
2. actiontrack list shows items. Filters: --owner, --status open|done|overdue,
   --due-before <date>. Overdu
3. actiontrack done <id> marks an item as done.
4. actiontrack followup <ownerper owner covering their openand overdue items, and creates a Gmail draft through the Gmail MCP connector. It never sends.


Edge cases the tool must handl
Duplicate items repeated across several meetings.
Items with no owner or no da
Two people with the same first name.
Malformed notes (skip them and report, don't crash).
A sample notes/ folder with 30+ files is provided. Several are long and messy, and a few are deliberately malformed.