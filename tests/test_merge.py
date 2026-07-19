"""Unit tests for the pure merge logic (#28): field union/dedup, self-relation
drop, single-value override selection, and group member rewrite. No DAV/HTTP --
see tests/test_merge_live.py for the full write-sequence coverage (-m live)."""

from peopledb.merge import (
    MergeChoice,
    build_merged_fields,
    drop_self_relations,
    rewrite_members,
    union_values,
)
from peopledb.vcard import AddressParts, Contact


def test_union_values_dedups_exact_string_keeper_first():
    keeper = [("home", "a@x.com"), ("work", "b@x.com")]
    source = [("work", "b@x.com"), ("other", "c@x.com")]
    assert union_values(keeper, source) == [
        ("home", "a@x.com"), ("work", "b@x.com"), ("other", "c@x.com"),
    ]


def test_union_values_first_label_wins_on_duplicate_value():
    keeper = [("home", "a@x.com")]
    source = [("work", "a@x.com")]
    assert union_values(keeper, source) == [("home", "a@x.com")]


def test_union_values_no_overlap_appends_all_source_entries():
    keeper = [("home", "a@x.com")]
    source = [("work", "b@x.com"), ("other", "c@x.com")]
    assert union_values(keeper, source) == [
        ("home", "a@x.com"), ("work", "b@x.com"), ("other", "c@x.com"),
    ]


def test_union_values_addresses_dedup_by_equal_parts():
    parts = AddressParts(street="1 Main St", city="Springfield")
    same = AddressParts(street="1 Main St", city="Springfield")
    different = AddressParts(street="2 Elm St", city="Springfield")
    keeper = [("home", parts)]
    source = [("home", same), ("work", different)]
    result = union_values(keeper, source)
    assert result == [("home", parts), ("work", different)]


def test_drop_self_relations_removes_keeper_uid_target():
    related = [("spouse", "keeper-uid"), ("friend", "Someone Else")]
    result = drop_self_relations(related, keeper_uid="keeper-uid", source_uid="source-uid")
    assert result == [("friend", "Someone Else")]


def test_drop_self_relations_removes_source_uid_target():
    related = [("spouse", "source-uid"), ("friend", "Someone Else")]
    result = drop_self_relations(related, keeper_uid="keeper-uid", source_uid="source-uid")
    assert result == [("friend", "Someone Else")]


def test_drop_self_relations_keeps_unrelated_targets():
    related = [("friend", "third-party-uid")]
    result = drop_self_relations(related, keeper_uid="keeper-uid", source_uid="source-uid")
    assert result == related


def test_rewrite_members_replaces_source_with_keeper():
    assert rewrite_members(["a", "source-uid", "b"], "source-uid", "keeper-uid") == [
        "a", "keeper-uid", "b",
    ]


def test_rewrite_members_dedups_when_keeper_already_a_member():
    assert rewrite_members(["keeper-uid", "source-uid"], "source-uid", "keeper-uid") == [
        "keeper-uid",
    ]


def test_rewrite_members_leaves_unrelated_groups_untouched():
    assert rewrite_members(["a", "b"], "source-uid", "keeper-uid") == ["a", "b"]


def test_build_merged_fields_defaults_to_contact_a_single_values():
    a = Contact(
        uid="a", formatted_name="A Person", given="Aaa", family="Person",
        org="A Co", note="a note", bday="1990-01-01",
    )
    b = Contact(
        uid="b", formatted_name="B Person", given="Bbb", family="Person",
        org="B Co", note="b note", bday="1991-02-02",
    )
    fields = build_merged_fields(a, b, MergeChoice(), contact_a=a, contact_b=b)
    assert fields.given == "Aaa"
    assert fields.family == "Person"
    assert fields.org == "A Co"
    assert fields.note == "a note"
    assert fields.bday == "1990-01-01"


def test_build_merged_fields_can_take_contact_b_single_values():
    a = Contact(uid="a", org="A Co")
    b = Contact(uid="b", org="B Co")
    choice = MergeChoice(org="b")
    fields = build_merged_fields(a, b, choice, contact_a=a, contact_b=b)
    assert fields.org == "B Co"


def test_build_merged_fields_single_values_independent_of_keeper():
    """The keeper-flip regression (#28 finding 1): whichever card is passed as
    `keeper`/`source` (deciding UID/href/raw base) must NOT change which
    single-valued fields win -- that is decided purely by contact_a/contact_b
    + choice."""
    a = Contact(uid="a", org="A Co")
    b = Contact(uid="b", org="B Co")
    choice = MergeChoice(org="b")
    # keeper=b, source=a this time -- org choice ("b") must still resolve to
    # contact_b's value, not flip because b is now the keeper.
    fields = build_merged_fields(b, a, choice, contact_a=a, contact_b=b)
    assert fields.org == "B Co"


def test_build_merged_fields_unions_multivalued_and_drops_self_relation():
    keeper = Contact(
        uid="k", formatted_name="Keeper Person",
        emails=[("home", "keeper@x.com")],
        related=[("spouse", "s")],  # relation to the source contact -> collapses
    )
    source = Contact(
        uid="s", formatted_name="Source Person",
        emails=[("work", "source@x.com")],
        related=[("spouse", "k"), ("friend", "Third Party")],
    )
    fields = build_merged_fields(
        keeper, source, MergeChoice(), contact_a=keeper, contact_b=source,
    )
    assert fields.emails == [("home", "keeper@x.com"), ("work", "source@x.com")]
    assert fields.related == [("friend", "Third Party")]


def test_build_merged_fields_accepts_explicit_multivalued_overrides():
    keeper = Contact(uid="k", emails=[("home", "keeper@x.com")])
    source = Contact(uid="s", emails=[("work", "source@x.com")])
    fields = build_merged_fields(
        keeper, source, MergeChoice(), contact_a=keeper, contact_b=source,
        emails=[("home", "keeper@x.com")],
    )
    assert fields.emails == [("home", "keeper@x.com")]
