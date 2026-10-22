"""Tests for owners.py (TEST_PLAN section 4, IDs O01-O25)."""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from actiontrack.owners import OwnerResult, build_roster, parse_collaborators, resolve_owner

NOTES = Path(__file__).resolve().parent.parent / "notes"

NINE = [
    "Priya Nair",
    "Rahul Mehta",
    "Anita Desai",
    "Sam Okafor",
    "Meera Iyer",
    "Karan Joshi",
    "Lena Fischer",
    "Priya Shah",
    "Rahul Verma",
]


def attendees_of(name: str) -> list[str]:
    """Read the Attendees line of a real note (read-only), header or YAML style."""
    try:
        text = (NOTES / name).read_text(encoding="utf-8")
    except UnicodeDecodeError:  # scratch.md is binary on purpose
        return []
    for line in text.splitlines():
        m = re.match(r"\s*attendees:\s*(.*)$", line, re.IGNORECASE)
        if m:
            body = m[1].strip().strip("[]")
            return [a.strip() for a in body.split(",") if a.strip()]
    return []


def note_has(name: str, text: str) -> None:
    assert text in (NOTES / name).read_text(encoding="utf-8")


@pytest.fixture
def roster():
    return build_roster([NINE])


def resolve(text, attendees, roster):
    return resolve_owner(text, attendees, roster)


def test_owner_result_is_frozen(roster):
    r = resolve("Anita", [], roster)
    assert isinstance(r, OwnerResult)
    with pytest.raises(AttributeError):
        r.owner = "x"  # type: ignore[misc]


def test_roster_maps_first_name_to_full_names(roster):
    assert roster.full_names("priya") == frozenset({"Priya Nair", "Priya Shah"})
    assert roster.full_names("RAHUL") == frozenset({"Rahul Mehta", "Rahul Verma"})
    assert roster.full_names("anita") == frozenset({"Anita Desai"})
    assert roster.full_names("zoe") == frozenset()


def test_roster_from_real_notes_matches_the_nine():
    lists = [attendees_of(p.name) for p in NOTES.glob("*.md")]
    r = build_roster(lists)
    names = set().union(*(r.full_names(f) for f in ("priya", "rahul", "anita", "sam", "meera")))
    names |= r.full_names("karan") | r.full_names("lena")
    assert names == set(NINE)


# --- O01-O02 unique first names -----------------------------------------------------------


def test_o01_unique_first_name_resolves_without_attendance(roster):
    r = resolve("Anita", ["Sam Okafor"], roster)
    assert (r.owner, r.kind, r.collaborators) == ("Anita Desai", "person", [])
    assert r.warning is None


@pytest.mark.parametrize(
    ("first", "full"),
    [
        ("Sam", "Sam Okafor"),
        ("Meera", "Meera Iyer"),
        ("Karan", "Karan Joshi"),
        ("Lena", "Lena Fischer"),
    ],
)
def test_o02_unique_names(first, full, roster):
    att = attendees_of("2026-10-02-finance-sync.md")
    r = resolve(first, att, roster)
    assert (r.owner, r.kind) == (full, "person")


# --- O03-O15 same-first-name rules --------------------------------------------------------


def test_o03_only_nair_attended(roster):
    att = attendees_of("2026-09-01-quote-portal-kickoff.md")
    r = resolve("Priya", att, roster)
    assert (r.owner, r.kind) == ("Priya Nair", "person")


def test_o04_only_shah_attended(roster):
    att = attendees_of("2026-09-03-billing-migration-sync.md")
    r = resolve("Priya", att, roster)
    assert (r.owner, r.kind) == ("Priya Shah", "person")


def test_o05_both_priyas_ambiguous(roster):
    att = attendees_of("2026-09-17-billing-migration-sync.md")
    r = resolve("Priya", att, roster)
    assert (r.owner, r.kind) == ("Ambiguous (Priya)", "ambiguous")
    assert r.warning


def test_o06_bare_priya_ambiguous_but_initial_resolves(roster):
    att = attendees_of("2026-10-08-billing-go-no-go.md")
    assert resolve("Priya", att, roster).owner == "Ambiguous (Priya)"
    assert resolve("Priya N.", att, roster).owner == "Priya Nair"


def test_o07_initials(roster):
    att = attendees_of("2026-09-29-billing-cutover-planning.md")
    note_has("2026-09-29-billing-cutover-planning.md", "Priya S. to run")
    assert resolve("Priya S.", att, roster).owner == "Priya Shah"
    assert resolve("Priya N.", att, roster).owner == "Priya Nair"
    assert resolve("Priya S.", att, roster).warning is None


def test_o08_initial_agrees_with_single_attendee(roster):
    att = attendees_of("2026-09-08-quote-portal-weekly.md")
    r = resolve("Priya N.", att, roster)
    assert (r.owner, r.kind, r.warning) == ("Priya Nair", "person", None)


def test_o09_initial_wins_over_attendees_with_warning(roster):
    r = resolve("Priya N.", ["Priya Shah", "Sam Okafor"], roster)
    assert (r.owner, r.kind) == ("Priya Nair", "person")
    assert r.warning
    assert "Priya Nair" in r.warning


def test_initial_without_dot_and_lowercase(roster):
    assert resolve("priya s", [], roster).owner == "Priya Shah"
    assert resolve("Rahul V.", [], roster).owner == "Rahul Verma"
    assert resolve("Rahul M", [], roster).owner == "Rahul Mehta"


def test_o10_o13_no_attendees_is_ambiguous(roster):
    att = attendees_of("2026-09-23-standup.md")
    assert att == []
    assert resolve("Priya", att, roster).owner == "Ambiguous (Priya)"
    r = resolve("Rahul", att, roster)
    assert (r.owner, r.kind) == ("Ambiguous (Rahul)", "ambiguous")
    assert r.warning


def test_o11_both_rahuls_ambiguous_no_inference(roster):
    att = attendees_of("2026-10-07-standup.md")
    r = resolve("Rahul", att, roster)
    assert (r.owner, r.kind) == ("Ambiguous (Rahul)", "ambiguous")


def test_o11b_d23_two_rahuls_even_with_a_billing_cluster(roster):
    # data-findings hints at Verma on 09-17, but both attended: never guess.
    att = attendees_of("2026-09-17-billing-migration-sync.md") + ["Rahul Mehta"]
    assert resolve("Rahul", att, roster).owner == "Ambiguous (Rahul)"


def test_o12_only_verma(roster):
    att = attendees_of("2026-10-09-security-review.md")
    r = resolve("Rahul", att, roster)
    assert (r.owner, r.kind) == ("Rahul Verma", "person")


def test_o14_offsite_everyone_present(roster):
    att = attendees_of("2026-09-30-q4-offsite.md")
    assert len(att) == 9
    assert resolve("Priya", att, roster).kind == "ambiguous"
    assert resolve("Rahul", att, roster).kind == "ambiguous"


def test_o15_priya_nair_with_mehta_attending(roster):
    att = attendees_of("2026-09-18-design-review.md")
    assert resolve("Priya", att, roster).owner == "Priya Nair"
    assert resolve("Rahul", att, roster).owner == "Rahul Mehta"


def test_attendee_matching_is_case_and_space_insensitive(roster):
    r = resolve("Priya", ["  priya   shah "], roster)
    assert r.owner == "Priya Shah"


def test_full_name_resolves_directly(roster):
    r = resolve("Priya Nair", ["Priya Nair", "Priya Shah"], roster)
    assert (r.owner, r.kind) == ("Priya Nair", "person")


# --- O16-O20 syntaxes -----------------------------------------------------------------------


@pytest.mark.parametrize("text", ["@anita", "@anita:", "@Anita", "  @ANITA "])
def test_o16_handle(text, roster):
    att = attendees_of("2026-09-18-design-review.md")
    note_has("2026-09-18-design-review.md", "@anita:")
    r = resolve(text, att, roster)
    assert (r.owner, r.kind) == ("Anita Desai", "person")


def test_handle_for_shared_first_name_follows_the_same_rules(roster):
    assert resolve("@priya", ["Priya Shah"], roster).owner == "Priya Shah"
    assert resolve("@priya", [], roster).kind == "ambiguous"


def test_o17_joint_owners_with_ambiguous_second(roster):
    note_has("2026-09-18-design-review.md", "Anita & Rahul to agree")
    att = ["Anita Desai", "Rahul Mehta", "Rahul Verma"]
    r = resolve("Anita & Rahul", att, roster)
    assert r.owner == "Anita Desai"
    assert r.kind == "person"
    assert r.collaborators == ["Ambiguous (Rahul)"]
    assert parse_collaborators("Anita & Rahul", att, roster) == ["Ambiguous (Rahul)"]


def test_o17_real_attendees_resolve_the_collaborator(roster):
    att = attendees_of("2026-09-18-design-review.md")
    r = resolve("Anita & Rahul", att, roster)
    assert (r.owner, r.collaborators) == ("Anita Desai", ["Rahul Mehta"])


def test_o18_lena_with_priya(roster):
    note_has("2026-09-18-design-review.md", "Lena (with Priya) to collect")
    att = attendees_of("2026-09-18-design-review.md")
    r = resolve("Lena (with Priya)", att, roster)
    assert (r.owner, r.kind) == ("Lena Fischer", "person")
    assert r.collaborators == ["Priya Nair"]
    assert parse_collaborators("Lena (with Priya)", att, roster) == ["Priya Nair"]


def test_o18_collaborator_ambiguous_when_both_attend(roster):
    r = resolve("Lena (with Priya)", NINE, roster)
    assert r.collaborators == ["Ambiguous (Priya)"]


def test_owner_is_first_listed(roster):
    r = resolve("Rahul V. & Anita", [], roster)
    assert (r.owner, r.collaborators) == ("Rahul Verma", ["Anita Desai"])
    r = resolve("Anita and Sam", [], roster)
    assert (r.owner, r.collaborators) == ("Anita Desai", ["Sam Okafor"])


def test_no_collaborators_for_single_owner(roster):
    assert parse_collaborators("Anita", [], roster) == []
    assert resolve("Anita", [], roster).collaborators == []


@pytest.mark.parametrize("word", ["Everyone", "Team", "Everybody"])
def test_o19_group_words(word, roster):
    note_has("2026-09-18-design-review.md", "Everyone to review")
    note_has("2026-10-01-quote-portal-weekly.md", "Team to decide")
    r = resolve(word, NINE, roster)
    assert (r.owner, r.kind, r.collaborators) == ("Unassigned", "unassigned", [])
    assert r.raw == word


@pytest.mark.parametrize("word", ["TBD", "Someone", "Anyone"])
def test_o20_unassigned_words(word, roster):
    note_has("2026-09-10-acme-renewal-prep.md", "Someone to update")
    r = resolve(word, attendees_of("2026-09-10-acme-renewal-prep.md"), roster)
    assert (r.owner, r.kind) == ("Unassigned", "unassigned")
    assert r.raw == word


@pytest.mark.parametrize("word", ["everyone", "EVERYONE", " tbd ", "TEAM", "someOne"])
def test_group_words_case_insensitive(word, roster):
    r = resolve(word, [], roster)
    assert r.kind == "unassigned"
    assert r.raw == word.strip()


def test_o21_none_and_blank(roster):
    for text in (None, "", "   "):
        r = resolve(text, [], roster)
        assert (r.owner, r.kind, r.collaborators) == ("Unassigned", "unassigned", [])


# --- O22-O25 ----------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["priya", "PRIYA", "Priya ", "  Priya", "PrIyA"])
def test_o22_case_and_whitespace_variants(text, roster):
    base = resolve("Priya", ["Priya Shah"], roster)
    assert resolve(text, ["Priya Shah"], roster) == base or (
        resolve(text, ["Priya Shah"], roster).owner == base.owner
    )
    assert resolve(text, NINE, roster).owner == "Ambiguous (Priya)"


def test_o23_unknown_name_not_dropped(roster):
    r = resolve("Zoe", NINE, roster)
    assert (r.owner, r.kind) == ("Zoe", "person")
    assert r.warning
    assert "unknown owner" in r.warning.lower()


def test_unknown_collaborator_kept_with_warning(roster):
    r = resolve("Anita & Zoe", [], roster)
    assert r.owner == "Anita Desai"
    assert r.collaborators == ["Zoe"]
    assert r.warning and "unknown owner" in r.warning.lower()


def test_o24_owner_comes_from_owner_text_only(roster):
    att = attendees_of("2026-10-07-standup.md")
    note_has("2026-10-07-standup.md", "Rahul to review Anita's PR")
    r = resolve("Rahul", att, roster)
    assert r.owner == "Ambiguous (Rahul)"
    assert r.collaborators == []


def test_o25_roster_is_order_independent():
    lists = [attendees_of(p.name) for p in sorted(NOTES.glob("*.md"))]
    base = build_roster(lists)
    cases = [("Priya", ["Priya Shah"]), ("Rahul", NINE), ("Anita", []), ("Priya S.", [])]
    expected = [resolve_owner(t, a, base) for t, a in cases]
    rng = random.Random(7)
    for _ in range(5):
        shuffled = [list(x) for x in lists]
        rng.shuffle(shuffled)
        for lst in shuffled:
            rng.shuffle(lst)
        roster = build_roster(shuffled)
        assert roster == base
        assert [resolve_owner(t, a, roster) for t, a in cases] == expected


def test_build_roster_accepts_generator_and_ignores_blanks():
    r = build_roster(iter([["Priya  Nair", " "], [], ["priya nair"]]))
    assert r.full_names("priya") == frozenset({"Priya Nair"})


def test_never_guesses_when_roster_is_empty():
    r = resolve_owner("Priya", [], build_roster([]))
    assert r.owner == "Priya"
    assert r.kind == "person"
    assert r.warning
