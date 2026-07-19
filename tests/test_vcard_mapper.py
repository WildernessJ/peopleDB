"""Tests for the vCard mapper seam: parse_vcard / new_vcard / apply_edits."""

import base64

import pytest

from peopledb.vcard import (
    AddressParts,
    Contact,
    ContactFields,
    apply_edits,
    new_vcard,
    parse_vcard,
)

JPEG_B64 = base64.b64encode(b"totally-a-jpeg").decode()
PNG_B64 = base64.b64encode(b"totally-a-png").decode()

SIMPLE_CARD = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:abc-123\r\n"
    "FN:Sarah Jones\r\n"
    "N:Jones;Sarah;;;\r\n"
    "END:VCARD\r\n"
)


APPLE_CARD = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:def-456\r\n"
    "FN:Bob Smith\r\n"
    "N:Smith;Bob;;;\r\n"
    "ORG:Acme Corp;\r\n"
    "NOTE:Met at the conference.\r\n"
    "EMAIL;TYPE=INTERNET;TYPE=WORK;TYPE=pref:bob@acme.example\r\n"
    "TEL;TYPE=CELL;TYPE=VOICE:+1 555 0100\r\n"
    "item1.TEL:+1 555 0199\r\n"
    "item1.X-ABLABEL:Batphone\r\n"
    "item2.URL:https://bob.example\r\n"
    "item2.X-ABLABEL:_$!<HomePage>!$_\r\n"
    "ADR;TYPE=HOME:;;1 Main St;Springfield;IL;62704;USA\r\n"
    "BDAY:1985-04-12\r\n"
    "END:VCARD\r\n"
)


def test_parse_emails_and_phones_with_labels():
    contact = parse_vcard(APPLE_CARD)
    assert contact.emails == [("work", "bob@acme.example")]
    assert contact.phones == [("cell", "+1 555 0100"), ("Batphone", "+1 555 0199")]


def test_parse_org_note_bday_url_address():
    contact = parse_vcard(APPLE_CARD)
    assert contact.org == "Acme Corp"
    assert contact.note == "Met at the conference."
    assert contact.bday == "1985-04-12"
    assert contact.urls == [("HomePage", "https://bob.example")]
    assert len(contact.addresses) == 1
    label, parts = contact.addresses[0]
    assert label == "home"
    assert parts == AddressParts(
        street="1 Main St", city="Springfield", region="IL", code="62704", country="USA",
    )
    assert parts.formatted == "1 Main St, Springfield, IL, 62704, USA"


RELATED_CARD = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:rel-1\r\n"
    "FN:Carol King\r\n"
    "N:King;Carol;;;\r\n"
    "item3.X-ABRELATEDNAMES:James King\r\n"
    "item3.X-ABLABEL:_$!<Spouse>!$_\r\n"
    "item4.X-ABRELATEDNAMES:Ann Lee\r\n"
    "item4.X-ABLABEL:Manager\r\n"
    "END:VCARD\r\n"
)

GROUP_CARD = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:grp-1\r\n"
    "FN:Book Club\r\n"
    "N:Book Club\r\n"
    "X-ADDRESSBOOKSERVER-KIND:group\r\n"
    "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:abc-123\r\n"
    "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:def-456\r\n"
    "END:VCARD\r\n"
)


def test_parse_relationships_with_apple_labels():
    contact = parse_vcard(RELATED_CARD)
    assert contact.related == [("Spouse", "James King"), ("Manager", "Ann Lee")]


def test_parse_vcard4_related_property():
    card = (
        "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:v4-1\r\n"
        "FN:Dee Four\r\nN:Four;Dee;;;\r\n"
        "RELATED;TYPE=spouse;VALUE=text:Eve Four\r\n"
        "END:VCARD\r\n"
    )
    contact = parse_vcard(card)
    assert contact.related == [("spouse", "Eve Four")]


def test_parse_group_card():
    group = parse_vcard(GROUP_CARD)
    assert group.is_group is True
    assert group.formatted_name == "Book Club"
    assert group.member_uids == ["abc-123", "def-456"]


def test_new_vcard_roundtrips_through_parse():
    fields = ContactFields(
        given="Dana",
        family="Wu",
        org="Initech",
        note="Neighbor",
        bday="1990-06-01",
        emails=[("home", "dana@example.net")],
        phones=[("cell", "+1 555 0111"), ("Batphone", "+1 555 0122")],
        urls=[("HomePage", "https://dana.example")],
        related=[("Spouse", "Lee Wu")],
    )
    raw = new_vcard(fields)
    contact = parse_vcard(raw)
    assert contact.uid  # generated
    assert contact.formatted_name == "Dana Wu"
    assert contact.given == "Dana"
    assert contact.family == "Wu"
    assert contact.org == "Initech"
    assert contact.bday == "1990-06-01"
    assert contact.emails == [("home", "dana@example.net")]
    assert contact.phones == [("cell", "+1 555 0111"), ("Batphone", "+1 555 0122")]
    assert contact.urls == [("HomePage", "https://dana.example")]
    assert contact.related == [("Spouse", "Lee Wu")]
    assert "VERSION:3.0" in raw


def test_apply_edits_preserves_unmodeled_n_and_org_components():
    # A no-op-ish save must not destroy N sub-components (prefix/middle/suffix)
    # or ORG department components the Contact model doesn't surface.
    raw = (
        "BEGIN:VCARD\r\n"
        "VERSION:3.0\r\n"
        "UID:struct-1\r\n"
        "FN:Dr. Jane A. Doe Jr.\r\n"
        "N:Doe;Jane;Ann;Dr.;Jr.\r\n"
        "ORG:Acme;Engineering;Backend\r\n"
        "END:VCARD\r\n"
    )
    edited = apply_edits(raw, ContactFields(given="Jane", family="Doe", org="Acme"))
    lines = edited.split("\r\n")
    n_line = next(line for line in lines if line.startswith("N:"))
    org_line = next(line for line in lines if line.startswith("ORG:"))
    assert n_line == "N:Doe;Jane;Ann;Dr.;Jr."
    assert org_line == "ORG:Acme;Engineering;Backend"


def test_apply_edits_updates_modeled_name_component():
    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:struct-2\r\n"
        "FN:Jane Doe\r\nN:Doe;Jane;Ann;Dr.;Jr.\r\nEND:VCARD\r\n"
    )
    edited = apply_edits(raw, ContactFields(given="Janet", family="Doe"))
    contact = parse_vcard(edited)
    assert contact.given == "Janet"
    # unmodeled components still intact
    n_line = next(line for line in edited.split("\r\n") if line.startswith("N:"))
    assert n_line == "N:Doe;Janet;Ann;Dr.;Jr."
    assert contact.formatted_name == "Janet Doe"


def test_apply_edits_changes_fields_and_preserves_unknown_properties():
    raw = (
        "BEGIN:VCARD\r\n"
        "VERSION:3.0\r\n"
        "UID:keep-1\r\n"
        "FN:Old Name\r\n"
        "N:Name;Old;;;\r\n"
        "TEL;TYPE=CELL:+1 555 0000\r\n"
        "PHOTO;ENCODING=b;TYPE=JPEG:dGVzdGRhdGE=\r\n"
        "X-CUSTOM-FLAG:keep-me\r\n"
        "item9.X-SOCIALPROFILE;type=twitter:https://twitter.com/old\r\n"
        "item9.X-ABLABEL:twitter\r\n"
        "END:VCARD\r\n"
    )
    fields = ContactFields(given="New", family="Name", phones=[("cell", "+1 555 9999")])
    edited = apply_edits(raw, fields)
    contact = parse_vcard(edited)
    assert contact.uid == "keep-1"
    assert contact.formatted_name == "New Name"
    assert contact.phones == [("cell", "+1 555 9999")]
    # Unrendered properties survive the edit untouched.
    assert "dGVzdGRhdGE=" in edited
    assert "X-CUSTOM-FLAG:keep-me" in edited
    assert "https://twitter.com/old" in edited
    assert "item9.X-ABLABEL:twitter" in edited


def test_new_group_and_member_editing():
    from peopledb.vcard import new_group, set_group

    raw = new_group("Neighbors", member_uids=["abc-123"])
    group = parse_vcard(raw)
    assert group.is_group is True
    assert group.formatted_name == "Neighbors"
    assert group.member_uids == ["abc-123"]

    edited = set_group(raw, name="Street Friends", member_uids=["abc-123", "def-456"])
    group = parse_vcard(edited)
    assert group.formatted_name == "Street Friends"
    assert group.member_uids == ["abc-123", "def-456"]
    assert group.uid == parse_vcard(raw).uid  # UID stable across edits


def test_parse_minimal_card_extracts_identity():
    contact = parse_vcard(SIMPLE_CARD)
    assert contact.uid == "abc-123"
    assert contact.formatted_name == "Sarah Jones"
    assert contact.given == "Sarah"
    assert contact.family == "Jones"
    assert contact.is_group is False


# -- PHOTO (issue #9) ---------------------------------------------------------


def test_parse_photo_v3_embedded_base64():
    card = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-v3\r\nFN:Vera Three\r\n"
        f"PHOTO;ENCODING=b;TYPE=JPEG:{JPEG_B64}\r\nEND:VCARD\r\n"
    )
    contact = parse_vcard(card)
    assert contact.photo_media_type == "image/jpeg"
    assert contact.photo_b64 == JPEG_B64
    assert contact.photo_uri == ""
    assert contact.has_photo is True


def test_parse_photo_v3_type_as_full_media_type_and_base64_param_spelling():
    card = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-v3b\r\nFN:Peg Ann\r\n"
        f"PHOTO;ENCODING=BASE64;TYPE=image/png:{PNG_B64}\r\nEND:VCARD\r\n"
    )
    contact = parse_vcard(card)
    assert contact.photo_media_type == "image/png"
    assert contact.photo_b64 == PNG_B64
    assert contact.has_photo is True


def test_parse_photo_v4_data_uri():
    card = (
        "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:photo-v4\r\nFN:Vic Four\r\n"
        f"PHOTO:data:image/png;base64,{PNG_B64}\r\nEND:VCARD\r\n"
    )
    contact = parse_vcard(card)
    assert contact.photo_media_type == "image/png"
    assert contact.photo_b64 == PNG_B64
    assert contact.photo_uri == ""
    assert contact.has_photo is True


def test_parse_photo_uri_form_explicit_value_param():
    card = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-uri\r\nFN:Uri Person\r\n"
        "PHOTO;VALUE=uri:https://example.com/photo.jpg\r\nEND:VCARD\r\n"
    )
    contact = parse_vcard(card)
    assert contact.photo_uri == "https://example.com/photo.jpg"
    assert contact.photo_b64 == ""
    assert contact.has_photo is True


def test_parse_photo_bare_uri_value():
    card = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-uri2\r\nFN:Uri Two\r\n"
        "PHOTO:http://example.com/pic.png\r\nEND:VCARD\r\n"
    )
    contact = parse_vcard(card)
    assert contact.photo_uri == "http://example.com/pic.png"
    assert contact.has_photo is True


def test_parse_photo_invalid_base64_treated_as_absent():
    card = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-bad\r\nFN:Bad Photo\r\n"
        "PHOTO;ENCODING=b;TYPE=JPEG:not-valid-base64!!!\r\nEND:VCARD\r\n"
    )
    contact = parse_vcard(card)
    assert contact.has_photo is False
    assert contact.photo_b64 == ""
    assert contact.photo_uri == ""
    # rest of the card still parses -- an invalid PHOTO must not crash parse_vcard
    assert contact.formatted_name == "Bad Photo"


def test_parse_card_without_photo_has_no_photo():
    contact = parse_vcard(SIMPLE_CARD)
    assert contact.has_photo is False
    assert contact.photo_b64 == ""
    assert contact.photo_uri == ""


def test_parse_photo_folded_across_lines():
    # RFC 6350 line folding: a continuation line starts with a single space.
    half = len(JPEG_B64) // 2
    folded = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-fold\r\nFN:Fold Person\r\n"
        f"PHOTO;ENCODING=b;TYPE=JPEG:{JPEG_B64[:half]}\r\n {JPEG_B64[half:]}\r\nEND:VCARD\r\n"
    )
    contact = parse_vcard(folded)
    assert contact.photo_b64 == JPEG_B64
    assert contact.has_photo is True


def test_apply_edits_leaves_embedded_photo_byte_identical():
    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-keep\r\nFN:Old Name\r\nN:Name;Old;;;\r\n"
        f"PHOTO;ENCODING=b;TYPE=JPEG:{JPEG_B64}\r\nEND:VCARD\r\n"
    )
    edited = apply_edits(raw, ContactFields(given="New", family="Name"))
    photo_line = next(line for line in raw.split("\r\n") if line.startswith("PHOTO"))
    assert photo_line in edited


def test_contact_initials_from_given_and_family():
    contact = Contact(given="Jane", family="Doe", formatted_name="Jane Doe")
    assert contact.initials == "JD"


def test_contact_initials_from_given_only():
    contact = Contact(given="Cher", formatted_name="Cher")
    assert contact.initials == "C"


def test_contact_initials_falls_back_to_formatted_name():
    contact = Contact(formatted_name="Madonna")
    assert contact.initials == "M"


# -- code review follow-ups (issue #9) ----------------------------------------


def test_apply_edits_succeeds_on_card_with_invalid_photo_base64():
    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:edit-bad-photo\r\nFN:Old Name\r\nN:Name;Old;;;\r\n"
        "PHOTO;ENCODING=b;TYPE=JPEG:not-valid-base64!!!\r\nEND:VCARD\r\n"
    )
    edited = apply_edits(raw, ContactFields(given="New", family="Name"))
    contact = parse_vcard(edited)
    assert contact.given == "New"
    assert contact.family == "Name"
    # broken PHOTO is unavoidably lost -- vobject can't round-trip invalid base64
    assert contact.has_photo is False


def test_set_group_succeeds_on_card_with_invalid_photo_base64():
    from peopledb.vcard import set_group

    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:group-bad-photo\r\nFN:Old Group\r\n"
        "N:Old Group;;;;\r\nX-ADDRESSBOOK-SERVER-KIND:group\r\n"
        "PHOTO;ENCODING=b;TYPE=JPEG:not-valid-base64!!!\r\nEND:VCARD\r\n"
    )
    edited = set_group(raw, "New Group", ["member-1"])
    group = parse_vcard(edited)
    assert group.formatted_name == "New Group"
    assert group.member_uids == ["member-1"]
    assert group.has_photo is False


def test_parse_photo_skips_unrecognized_line_and_uses_next_valid_one():
    card = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-multi\r\nFN:Multi Photo\r\n"
        "PHOTO;ENCODING=x-weird:garbage\r\n"
        f"PHOTO;ENCODING=b;TYPE=JPEG:{JPEG_B64}\r\nEND:VCARD\r\n"
    )
    contact = parse_vcard(card)
    assert contact.photo_b64 == JPEG_B64
    assert contact.has_photo is True


def test_parse_photo_encoding_b_takes_priority_over_value_uri_param():
    card = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-priority\r\nFN:Priority Person\r\n"
        f"PHOTO;ENCODING=b;VALUE=uri;TYPE=JPEG:{JPEG_B64}\r\nEND:VCARD\r\n"
    )
    contact = parse_vcard(card)
    assert contact.photo_b64 == JPEG_B64
    assert contact.photo_uri == ""


def test_parse_photo_defaults_media_type_to_jpeg_when_type_missing():
    card = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-notype\r\nFN:No Type\r\n"
        f"PHOTO;ENCODING=b:{JPEG_B64}\r\nEND:VCARD\r\n"
    )
    contact = parse_vcard(card)
    assert contact.photo_media_type == "image/jpeg"


def test_parse_photo_quoted_type_param_with_embedded_semicolon():
    # RFC 6350 param-value quoting: a semicolon inside a quoted TYPE value is
    # not a parameter separator. A naive regex leaks a literal `"` into the
    # parsed media type, producing a malformed Content-Type from /photo.
    card = (
        'BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-quoted\r\nFN:Quoted Person\r\n'
        f'PHOTO;ENCODING=b;TYPE="image/jpeg;extra":{JPEG_B64}\r\nEND:VCARD\r\n'
    )
    contact = parse_vcard(card)
    assert contact.photo_media_type == "image/jpeg;extra"
    assert contact.photo_b64 == JPEG_B64
    assert contact.has_photo is True


# -- addresses (issue #1) -----------------------------------------------------


def test_parse_address_preserves_pobox_and_extended():
    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:adr-1\r\nFN:Adi Ex\r\nN:Ex;Adi;;;\r\n"
        "ADR;TYPE=WORK:PO Box 9;Suite 200;1 Main St;Springfield;IL;62704;USA\r\n"
        "END:VCARD\r\n"
    )
    contact = parse_vcard(raw)
    label, parts = contact.addresses[0]
    assert label == "work"
    assert parts.pobox == "PO Box 9"
    assert parts.extended == "Suite 200"
    assert parts.street == "1 Main St"
    assert parts.formatted == "1 Main St, Springfield, IL, 62704, USA"


def test_new_vcard_writes_address_with_label():
    fields = ContactFields(
        given="Adi",
        family="Ex",
        addresses=[("home", AddressParts(street="1 Main St", city="Springfield",
                                          region="IL", code="62704", country="USA"))],
    )
    raw = new_vcard(fields)
    contact = parse_vcard(raw)
    label, parts = contact.addresses[0]
    assert label == "home"
    assert parts.formatted == "1 Main St, Springfield, IL, 62704, USA"


def test_new_vcard_writes_address_with_custom_ablabel():
    fields = ContactFields(
        given="Adi",
        family="Ex",
        addresses=[("Summer House", AddressParts(street="2 Elm St", city="Metropolis"))],
    )
    raw = new_vcard(fields)
    assert "X-ABLABEL:Summer House" in raw
    contact = parse_vcard(raw)
    label, parts = contact.addresses[0]
    assert label == "Summer House"
    assert parts.street == "2 Elm St"


def test_apply_edits_adds_address_to_card_with_none():
    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:adr-add\r\nFN:No Addr\r\nN:Addr;No;;;\r\n"
        "END:VCARD\r\n"
    )
    fields = ContactFields(
        given="No", family="Addr",
        addresses=[("home", AddressParts(street="9 New St", city="Newtown"))],
    )
    edited = apply_edits(raw, fields)
    contact = parse_vcard(edited)
    assert contact.addresses == [("home", AddressParts(street="9 New St", city="Newtown"))]


def test_apply_edits_round_trips_address_preserving_pobox_and_extended():
    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:adr-rt\r\nFN:Old Name\r\nN:Name;Old;;;\r\n"
        "ADR;TYPE=HOME:PO Box 1;Apt 2;1 Main St;Springfield;IL;62704;USA\r\n"
        "X-CUSTOM-FLAG:keep-me\r\n"
        "END:VCARD\r\n"
    )
    existing = parse_vcard(raw)
    label, parts = existing.addresses[0]
    fields = ContactFields(
        given="New", family="Name",
        addresses=[(label, AddressParts(
            street="1 Main St", city="Springfield", region="IL", code="62704",
            country="USA", pobox=parts.pobox, extended=parts.extended,
        ))],
    )
    edited = apply_edits(raw, fields)
    contact = parse_vcard(edited)
    label2, parts2 = contact.addresses[0]
    assert parts2.pobox == "PO Box 1"
    assert parts2.extended == "Apt 2"
    assert "X-CUSTOM-FLAG:keep-me" in edited


def test_apply_edits_removes_address_when_no_rows_submitted():
    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:adr-rm\r\nFN:Old Name\r\nN:Name;Old;;;\r\n"
        "ADR;TYPE=HOME:;;1 Main St;Springfield;IL;62704;USA\r\n"
        "END:VCARD\r\n"
    )
    edited = apply_edits(raw, ContactFields(given="Old", family="Name"))
    contact = parse_vcard(edited)
    assert contact.addresses == []


def test_parse_vcard_reraises_original_error_for_non_photo_parse_failure(monkeypatch):
    import peopledb.vcard as vcard_mod

    def boom(_raw):
        raise ValueError("boom: unrelated to photo")

    monkeypatch.setattr(vcard_mod.vobject, "readOne", boom)
    with pytest.raises(ValueError, match="unrelated to photo"):
        parse_vcard(SIMPLE_CARD)


# -- set_photo / remove_photo (issue #11) -------------------------------------


NEW_JPEG_B64 = base64.b64encode(b"a" * 200).decode()  # long enough to force folding


def test_set_photo_v3_adds_folded_photo_line_and_reparses():
    from peopledb.vcard import set_photo

    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:setph-1\r\nFN:Set Photo\r\nN:Photo;Set;;;\r\n"
        "END:VCARD\r\n"
    )
    edited = set_photo(raw, NEW_JPEG_B64, "image/jpeg")
    assert "PHOTO;ENCODING=b;TYPE=JPEG:" in edited
    # Folded per RFC 6350: continuation lines start with a single space, each
    # physical line (post-fold) capped at 75 octets.
    lines = edited.split("\r\n")
    photo_lines = []
    capturing = False
    for line in lines:
        if line.startswith("PHOTO"):
            capturing = True
            photo_lines.append(line)
        elif capturing and line.startswith(" "):
            photo_lines.append(line)
        elif capturing:
            break
    assert len(photo_lines) > 1  # actually folded
    for line in photo_lines:
        assert len(line) <= 75
    for line in photo_lines[1:]:
        assert line.startswith(" ")

    contact = parse_vcard(edited)
    assert contact.photo_b64 == NEW_JPEG_B64
    assert contact.photo_media_type == "image/jpeg"


def test_set_photo_v4_uses_data_uri_form():
    from peopledb.vcard import set_photo

    raw = "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:setph-4\r\nFN:Set Four\r\nEND:VCARD\r\n"
    edited = set_photo(raw, NEW_JPEG_B64, "image/jpeg")
    assert "data:image/jpeg;base64," in edited
    contact = parse_vcard(edited)
    assert contact.photo_b64 == NEW_JPEG_B64
    assert contact.photo_media_type == "image/jpeg"


def test_set_photo_defaults_to_v3_dialect_when_version_missing():
    from peopledb.vcard import set_photo

    raw = "BEGIN:VCARD\r\nUID:setph-noversion\r\nFN:No Version\r\nEND:VCARD\r\n"
    edited = set_photo(raw, NEW_JPEG_B64, "image/jpeg")
    assert "PHOTO;ENCODING=b;TYPE=JPEG:" in edited


def test_set_photo_replaces_all_existing_photo_lines():
    from peopledb.vcard import set_photo

    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:setph-2\r\nFN:Replace Me\r\nN:Me;Replace;;;\r\n"
        f"PHOTO;ENCODING=b;TYPE=JPEG:{JPEG_B64}\r\n"
        "PHOTO;VALUE=uri:https://example.com/old.jpg\r\n"
        "END:VCARD\r\n"
    )
    edited = set_photo(raw, NEW_JPEG_B64, "image/jpeg")
    assert JPEG_B64 not in edited
    assert "https://example.com/old.jpg" not in edited
    contact = parse_vcard(edited)
    assert contact.photo_b64 == NEW_JPEG_B64


def test_set_photo_preserves_other_lines_byte_identical():
    from peopledb.vcard import set_photo

    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:setph-3\r\nFN:Keep Lines\r\nN:Lines;Keep;;;\r\n"
        "NOTE:A very long note that in principle could also be folded across mult\r\n"
        " iple physical lines just like PHOTO can be, testing preservation.\r\n"
        "X-CUSTOM-FLAG:keep-me\r\n"
        "END:VCARD\r\n"
    )
    edited = set_photo(raw, NEW_JPEG_B64, "image/jpeg")
    for line in raw.split("\r\n"):
        if line.startswith("PHOTO") or (line.startswith(" ") and False):
            continue
        assert line in edited.split("\r\n")
    assert "X-CUSTOM-FLAG:keep-me" in edited
    contact = parse_vcard(edited)
    assert "A very long note" in contact.note


def test_set_photo_preserves_lf_only_line_endings():
    from peopledb.vcard import set_photo

    raw = (
        "BEGIN:VCARD\nVERSION:3.0\nUID:setph-lf\nFN:LF Card\nN:Card;LF;;;\nEND:VCARD\n"
    )
    edited = set_photo(raw, NEW_JPEG_B64, "image/jpeg")
    assert "\r\n" not in edited
    assert "\nEND:VCARD" in edited
    contact = parse_vcard(edited)
    assert contact.photo_b64 == NEW_JPEG_B64


def test_remove_photo_deletes_photo_lines_only():
    from peopledb.vcard import remove_photo

    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:rmph-1\r\nFN:Remove Me\r\nN:Me;Remove;;;\r\n"
        f"PHOTO;ENCODING=b;TYPE=JPEG:{JPEG_B64}\r\n"
        "X-CUSTOM-FLAG:keep-me\r\n"
        "END:VCARD\r\n"
    )
    edited = remove_photo(raw)
    assert "PHOTO" not in edited
    assert "X-CUSTOM-FLAG:keep-me" in edited
    contact = parse_vcard(edited)
    assert contact.has_photo is False
    assert contact.formatted_name == "Remove Me"


def test_remove_photo_removes_folded_photo_continuation_lines():
    from peopledb.vcard import remove_photo

    half = len(JPEG_B64) // 2
    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:rmph-2\r\nFN:Fold Remove\r\n"
        f"PHOTO;ENCODING=b;TYPE=JPEG:{JPEG_B64[:half]}\r\n {JPEG_B64[half:]}\r\n"
        "END:VCARD\r\n"
    )
    edited = remove_photo(raw)
    assert "PHOTO" not in edited
    assert JPEG_B64[half:] not in edited
    contact = parse_vcard(edited)
    assert contact.has_photo is False


def test_remove_photo_is_noop_when_no_photo_present():
    from peopledb.vcard import remove_photo

    edited = remove_photo(SIMPLE_CARD)
    assert edited == SIMPLE_CARD


# -- mixed line endings (bug repro) -------------------------------------------

_MIXED_EOL_CARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Test\r\n"
    "PHOTO;ENCODING=b;TYPE=JPEG:AAAA\n"
    "END:VCARD\r\n"
)


def test_remove_photo_strips_photo_line_with_bare_lf_terminator_on_crlf_card():
    from peopledb.vcard import remove_photo

    edited = remove_photo(_MIXED_EOL_CARD)
    assert "PHOTO" not in edited
    contact = parse_vcard(edited)
    assert contact.has_photo is False


def test_set_photo_yields_exactly_one_photo_property_on_mixed_eol_card():
    from peopledb.vcard import set_photo

    edited = set_photo(_MIXED_EOL_CARD, NEW_JPEG_B64, "image/jpeg")
    assert edited.upper().count("PHOTO") == 1
    contact = parse_vcard(edited)
    assert contact.photo_b64 == NEW_JPEG_B64
