"""Dedupe and ID tests (TEST_PLAN section 5, DD01-DD39)."""

from __future__ import annotations

import hashlib
import random
import re
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from actiontrack import dedupe
from actiontrack.dates import resolve_due
from actiontrack.dedupe import (
    group_mentions,
    item_id,
    make_item,
    match_key,
    similarity,
    task_key,
)
from actiontrack.models import Mention, Note, Skip
from actiontrack.owners import build_roster, resolve_owner
from actiontrack.parser import parse_note
from actiontrack.reader import read_folder

NOTES = Path(__file__).resolve().parent.parent / "notes"


# --------------------------------------------------------------------------- helpers


def mk(
    owner: str,
    task: str,
    file: str = "2026-09-01-a.md",
    meeting: date | None = date(2026, 9, 1),
    *,
    checked: bool = False,
    due: date | None = None,
    due_raw: str | None = None,
    collaborators: list[str] | None = None,
    line_no: int = 1,
) -> Mention:
    if owner == "Unassigned":
        kind = "unassigned"
    elif owner.startswith("Ambiguous ("):
        kind = "ambiguous"
    else:
        kind = "person"
    return Mention(
        file=file,
        line_no=line_no,
        syntax="checkbox",
        raw_line=f"- [ ] {task}",
        owner_raw=owner,
        owner=owner,
        owner_kind=kind,  # type: ignore[arg-type]
        collaborators=collaborators or [],
        task=task,
        task_key=task_key(task),
        due=due,
        due_raw=due_raw,
        checked=checked,
        meeting_date=meeting,
    )


def items_of(mentions: list[Mention]) -> list:
    taken: set[str] = set()
    out = []
    for g in group_mentions(mentions):
        item = make_item(g, taken)
        taken.add(item.id)
        out.append(item)
    return out


def snapshot(mentions: list[Mention]) -> list:
    taken: set[str] = set()
    snap = []
    for g in group_mentions(mentions):
        item = make_item(g, taken)
        taken.add(item.id)
        snap.append((item, [(m.file, m.line_no) for m in g.mentions]))
    return snap


# --------------------------------------------------------------------------- real notes


def build_real_mentions(folder: Path = NOTES, exclude: set[str] | None = None) -> list[Mention]:
    """Test-only glue: reader + parser + owners + dates, as ingest will do."""
    notes: list[Note] = []
    for entry in read_folder(folder):
        if isinstance(entry, Skip):
            continue
        parsed = parse_note(entry)
        if isinstance(parsed, Skip):
            continue
        if exclude and parsed.file in exclude:
            continue
        notes.append(parsed)
    roster = build_roster([n.header.attendees for n in notes])
    out: list[Mention] = []
    for note in notes:
        for line in note.lines:
            res = resolve_owner(line.owner_text, note.header.attendees, roster)
            due = resolve_due(line.due_text, note.header.date)
            out.append(
                Mention(
                    file=note.file,
                    line_no=line.line_no,
                    syntax=line.syntax,
                    raw_line=line.raw_line,
                    owner_raw=line.owner_text,
                    owner=res.owner,
                    owner_kind=res.kind,
                    collaborators=list(res.collaborators),
                    task=line.task_text,
                    task_key=task_key(line.task_text),
                    due=due.due,
                    due_raw=due.raw,
                    checked=line.checked,
                    meeting_date=note.header.date,
                )
            )
    return out


@pytest.fixture(scope="module")
def real() -> list[Mention]:
    return build_real_mentions()


def real_items(real: list[Mention], owner_prefix: str, needle: str):
    """Items whose group has a mention of `owner_prefix*` with `needle` in the task."""
    out = []
    taken: set[str] = set()
    for g in group_mentions(real):
        item = make_item(g, taken)
        taken.add(item.id)
        if g.owner.startswith(owner_prefix) and any(needle in m.task.lower() for m in g.mentions):
            out.append((item, g))
    return out


# --------------------------------------------------------------------------- task_key / similarity


def test_dd19_task_key_example() -> None:
    assert task_key("send the revised quote to Acme") == "send revised quote acme"


def test_dd18_stopwords_and_punctuation() -> None:
    a = task_key("Send the revised quote to Acme!")
    b = task_key("send revised quote Acme")
    assert a == b
    assert similarity(a, b) == 1.0


def test_task_key_strips_punctuation_to_spaces() -> None:
    assert task_key("Re-send  invoice/quote (v2)") == "re send invoice quote v2"


def test_dd15_disjoint_is_zero() -> None:
    a = task_key("export last quarter invoices")
    b = task_key("review schema mapping doc")
    assert similarity(a, b) == 0.0
    owner = "Karan Joshi"
    assert len(items_of([mk(owner, a), mk(owner, b, "2026-09-02-b.md", date(2026, 9, 2))])) == 2


def test_dd16_share_wireframes() -> None:
    assert similarity("share wireframes", "share updated wireframes") == pytest.approx(2 / 3)
    owner = "Anita Desai"
    ms = [
        mk(owner, "share wireframes"),
        mk(owner, "share updated wireframes", "2026-09-15-b.md", date(2026, 9, 15)),
    ]
    assert len(items_of(ms)) == 1


def test_dd17_threshold_exact_and_below() -> None:
    exact = similarity("p q r s", "p q r t")  # 3 / 5
    assert exact == 0.6
    below = similarity("p q r s t", "p q r s u v")  # 4 / 7 = 0.571
    assert below < 0.6
    o = "Sam Okafor"
    d2 = date(2026, 9, 2)
    assert len(items_of([mk(o, "p q r s"), mk(o, "p q r t", "2026-09-02-b.md", d2)])) == 1
    assert len(items_of([mk(o, "p q r s t"), mk(o, "p q r s u v", "2026-09-02-b.md", d2)])) == 2


def test_similarity_empty_sets() -> None:
    assert similarity("", "") == 1.0
    assert similarity("", "a") == 0.0


# --------------------------------------------------------------------------- owner rules


def test_dd11_ambiguous_never_merges_into_resolved() -> None:
    d2 = date(2026, 9, 2)
    ms = [
        mk("Ambiguous (Priya)", "send revised quote acme"),
        mk("Priya Nair", "send revised quote acme", "2026-09-02-b.md", d2),
    ]
    assert len(items_of(ms)) == 2


def test_ambiguous_same_first_name_merges() -> None:
    d2 = date(2026, 9, 2)
    ms = [
        mk("Ambiguous (Priya)", "sign off cutover checklist"),
        mk("Ambiguous (Priya)", "sign off cutover checklist", "2026-09-02-b.md", d2),
        mk("Ambiguous (Rahul)", "sign off cutover checklist", "2026-09-02-b.md", d2, line_no=2),
    ]
    items = items_of(ms)
    assert len(items) == 2
    assert {i.owner for i in items} == {"Ambiguous (Priya)", "Ambiguous (Rahul)"}


def test_dd12_priya_nair_vs_shah() -> None:
    ms = [mk("Priya Nair", "send slides"), mk("Priya Shah", "send slides")]
    assert len(items_of(ms)) == 2


def test_dd13_different_owners_same_text() -> None:
    ms = [mk("Sam Okafor", "chase vendor"), mk("Karan Joshi", "chase vendor")]
    items = items_of(ms)
    assert len(items) == 2
    assert items[0].id != items[1].id


def test_dd14_unassigned_merge() -> None:
    ms = [
        mk("Unassigned", "book the venue"),
        mk("Unassigned", "book the venue", "2026-09-02-b.md", date(2026, 9, 2)),
    ]
    items = items_of(ms)
    assert len(items) == 1
    assert items[0].owner_kind == "unassigned"


# --------------------------------------------------------------------------- match key (D24)


def test_dd40_match_key_drops_qualifiers() -> None:
    a = match_key(task_key("share first wireframes"))
    assert a == match_key(task_key("share updated wireframes")) == "share wireframes"
    assert similarity(match_key("start sso spike"), match_key("estimate sso")) == 1.0


def test_dd40_match_key_never_empties() -> None:
    assert match_key("start") == "start"
    assert match_key("") == ""


def test_dd40_task_key_unchanged_by_match_key() -> None:
    """IDs hash task_key, so the loose match key must not leak into it."""
    assert task_key("Share first wireframes") == "share first wireframes"


def test_dd40_qualifier_drift_merges() -> None:
    d2 = date(2026, 9, 2)
    ms = [
        mk("Anita Desai", "share first wireframes"),
        mk("Anita Desai", "share updated wireframes", "2026-09-02-b.md", d2),
    ]
    (item,) = items_of(ms)
    assert item.task == "share updated wireframes"
    assert item.mention_count == 2


def test_dd40_spike_and_estimate_merge() -> None:
    ms = [
        mk("Rahul Verma", "estimate the SSO work"),
        mk("Rahul Verma", "start SSO spike", "2026-09-02-b.md", date(2026, 9, 2)),
    ]
    assert len(items_of(ms)) == 1


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Priya Nair", "Priya Shah"),
        ("Rahul Mehta", "Rahul Verma"),
        ("Anita Desai", "Sam Okafor"),
        ("Priya Nair", "Ambiguous (Priya)"),
        ("Rahul Verma", "Unassigned"),
    ],
)
def test_dd40_loose_match_never_crosses_owners(a: str, b: str) -> None:
    d2 = date(2026, 9, 2)
    ms = [
        mk(a, "share first wireframes"),
        mk(b, "share updated wireframes", "2026-09-02-b.md", d2),
        mk(a, "estimate sso work", line_no=2),
        mk(b, "start sso spike", "2026-09-02-b.md", d2, line_no=2),
    ]
    items = items_of(ms)
    assert len(items) == 4
    for g in group_mentions(ms):
        assert len({(m.owner, m.owner_kind) for m in g.mentions}) == 1


def test_dd40_loose_match_keeps_distinct_steps_apart() -> None:
    o = "Meera Iyer"
    d2 = date(2026, 9, 2)
    assert (
        len(items_of([mk(o, "chase orbit labs"), mk(o, "send proposal orbit labs", "b.md", d2)]))
        == 2
    )


# --------------------------------------------------------------------------- merged fields


def test_dd20_later_open_reopens() -> None:
    ms = [
        mk("Sam Okafor", "ship report", "2026-09-17-a.md", date(2026, 9, 17), checked=True),
        mk("Sam Okafor", "ship report", "2026-10-01-a.md", date(2026, 10, 1), checked=False),
    ]
    (item,) = items_of(ms)
    assert item.status == "open"
    assert item.done_manual is False


def test_later_checked_closes() -> None:
    ms = [
        mk("Sam Okafor", "ship report", "2026-09-17-a.md", date(2026, 9, 17)),
        mk("Sam Okafor", "ship report", "2026-10-01-a.md", date(2026, 10, 1), checked=True),
    ]
    (item,) = items_of(ms)
    assert item.status == "done"


def test_dd21_latest_non_empty_due() -> None:
    mid = date(2026, 9, 11)
    ms = [
        mk(
            "Sam Okafor",
            "ship report",
            "2026-09-01-a.md",
            date(2026, 9, 1),
            due=date(2026, 9, 4),
            due_raw="by Friday",
        ),
        mk(
            "Sam Okafor",
            "ship report",
            "2026-09-08-a.md",
            date(2026, 9, 8),
            due=mid,
            due_raw="by Friday",
        ),
        mk("Sam Okafor", "ship report", "2026-09-15-a.md", date(2026, 9, 15), checked=True),
    ]
    (item,) = items_of(ms)
    assert item.due == mid
    assert item.due_raw == "by Friday"


def test_due_raw_when_no_due_from_latest_with_raw() -> None:
    ms = [
        mk(
            "Karan Joshi",
            "freeze invoice edits",
            "2026-09-29-a.md",
            date(2026, 9, 29),
            due_raw="from 9 Oct",
        ),
        mk("Karan Joshi", "freeze invoice edits", "2026-10-08-a.md", date(2026, 10, 8)),
    ]
    (item,) = items_of(ms)
    assert item.due is None
    assert item.due_raw == "from 9 Oct"


def test_dd22_task_twice_in_one_note() -> None:
    ms = [
        mk("Sam Okafor", "chase vendor", line_no=3),
        mk("Sam Okafor", "chase vendor", line_no=9),
    ]
    groups = group_mentions(ms)
    assert len(groups) == 1
    assert len(groups[0].mentions) == 2
    (item,) = items_of(ms)
    assert item.mention_count == 2
    assert item.first_file == item.latest_file


def test_collaborators_from_latest_mention_that_has_any() -> None:
    ms = [
        mk(
            "Anita Desai",
            "agree plan",
            "2026-09-01-a.md",
            date(2026, 9, 1),
            collaborators=["Rahul Mehta"],
        ),
        mk(
            "Anita Desai",
            "agree plan",
            "2026-09-08-a.md",
            date(2026, 9, 8),
            collaborators=["Lena Park"],
        ),
        mk("Anita Desai", "agree plan", "2026-09-15-a.md", date(2026, 9, 15)),
    ]
    (item,) = items_of(ms)
    assert item.collaborators == ["Lena Park"]


def test_task_wording_and_files_of_latest() -> None:
    ms = [
        mk("Anita Desai", "share wireframes", "2026-09-01-a.md", date(2026, 9, 1)),
        mk("Anita Desai", "share updated wireframes", "2026-09-22-b.md", date(2026, 9, 22)),
    ]
    (item,) = items_of(ms)
    assert item.task == "share updated wireframes"
    assert item.first_file == "2026-09-01-a.md"
    assert item.latest_file == "2026-09-22-b.md"
    assert item.mention_count == 2


def test_undated_sorts_first() -> None:
    ms = [
        mk("Sam Okafor", "chase vendor", "2026-09-01-a.md", date(2026, 9, 1), checked=True),
        mk("Sam Okafor", "chase vendor", "untitled.md", None),
    ]
    (g,) = group_mentions(ms)
    assert [m.file for m in g.mentions] == ["untitled.md", "2026-09-01-a.md"]
    (item,) = items_of(ms)
    assert item.first_file == "untitled.md"
    assert item.status == "done"


def test_best_scoring_group_wins() -> None:
    o = "Sam Okafor"
    d = [date(2026, 9, i) for i in (1, 2, 3)]
    ms = [
        mk(o, "p q r s t", "f1.md", d[0]),
        mk(o, "p q r s u v", "f2.md", d[1]),  # 4/7 to g1: below threshold, new group
        mk(o, "p q r s u", "f3.md", d[2]),  # 4/6 to g1, 5/6 to g2 -> g2 wins
    ]
    groups = group_mentions(ms)
    assert [[m.file for m in g.mentions] for g in groups] == [["f1.md"], ["f2.md", "f3.md"]]


def test_exact_tie_goes_to_first_created() -> None:
    o = "Sam Okafor"
    ms = [
        mk(o, "p q r s", "f1.md", date(2026, 9, 1)),
        mk(o, "p q x y", "f2.md", date(2026, 9, 2)),  # 2/6 to g1: new group
        mk(o, "p q r x", "f3.md", date(2026, 9, 3)),  # 0.6 to both -> g1
    ]
    groups = group_mentions(ms)
    assert [[m.file for m in g.mentions] for g in groups] == [["f1.md", "f3.md"], ["f2.md"]]


# --------------------------------------------------------------------------- IDs


def test_dd30_known_id_sam() -> None:
    expected = hashlib.sha1(b"Sam Okafor|confirm cloud budget finance").hexdigest()[:8]
    assert expected == "b48cced6"
    assert item_id("Sam Okafor", "confirm cloud budget finance", set()) == (
        "b48cced6",
        "Sam Okafor|confirm cloud budget finance",
    )


def test_dd31_known_id_priya() -> None:
    assert item_id("Priya Nair", "send revised quote acme", set())[0] == "cfc90787"


def test_dd37_forced_collision_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    id1, key1 = item_id("Sam Okafor", "alpha", set())
    # Pretend a different key already owns this id: second call gets '#2'.
    id2, key2 = item_id("Sam Okafor", "alpha", {id1})
    assert key1 == "Sam Okafor|alpha"
    assert key2 == "Sam Okafor|alpha#2"
    assert id2 != id1
    assert id2 == hashlib.sha1(key2.encode()).hexdigest()[:8]
    id3, key3 = item_id("Sam Okafor", "alpha", {id1, id2})
    assert key3 == "Sam Okafor|alpha#3"
    assert id3 not in {id1, id2}
    # deterministic
    assert item_id("Sam Okafor", "alpha", {id1}) == (id2, key2)

    # Truly colliding hashes: patch the hash so two different keys share a prefix.
    real_hash = dedupe._hash8
    monkeypatch.setattr(dedupe, "_hash8", lambda k: "deadbeef" if "#" not in k else real_hash(k))
    a = item_id("Sam Okafor", "one", set())
    b = item_id("Sam Okafor", "two", {a[0]})
    assert a[0] == "deadbeef"
    assert b[1] == "Sam Okafor|two#2"
    assert b[0] != a[0]


def test_dd37_collision_between_groups() -> None:
    ms = [mk("Sam Okafor", "alpha"), mk("Sam Okafor", "beta", "2026-09-02-b.md", date(2026, 9, 2))]
    ids = {i.id for i in items_of(ms)}
    assert len(ids) == 2


def _base_mentions() -> list[Mention]:
    return [
        mk("Anita Desai", "share wireframes", "2026-09-15-a.md", date(2026, 9, 15)),
        mk("Anita Desai", "share the updated wireframes", "2026-09-22-a.md", date(2026, 9, 22)),
    ]


def test_dd33_wording_drift_keeps_id() -> None:
    before = items_of(_base_mentions()[:1])[0]
    after = items_of(_base_mentions())[0]
    assert after.task == "share the updated wireframes"
    assert before.id == after.id


def test_dd34_due_and_checkbox_change_keeps_id() -> None:
    ms = _base_mentions()
    changed = [
        ms[0],
        replace(ms[1], checked=True, due=date(2026, 9, 24), due_raw="by Thursday"),
    ]
    a, b = items_of(ms)[0], items_of(changed)[0]
    assert a.id == b.id
    assert (a.status, b.status) == ("open", "done")


def test_dd38_earlier_note_added_changes_id() -> None:
    """Documents the D9 limit: a new earlier-dated note moves the anchor."""
    ms = _base_mentions()
    earlier = mk("Anita Desai", "share wireframes now", "2026-09-01-a.md", date(2026, 9, 1))
    before = items_of(ms)[0]
    after = items_of([earlier, *ms])
    assert len(after) == 1
    assert after[0].id != before.id
    assert after[0].first_file == "2026-09-01-a.md"


def test_dd39_id_independent_of_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    ms = _base_mentions()
    monkeypatch.setattr(time, "time", lambda: 1_000.0)
    first = snapshot(ms)
    monkeypatch.setattr(time, "time", lambda: 9_999_999_999.0)
    second = snapshot(ms)
    assert first == second
    source = Path(dedupe.__file__).read_text()
    assert not re.search(r"\.(today|now|utcnow)\(|\btime\.time\(|import (time|datetime)", source)


def test_dd32_order_independent_100_shuffles() -> None:
    o = "Sam Okafor"
    ms = [
        mk(o, "confirm cloud budget with finance", "2026-09-01-a.md", date(2026, 9, 1)),
        mk(
            o,
            "confirm cloud budget with finance",
            "2026-09-15-a.md",
            date(2026, 9, 15),
            due=date(2026, 9, 18),
            due_raw="by Friday",
        ),
        mk(
            o,
            "confirm cloud budget with finance",
            "2026-09-22-a.md",
            date(2026, 9, 22),
            checked=True,
        ),
        mk(
            "Priya Nair",
            "send revised quote to Acme",
            "2026-09-01-a.md",
            date(2026, 9, 1),
            line_no=2,
        ),
        mk("Priya Nair", "send revised quote to Acme", "2026-09-08-a.md", date(2026, 9, 8)),
        mk(
            "Priya Shah",
            "send revised quote to Acme",
            "2026-09-08-a.md",
            date(2026, 9, 8),
            line_no=4,
        ),
        mk("Unassigned", "book venue", "2026-09-01-a.md", date(2026, 9, 1), line_no=5),
        mk("Unassigned", "book venue", "untitled.md", None),
        mk("Ambiguous (Priya)", "sign off checklist", "2026-09-17-a.md", date(2026, 9, 17)),
        mk(o, "p q r s", "2026-09-02-b.md", date(2026, 9, 2), line_no=7),
        mk(o, "p q x y", "2026-09-03-b.md", date(2026, 9, 3), line_no=7),
        mk(o, "p q r x", "2026-09-04-b.md", date(2026, 9, 4), line_no=7),
    ]
    expected = snapshot(ms)
    rng = random.Random(1234)
    for _ in range(100):
        shuffled = ms[:]
        rng.shuffle(shuffled)
        assert snapshot(shuffled) == expected


def test_group_exposes_mentions_in_order() -> None:
    ms = [
        mk("Sam Okafor", "chase vendor", "2026-09-08-a.md", date(2026, 9, 8)),
        mk("Sam Okafor", "chase vendor", "2026-09-01-a.md", date(2026, 9, 1)),
    ]
    (g,) = group_mentions(ms)
    assert [m.file for m in g.mentions] == ["2026-09-01-a.md", "2026-09-08-a.md"]
    assert g.owner == "Sam Okafor"


# --------------------------------------------------------------------------- real notes

RECORDED_LENA_SCORE = 0.2  # {pull acme s usage report last 6 months} vs {share usage report meera}


def test_dd01_real_sam_cloud_budget(real: list[Mention]) -> None:
    found = real_items(real, "Sam Okafor", "confirm cloud budget")
    assert len(found) == 1
    item, _ = found[0]
    assert item.status == "done"
    assert item.due == date(2026, 9, 18)
    assert item.mention_count == 3
    assert item.first_file.startswith("2026-09-01")
    assert item.latest_file.startswith("2026-09-22")
    assert item.id == "b48cced6"  # DD30 on real data


def test_dd02_real_priya_quote(real: list[Mention]) -> None:
    found = real_items(real, "Priya Nair", "revised quote")
    assert len(found) == 1
    item, _ = found[0]
    assert item.owner == "Priya Nair"
    assert item.status == "done"
    assert item.due == date(2026, 9, 11)
    assert item.mention_count == 3
    assert item.id == "cfc90787"  # DD31 on real data


def test_dd03_real_anita_wireframes(real: list[Mention]) -> None:
    """'share first wireframes' vs 'share updated wireframes' was 2/4 = 0.5 on plain Jaccard.

    The match key drops the qualifier, so all three mentions are one item (D24).
    """
    found = real_items(real, "Anita Desai", "wireframes")
    assert similarity("share first wireframes", "share updated wireframes") == 0.5
    assert len(found) == 1
    item, g = found[0]
    assert item.status == "open"
    assert item.mention_count == 3
    assert item.first_file.startswith("2026-09-01")
    assert item.latest_file.startswith("2026-09-22")
    last = g.mentions[-1]
    assert item.task == last.task == "share updated wireframes"
    assert item.due == last.due and item.due is not None
    assert item.id == item_id("Anita Desai", "share first wireframes", set())[0]


def test_dd40_real_rahul_sso_estimate_and_spike(real: list[Mention]) -> None:
    found = real_items(real, "Rahul", "sso")
    assert len(found) == 1
    item, _ = found[0]
    assert item.owner == "Rahul Verma"
    assert item.status == "open"
    assert item.mention_count == 3
    assert item.first_file.startswith("2026-09-14")
    assert item.latest_file.startswith("2026-10-05")
    assert item.due == date(2026, 10, 13)  # "by next Tuesday" from Mon 2026-10-05


@pytest.mark.parametrize(
    ("owner", "needle_a", "needle_b"),
    [
        ("Meera Iyer", "chase orbit", "proposal to orbit"),
        ("Priya Shah", "test plan for invoice rounding", "invoice rounding tests"),
        ("Meera Iyer", "procurement contact", "procurement form"),
        ("Lena Fischer", "pull acme", "share the usage report"),
        ("Lena Fischer", "collect 5 customer quotes", "publish the customer quotes"),
    ],
)
def test_dd41_real_distinct_steps_stay_apart(
    real: list[Mention], owner: str, needle_a: str, needle_b: str
) -> None:
    """Follow-on steps on the same subject are different tasks, not drift (D24)."""
    a = {i.id for i, _ in real_items(real, owner, needle_a)}
    b = {i.id for i, _ in real_items(real, owner, needle_b)}
    assert a and b
    assert a.isdisjoint(b)


def test_dd04_real_karan_freeze(real: list[Mention]) -> None:
    found = real_items(real, "Karan Joshi", "freeze invoice")
    assert len(found) == 1
    item, _ = found[0]
    assert item.status == "open"
    assert item.due is None
    assert item.mention_count == 2


def test_dd05_real_karan_refund(real: list[Mention]) -> None:
    found = real_items(real, "Karan Joshi", "refund affected")
    assert len(found) == 1
    item, _ = found[0]
    assert item.mention_count == 1


def test_dd06_real_rahul_beta(real: list[Mention]) -> None:
    found = real_items(real, "", "deploy the beta")
    found = [f for f in found if f[0].owner.startswith(("Rahul", "Ambiguous (Rahul"))]
    assert len(found) == 1
    item, _ = found[0]
    assert item.status == "done"
    assert item.mention_count == 3


def test_dd07_real_meera_renewal_call(real: list[Mention]) -> None:
    found = real_items(real, "Meera", "renewal call")
    assert len(found) == 1
    assert found[0][0].status == "done"
    assert found[0][0].mention_count == 3


def test_dd08_real_karan_export_invoices(real: list[Mention]) -> None:
    found = real_items(real, "Karan Joshi", "export last quarter invoices")
    assert len(found) == 1
    item, _ = found[0]
    assert item.status == "done"
    assert item.due == date(2026, 9, 10)


def test_dd09_real_priya_notify_customers(real: list[Mention]) -> None:
    found = real_items(real, "Priya", "maintenance window")
    assert len(found) == 1
    item, _ = found[0]
    assert item.status == "done"
    assert item.owner == "Priya Nair"  # 'Priya N.' in both notes


def test_dd10_real_lena_usage_report(real: list[Mention]) -> None:
    ms = sorted(
        (m for m in real if m.owner.startswith("Lena") and "usage report" in m.task.lower()),
        key=lambda m: m.meeting_date or date.min,
    )
    assert len(ms) == 2
    score = similarity(ms[0].task_key, ms[1].task_key)
    # Recorded actual score. Below the 0.6 threshold, so the rule yields two items.
    assert score == pytest.approx(RECORDED_LENA_SCORE)
    expected_items = 1 if score >= 0.6 else 2
    assert len(items_of(ms)) == expected_items


def test_dd35_dd36_ids_hex_and_unique(real: list[Mention]) -> None:
    items = items_of(real)
    assert len(items) > 20
    for i in items:
        assert re.fullmatch(r"[0-9a-f]{8}", i.id)
    assert len({i.id for i in items}) == len(items)
    assert sum(i.mention_count for i in items) == len(real)


def test_real_notes_shuffle_stable(real: list[Mention]) -> None:
    expected = snapshot(real)
    rng = random.Random(7)
    for _ in range(5):
        shuffled = real[:]
        rng.shuffle(shuffled)
        assert snapshot(shuffled) == expected


def test_real_notes_never_merge_across_owners(real: list[Mention]) -> None:
    for g in group_mentions(real):
        assert {(m.owner, m.owner_kind) for m in g.mentions} == {(g.owner, g.owner_kind)}
