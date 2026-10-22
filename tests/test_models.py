import dataclasses
from datetime import date

import pytest

from actiontrack.models import Header, Item, Mention, Note


def _mention(**kw) -> Mention:
    base = dict(
        file="f.md",
        line_no=1,
        syntax="checkbox",
        raw_line="- [ ] Sam to x",
        owner_raw="Sam",
        owner="Sam Okafor",
        owner_kind="person",
        collaborators=[],
        task="x",
        task_key="x",
        due=None,
        due_raw=None,
        checked=False,
    )
    base.update(kw)
    return Mention(**base)


def test_mention_defaults_and_frozen():
    m = _mention()
    assert m.meeting_date is None
    assert m.item_id is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.owner = "x"  # type: ignore[misc]


def test_mention_item_id_is_link_not_identity_field_name_stable():
    m = _mention(item_id="b48cced6", meeting_date=date(2026, 9, 1))
    assert dataclasses.replace(m, item_id=None).item_id is None
    names = [f.name for f in dataclasses.fields(Mention)]
    for required in ("file", "line_no", "owner", "owner_kind", "task_key", "due", "checked"):
        assert required in names


def test_note_content_hash_defaults_empty():
    n = Note(file="f.md", header=Header(None, None, None, "none"))
    assert n.content_hash == ""
    assert dataclasses.replace(n, content_hash="abc").content_hash == "abc"


def test_item_fields_match_items_table():
    names = [f.name for f in dataclasses.fields(Item)]
    assert names == [
        "id",
        "id_key",
        "owner",
        "owner_kind",
        "collaborators",
        "task",
        "due",
        "due_raw",
        "status",
        "done_manual",
        "first_file",
        "latest_file",
        "mention_count",
    ]
