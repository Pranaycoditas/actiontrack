"""The 'drafts only, never send' rule is stated in CLAUDE.md, SPEC.md and GMAIL_FLOW.md."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
RULE = "drafts only, never send"


@pytest.mark.parametrize("rel", ["CLAUDE.md", "docs/SPEC.md", "docs/GMAIL_FLOW.md"])
def test_rule_is_stated(rel):
    assert RULE in (ROOT / rel).read_text(encoding="utf-8").lower()


def test_claude_md_and_spec_point_to_flow_doc():
    for rel in ("CLAUDE.md", "docs/SPEC.md"):
        assert "docs/GMAIL_FLOW.md" in (ROOT / rel).read_text(encoding="utf-8")


def test_flow_doc_covers_the_steps():
    text = (ROOT / "docs" / "GMAIL_FLOW.md").read_text(encoding="utf-8")
    for needle in (
        "ingest",
        "--dry-run",
        "--email-map",
        "owner,email",
        "--all",
        "--out",
        "get_mcp_client",
        "DRAFT_TOOL",
        "create_draft",
        "Gmail Drafts",
        "SinkUnavailable",
    ):
        assert needle in text, needle


def test_spec_documents_email_map_format():
    text = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    assert "owner,email" in text and "Missing address is never an error" in text
