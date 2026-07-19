"""Tests for the natural-language quick-entry parser (pure function seam)."""

from peopledb.quickparse import parse_quick_entry


def test_empty_string_is_all_empty():
    fields = parse_quick_entry("")
    assert fields.given == ""
    assert fields.family == ""
    assert fields.org == ""
    assert fields.note == ""
    assert fields.bday == ""
    assert fields.emails == []
    assert fields.phones == []
    assert fields.urls == []
    assert fields.related == []


def test_single_word_is_given_only():
    fields = parse_quick_entry("Madonna")
    assert fields.given == "Madonna"
    assert fields.family == ""


def test_two_words_are_given_and_family():
    fields = parse_quick_entry("Jane Doe")
    assert fields.given == "Jane"
    assert fields.family == "Doe"


def test_three_plus_words_family_is_the_rest():
    fields = parse_quick_entry("Jane Q Doe")
    assert fields.given == "Jane"
    assert fields.family == "Q Doe"


def test_name_and_email():
    fields = parse_quick_entry("Jane Doe jane@x.com")
    assert fields.given == "Jane"
    assert fields.family == "Doe"
    assert fields.emails == [("", "jane@x.com")]


def test_email_with_label():
    fields = parse_quick_entry("Jane Doe jane@x.com (work)")
    assert fields.emails == [("work", "jane@x.com")]


def test_phone_shape_and_label():
    fields = parse_quick_entry("Jane Doe +1 555 0142 (cell)")
    assert fields.phones == [("cell", "+1 555 0142")]
    assert fields.given == "Jane"
    assert fields.family == "Doe"


def test_bare_domain_is_not_treated_as_url():
    fields = parse_quick_entry("Jane acme.com")
    assert fields.urls == []
    # unresolved token falls through to family/note, but must not be a URL.


def test_url_requires_scheme_or_www():
    fields = parse_quick_entry("Jane Doe https://jane.example (site)")
    assert fields.urls == [("site", "https://jane.example")]


def test_www_url_recognized():
    fields = parse_quick_entry("Jane Doe www.jane.example")
    assert fields.urls == [("", "www.jane.example")]


def test_bday_with_year():
    fields = parse_quick_entry("Jane Doe bday 1990-03-03")
    assert fields.bday == "1990-03-03"


def test_bday_day_month_no_year():
    fields = parse_quick_entry("Jane Doe bday 3 Mar")
    assert fields.bday == "--03-03"


def test_org_multiword_to_end_of_string():
    fields = parse_quick_entry("Jane Doe org Acme Corp")
    assert fields.org == "Acme Corp"


def test_org_consumes_up_to_next_recognized_sigil():
    fields = parse_quick_entry("Jane Doe org Acme Corp bday 1990-03-03")
    assert fields.org == "Acme Corp"
    assert fields.bday == "1990-03-03"


def test_no_sigils_all_words_become_name():
    # With no recognized marker at all, every word is part of the leading
    # name run -- there is nothing left over for Note.
    fields = parse_quick_entry("Jane Doe met at the conference")
    assert fields.given == "Jane"
    assert fields.family == "Doe met at the conference"
    assert fields.note == ""


def test_unparseable_trailing_text_lands_in_note():
    # A marker (email) bounds the name run; text after it that isn't another
    # recognized sigil is leftover and must not be silently dropped.
    fields = parse_quick_entry("Jane Doe jane@x.com met at the conference")
    assert fields.given == "Jane"
    assert fields.family == "Doe"
    assert "met at the conference" in fields.note


def test_leftover_after_sigils_goes_to_note():
    fields = parse_quick_entry("Jane Doe jane@x.com met at a conference")
    assert fields.emails == [("", "jane@x.com")]
    assert fields.given == "Jane"
    assert "met at a conference" in fields.note


def test_ordering_email_phone_url_all_resolve_correctly():
    fields = parse_quick_entry(
        "Jane Doe jane@x.com +1 555 0142 https://jane.example"
    )
    assert fields.emails == [("", "jane@x.com")]
    assert fields.phones == [("", "+1 555 0142")]
    assert fields.urls == [("", "https://jane.example")]
    assert fields.given == "Jane"
    assert fields.family == "Doe"


def test_org_irregular_whitespace_is_not_duplicated_into_name():
    # Regression: a str.find() splice on a re-joined org missed when the user
    # typed a double space, leaking the org text into the name too.
    fields = parse_quick_entry("org Acme  Corp")
    assert fields.org == "Acme Corp"
    assert fields.given == ""
    assert fields.family == ""
    assert fields.note == ""


def test_bday_irregular_whitespace_is_not_duplicated_into_name():
    fields = parse_quick_entry("bday 3  Mar")
    assert fields.bday == "--03-03"
    assert fields.given == ""
    assert fields.family == ""
    assert fields.note == ""


def test_second_labeled_phone_is_not_dropped():
    # Regression: the `)` closing the first phone's label started a bogus
    # candidate that swallowed the second number, dropping it entirely.
    fields = parse_quick_entry("+1 555 0142 (work) +44 20 7946 0958 (home)")
    assert fields.phones == [
        ("work", "+1 555 0142"),
        ("home", "+44 20 7946 0958"),
    ]


def test_unlabeled_international_phones_split_on_plus():
    # Audit fix: a greedy run spanning two `+`-prefixed numbers is split.
    fields = parse_quick_entry("Sam +1 415 555 0100 +1 212 555 0199")
    assert fields.phones == [
        ("", "+1 415 555 0100"),
        ("", "+1 212 555 0199"),
    ]
    assert fields.given == "Sam"


def test_dotted_numbers_are_not_joined_into_a_phone():
    # Audit fix: `.` removed from the phone char class (spec-conform), so a
    # dotted IP is no longer joined across the dots into one long phone run.
    # (A single >=7-digit run is still phone-shaped by nature -- unavoidable.)
    assert parse_quick_entry("host 192.168.1.100 online").phones == []
    assert parse_quick_entry("v 1.2.3.4 rolled out").phones == []


def test_ambiguous_slash_date_is_not_parsed_as_bday():
    # Audit fix: bare D/M vs M/D is too ambiguous to guess (feeds the ICS
    # feed); it is left unparsed for the user to enter in the reviewed form.
    fields = parse_quick_entry("Jane Doe bday 3/4")
    assert fields.bday == ""
    assert fields.given == "Jane"


def test_whitespace_joined_domestic_pair_splits_into_two_phones():
    # Issue #23: unlike a `+`-prefixed run, a purely domestic run had no
    # split point and stayed merged into one bogus phone. Greedy >=10-digit
    # close now splits it into two.
    fields = parse_quick_entry("Jane 555-123-4567 555-987-6543")
    assert fields.phones == [("", "555-123-4567"), ("", "555-987-6543")]


def test_grouped_ten_digit_number_is_not_fragmented():
    # A single number typed as space-grouped triples must stay one phone --
    # the greedy close only fires once >=10 digits accumulate, i.e. at the
    # end of this run, not after each group.
    fields = parse_quick_entry("555 123 4567")
    assert len(fields.phones) == 1


def test_eleven_digit_grouped_number_without_plus_is_not_fragmented():
    fields = parse_quick_entry("Sam 1 555 123 4567")
    assert len(fields.phones) == 1


def test_domestic_pair_trailing_label_applies_to_last_number():
    fields = parse_quick_entry("5551234567 5559876543 (home)")
    assert fields.phones == [("", "5551234567"), ("home", "5559876543")]


def test_long_international_number_stays_one_phone():
    # Regression guard on the >=10-digit close: a real E.164 number (<=15
    # digits) can never reach the >=17 digits a spurious split needs, so a
    # long irregularly-grouped international number must stay one phone even
    # though the greedy close fires mid-run. Guards against a threshold tweak
    # silently fragmenting valid numbers.
    fields = parse_quick_entry("Ana +880 1712 345678")
    assert fields.phones == [("", "+880 1712 345678")]


def test_trailing_sub7_group_folds_back_into_previous_number():
    # The fold-back branch: after a number closes at >=10 digits, a trailing
    # group with <7 digits is not a phone on its own -- it folds back rather
    # than being emitted as a fragment.
    fields = parse_quick_entry("5551234567 12")
    assert fields.phones == [("", "5551234567 12")]


def test_iso_and_named_month_dates_still_parse():
    assert parse_quick_entry("x bday 1990-03-04").bday == "1990-03-04"


def test_single_group_sigil():
    fields = parse_quick_entry("Jane Doe #family")
    assert fields.groups == ["family"]
    assert fields.given == "Jane"
    assert fields.family == "Doe"


def test_multiple_group_sigils():
    fields = parse_quick_entry("Jane Doe #family #work")
    assert fields.groups == ["family", "work"]


def test_group_sigil_case_is_preserved():
    fields = parse_quick_entry("Jane #Family")
    assert fields.groups == ["Family"]


def test_hash_inside_url_is_not_read_as_group():
    fields = parse_quick_entry("Jane www.foo.com#frag")
    assert fields.groups == []
    assert fields.urls == [("", "www.foo.com#frag")]


def test_bare_hash_is_ignored():
    fields = parse_quick_entry("Jane # Doe")
    assert fields.groups == []
    assert parse_quick_entry("x bday Mar 3").bday == "--03-03"
